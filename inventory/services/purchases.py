from django.db import transaction
from django.utils import timezone

from catalog.models import Item
from core.constants import LEDGER_TYPES, PURCHASE_STATUS
from core.errors import BadRequest, Conflict
from core.rules.purchase_rules import (duplicate_item_problem, locked_problem, receipt_plan,
                                       status_from_lines)
from core.services.audit import log_audit
from core.services.sequence import next_number
from inventory.models import Purchase, PurchaseLine, StockLedger
from inventory.services.common import assert_visible, usable_items, user_stock_branch_id
from inventory.services.stock import get_main_branch


def purchase_snapshot(p, lines=None):
    lines = lines if lines is not None else list(p.lines.all())
    return {
        'number': p.number, 'supplier': p.supplier_id, 'purchase_date': p.purchase_date, 'invoice_ref': p.invoice_ref,
        'notes': p.notes, 'status': p.status,
        'lines': [{'item': l.item_id, 'quantity_ordered': l.quantity_ordered, 'unit_cost': l.unit_cost} for l in lines],
    }


def _check_usable(supplier, lines):
    if supplier is None:
        raise BadRequest('Choose a valid supplier')
    if not supplier.active:
        raise BadRequest('That supplier is inactive. Choose an active supplier')
    dup = duplicate_item_problem([l['item'].pk for l in lines])
    if dup:
        raise BadRequest(dup)
    usable_items([l['item'].pk for l in lines], 'purchased')


def get_purchase(user, pk, for_update=False):
    qs = Purchase.objects.select_related('supplier', 'branch', 'created_by')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    purchase = qs.filter(pk=pk).first()
    assert_visible(user, purchase, purchase.branch_id if purchase else None, 'Purchase')
    return purchase


def create_purchase(request, data):
    """data: supplier (Supplier), purchase_date, invoice_ref, notes, lines [{item, quantity_ordered, unit_cost}]."""
    user = request.user
    _check_usable(data['supplier'], data['lines'])
    main = get_main_branch()
    branch_id = user_stock_branch_id(user, main)
    if not branch_id:
        raise BadRequest('No main office exists. Run the seed command first')
    with transaction.atomic():
        purchase = Purchase.objects.create(
            number=next_number('PUR', yearly=True), supplier=data['supplier'], purchase_date=data['purchase_date'],
            invoice_ref=data.get('invoice_ref', ''), notes=data.get('notes', ''), branch_id=branch_id, created_by=user)
        PurchaseLine.objects.bulk_create([
            PurchaseLine(purchase=purchase, item=l['item'], quantity_ordered=l['quantity_ordered'], unit_cost=l['unit_cost'])
            for l in data['lines']])
    log_audit(request, 'purchase.create', 'Purchase', purchase.pk, new_value=purchase_snapshot(purchase))
    return purchase


def update_purchase(request, pk, data):
    """Only a purchase with nothing received yet can be edited; the lines are replaced as a whole."""
    with transaction.atomic():
        purchase = get_purchase(request.user, pk, for_update=True)
        existing = list(purchase.lines.all())
        problem = locked_problem(purchase.status, existing, 'edited')
        if problem:
            raise Conflict(problem)
        _check_usable(data['supplier'], data['lines'])
        old = purchase_snapshot(purchase, existing)
        purchase.supplier = data['supplier']
        purchase.purchase_date = data['purchase_date']
        purchase.invoice_ref = data.get('invoice_ref', '')
        purchase.notes = data.get('notes', '')
        purchase.save()
        purchase.lines.all().delete()
        PurchaseLine.objects.bulk_create([
            PurchaseLine(purchase=purchase, item=l['item'], quantity_ordered=l['quantity_ordered'], unit_cost=l['unit_cost'])
            for l in data['lines']])
    log_audit(request, 'purchase.update', 'Purchase', purchase.pk, old_value=old, new_value=purchase_snapshot(purchase))
    return purchase


def cancel_purchase(request, pk):
    with transaction.atomic():
        purchase = get_purchase(request.user, pk, for_update=True)
        problem = locked_problem(purchase.status, list(purchase.lines.all()), 'cancelled')
        if problem:
            raise Conflict(problem)
        purchase.status = PURCHASE_STATUS.CANCELLED
        purchase.save(update_fields=['status', 'updated_at'])
    log_audit(request, 'purchase.cancel', 'Purchase', purchase.pk)
    return purchase


def receive_purchase(request, pk, requested):
    """requested: [{'line_id', 'quantity'}]. Posts received quantities into the stock of the purchase's branch
    (the main office for older purchases). One transaction, so a purchase is never marked received without
    its stock rows (or the reverse). If two people press Receive at once, the second re-reads and is checked again."""
    user = request.user
    with transaction.atomic():
        purchase = get_purchase(user, pk, for_update=True)
        stock_branch_id = purchase.branch_id or (get_main_branch().pk if get_main_branch() else None)
        if not stock_branch_id:
            raise BadRequest('No main office exists. Run the seed command first')
        lines = list(purchase.lines.select_for_update(of=('self',)))
        plan = receipt_plan(purchase.status, lines, requested)
        if plan.get('problem'):
            raise Conflict(plan['problem'])

        rows = []
        for line, quantity in plan['postings']:
            line.quantity_received = (line.quantity_received or 0) + quantity
            line.save(update_fields=['quantity_received'])
            rows.append(StockLedger(
                item_id=line.item_id, branch_id=stock_branch_id, quantity_change=quantity,
                type=LEDGER_TYPES.PURCHASE_RECEIPT, source_model='Purchase', source_id=str(purchase.pk), created_by=user))
            Item.objects.filter(pk=line.item_id).update(last_unit_cost=line.unit_cost, updated_at=timezone.now())
        purchase.status = status_from_lines(lines)
        purchase.save(update_fields=['status', 'updated_at'])
        StockLedger.objects.bulk_create(rows)
        posted = [{'item': l.item_id, 'quantity': q} for l, q in plan['postings']]
    log_audit(request, 'purchase.receive', 'Purchase', purchase.pk, new_value=posted)
    return purchase
