from django.db import transaction
from django.utils import timezone

from accounts.models import Branch
from core.constants import BRANCH_TYPES, DISPATCH_STATUS, LEDGER_TYPES
from core.errors import BadRequest, Conflict, Forbidden, NotFound
from core.rules.purchase_rules import duplicate_item_problem
from core.rules.request_rules import close_plan, dispatch_plan, receipt_plan, status_after_dispatch
from core.services.audit import log_audit
from core.services.sequence import next_number
from branchops.models import Dispatch, DispatchLine, Request
from inventory.models import StockLedger
from inventory.services.common import assert_visible, usable_items
from inventory.services.stock import get_balances, get_main_branch, lock_items


def get_dispatch(user, pk, for_update=False):
    qs = Dispatch.objects.select_related('destination', 'request', 'dispatched_by', 'received_by')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    obj = qs.filter(pk=pk).first()
    assert_visible(user, obj, obj.destination_id if obj else None, 'Dispatch')
    return obj


def _transit(**kw):
    """Stock in transit is a ledger row with in_transit set and no branch."""
    return StockLedger(in_transit=True, source_model='Dispatch', **kw)


def create_dispatch(request, *, request_obj_id=None, destination_id=None, dispatch_date=None, lines):
    """Sends stock from the main office. The stock check, the ledger rows and the request update are one
    transaction, with the items locked first, so stock cannot be sent twice.
    lines: [{'item': Item, 'quantity': int}]  (zero quantities are ignored)."""
    user = request.user
    dup = duplicate_item_problem([l['item'].pk for l in lines])
    if dup:
        raise BadRequest(dup)
    main = get_main_branch()
    if not main:
        raise BadRequest('No main office exists. Run the seed command first')
    items = usable_items([l['item'].pk for l in lines], 'sent')
    names = {pk: i.name for pk, i in items.items()}
    dispatch_date = dispatch_date or timezone.localdate()

    with transaction.atomic():
        req = None
        dest_id = destination_id
        if request_obj_id:
            req = Request.objects.select_for_update(of=('self',)).filter(pk=request_obj_id).first()
            if not req:
                raise BadRequest('That request no longer exists')
            dest_id = req.branch_id
        destination = Branch.objects.filter(pk=dest_id).first() if dest_id else None
        if not destination or not destination.active or destination.type == BRANCH_TYPES.MAIN:
            raise BadRequest('Choose an active branch to send to')

        lock_items(items.keys())
        balances = get_balances(main.pk, items.keys())
        req_lines = list(req.lines.select_for_update(of=('self',))) if req else None
        plan = dispatch_plan(
            request_status=req.status if req else None, request_lines=req_lines, has_request=bool(req),
            requested=[{'item': l['item'].pk, 'quantity': l['quantity']} for l in lines], balances=balances, names=names)
        if plan.get('problem'):
            raise Conflict(plan['problem'])

        dispatch = Dispatch.objects.create(
            reference=next_number('DSP', yearly=True), request=req, destination=destination,
            dispatch_date=dispatch_date, dispatched_by=user)
        DispatchLine.objects.bulk_create([DispatchLine(dispatch=dispatch, item_id=p['item'], quantity_sent=p['quantity']) for p in plan['postings']])

        # Out of the main office, into transit.
        rows = []
        for p in plan['postings']:
            base = dict(item_id=p['item'], type=LEDGER_TYPES.DISPATCH_OUT, source_id=str(dispatch.pk), created_by=user)
            rows.append(StockLedger(branch=main, quantity_change=-p['quantity'], source_model='Dispatch', **base))
            rows.append(_transit(quantity_change=p['quantity'], **base))
        StockLedger.objects.bulk_create(rows)

        if req:
            for p in plan['postings']:
                line = next(l for l in req_lines if l.item_id == p['item'])
                line.quantity_dispatched = (line.quantity_dispatched or 0) + p['quantity']
                line.save(update_fields=['quantity_dispatched'])
            req.status = status_after_dispatch(req.status, req_lines)
            req.save(update_fields=['status', 'updated_at'])
    log_audit(request, 'dispatch.create', 'Dispatch', dispatch.pk,
              new_value={'reference': dispatch.reference, 'request': request_obj_id, 'destination': destination.pk,
                         'lines': plan['postings']})
    return dispatch


def receive_dispatch(request, pk, received):
    """The branch confirms what arrived. Received goods join the branch's stock; damaged or missing goods
    stay "in transit" until the main office closes the dispatch. received: [{'item','received','damaged'}]."""
    user = request.user
    with transaction.atomic():
        dispatch = get_dispatch(user, pk, for_update=True)
        if dispatch.destination_id != user.branch_id:
            raise Forbidden('Only the receiving branch can confirm this delivery')
        lines = list(dispatch.lines.select_for_update(of=('self',)))
        plan = receipt_plan(dispatch.status, lines, received)
        if plan.get('problem'):
            raise Conflict(plan['problem'])
        rows = []
        for o in plan['lines']:
            line = o['line']
            line.quantity_received, line.quantity_damaged, line.quantity_short = o['received'], o['damaged'], o['short']
            line.save(update_fields=['quantity_received', 'quantity_damaged', 'quantity_short'])
            if o['received'] > 0:
                base = dict(item_id=line.item_id, type=LEDGER_TYPES.BRANCH_RECEIPT, source_id=str(dispatch.pk), created_by=user)
                rows.append(_transit(quantity_change=-o['received'], **base))
                rows.append(StockLedger(branch_id=dispatch.destination_id, quantity_change=o['received'], source_model='Dispatch', **base))
        if rows:
            StockLedger.objects.bulk_create(rows)
        dispatch.status = plan['status']
        dispatch.received_by = user
        dispatch.received_at = timezone.now()
        dispatch.save()
    log_audit(request, 'dispatch.receive', 'Dispatch', dispatch.pk, new_value=received)
    return dispatch


def close_dispatch(request, pk, resolution, note=''):
    """Settles the damaged or missing goods: written off, or returned to the main office's stock."""
    user = request.user
    main = get_main_branch()
    if not main:
        raise BadRequest('No main office exists. Run the seed command first')
    with transaction.atomic():
        dispatch = Dispatch.objects.select_for_update(of=('self',)).filter(pk=pk).first()
        if not dispatch:
            raise NotFound('Dispatch not found')
        lines = list(dispatch.lines.all())
        plan = close_plan(dispatch.status, lines)
        if plan.get('problem'):
            raise Conflict(plan['problem'])
        rows = []
        for o in plan['leftovers']:
            base = dict(item_id=o['item'], type=LEDGER_TYPES.ADJUSTMENT, source_id=str(dispatch.pk), created_by=user)
            if resolution == 'return_to_main':
                qty = o['damaged'] + o['short']
                text = note or 'Returned to the main office'
                rows.append(_transit(quantity_change=-qty, reason='other', note=text, **base))
                rows.append(StockLedger(branch=main, quantity_change=qty, source_model='Dispatch', reason='other', note=text, **base))
            else:
                if o['damaged']:
                    rows.append(_transit(quantity_change=-o['damaged'], reason='damaged', note=note or 'Damaged in transit', **base))
                if o['short']:
                    rows.append(_transit(quantity_change=-o['short'], reason='other', note=note or 'Lost in transit', **base))
        if rows:
            StockLedger.objects.bulk_create(rows)
        dispatch.status = DISPATCH_STATUS.CLOSED
        dispatch.save(update_fields=['status', 'updated_at'])
    log_audit(request, 'dispatch.close', 'Dispatch', dispatch.pk, new_value={'resolution': resolution, 'note': note})
    return dispatch
