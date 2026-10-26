from django.db import transaction
from django.utils import timezone

from core.constants import BRANCH_TYPES, REQUEST_STATUS
from core.errors import BadRequest, Conflict, Forbidden
from core.rules.purchase_rules import duplicate_item_problem
from core.rules.request_rules import cancel_request_problem, review_plan
from core.services.audit import log_audit
from core.services.sequence import next_number
from branchops.models import Request, RequestLine
from inventory.services.common import assert_visible, usable_items


def get_request(user, pk, for_update=False):
    qs = Request.objects.select_related('branch', 'requested_by', 'reviewed_by')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    obj = qs.filter(pk=pk).first()
    assert_visible(user, obj, obj.branch_id if obj else None, 'Request')
    return obj


def create_request(request, notes, lines):
    """lines: [{'item': Item, 'quantity': int}]. Raised by a branch for its own stock."""
    user = request.user
    branch = user.branch
    if not branch or branch.type == BRANCH_TYPES.MAIN:
        raise BadRequest('Requests are raised by branches. The main office does not request items from itself')
    dup = duplicate_item_problem([l['item'].pk for l in lines])
    if dup:
        raise BadRequest(dup)
    usable_items([l['item'].pk for l in lines], 'requested')
    with transaction.atomic():
        req = Request.objects.create(number=next_number('REQ', yearly=True), branch=branch, notes=notes or '', requested_by=user)
        RequestLine.objects.bulk_create([RequestLine(request=req, item=l['item'], quantity_requested=l['quantity']) for l in lines])
    log_audit(request, 'request.create', 'Request', req.pk,
              new_value={'number': req.number, 'notes': notes, 'lines': [{'item': l['item'].pk, 'quantity': l['quantity']} for l in lines]})
    return req


def cancel_request(request, pk):
    """Only the branch that raised it can withdraw it, and only before it is reviewed."""
    user = request.user
    with transaction.atomic():
        req = get_request(user, pk, for_update=True)
        if req.branch_id != user.branch_id:
            raise Forbidden('Only the branch that raised this request can cancel it')
        problem = cancel_request_problem(req.status)
        if problem:
            raise Conflict(problem)
        req.status = REQUEST_STATUS.CANCELLED
        req.save(update_fields=['status', 'updated_at'])
    log_audit(request, 'request.cancel', 'Request', req.pk)
    return req


def review_request(request, pk, decisions):
    """The main office decides every line: approve in full, reduce (with a reason) or reject.
    decisions: [{'line_id', 'quantity_approved', 'reason'}]."""
    user = request.user
    with transaction.atomic():
        req = get_request(user, pk, for_update=True)
        lines = list(req.lines.select_for_update(of=('self',)))
        plan = review_plan(req.status, lines, decisions)
        if plan.get('problem'):
            raise Conflict(plan['problem'])
        for line, qty, reason in plan['lines']:
            line.quantity_approved = qty
            line.reason = reason
            line.save(update_fields=['quantity_approved', 'reason'])
        req.status = plan['status']
        req.reviewed_by = user
        req.reviewed_at = timezone.now()
        req.save()
    log_audit(request, 'request.review', 'Request', req.pk, new_value=decisions)
    return req
