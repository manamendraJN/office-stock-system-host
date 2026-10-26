from django.db import transaction
from django.utils import timezone

from core.constants import ISSUE_STATUS, LEDGER_TYPES
from core.errors import BadRequest, Conflict
from core.rules.issue_rules import cancel_problem, shortage_problem
from core.rules.purchase_rules import duplicate_item_problem
from core.services.audit import log_audit
from core.services.sequence import next_number
from inventory.models import OfficeIssue, OfficeIssueLine, StockLedger
from inventory.services.common import assert_visible, usable_items, user_stock_branch_id
from inventory.services.stock import get_balances, get_main_branch, lock_items


def get_issue(user, pk, for_update=False):
    qs = OfficeIssue.objects.select_related('branch', 'issued_by', 'cancelled_by')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    issue = qs.filter(pk=pk).first()
    assert_visible(user, issue, issue.branch_id if issue else None, 'Issue')
    return issue


def issue_snapshot(issue, lines):
    return {'number': issue.number, 'recipient': issue.recipient, 'department': issue.department,
            'issue_date': issue.issue_date, 'purpose': issue.purpose,
            'lines': [{'item': l.item_id, 'quantity': l.quantity} for l in lines]}


def create_issue(request, data):
    """data: recipient, department, issue_date, purpose, lines [{item, quantity}].
    Reduces stock at the issuing branch. The stock check and the stock rows are one transaction, and the
    items are locked first so two people issuing the same item at once cannot both pass the check."""
    user = request.user
    lines = data['lines']
    dup = duplicate_item_problem([l['item'].pk for l in lines])
    if dup:
        raise BadRequest(dup)
    items = usable_items([l['item'].pk for l in lines], 'issued')
    names = {pk: i.name for pk, i in items.items()}
    main = get_main_branch()
    branch_id = user_stock_branch_id(user, main)
    if not branch_id:
        raise BadRequest('No main office exists. Run the seed command first')

    with transaction.atomic():
        lock_items(items.keys())
        balances = get_balances(branch_id, items.keys())
        wanted = [{'item': l['item'].pk, 'quantity': l['quantity']} for l in lines]
        problem = shortage_problem(wanted, balances, names)
        if problem:
            raise Conflict(problem)
        issue = OfficeIssue.objects.create(
            number=next_number('ISS', yearly=True), recipient=data['recipient'], department=data.get('department', ''),
            issue_date=data['issue_date'], purpose=data.get('purpose', ''), branch_id=branch_id, issued_by=user)
        made = OfficeIssueLine.objects.bulk_create([OfficeIssueLine(issue=issue, item=l['item'], quantity=l['quantity']) for l in lines])
        StockLedger.objects.bulk_create([
            StockLedger(item=l['item'], branch_id=branch_id, quantity_change=-l['quantity'], type=LEDGER_TYPES.OFFICE_ISSUE,
                        source_model='OfficeIssue', source_id=str(issue.pk), created_by=user)
            for l in lines])
    log_audit(request, 'issue.create', 'OfficeIssue', issue.pk, new_value=issue_snapshot(issue, made))
    return issue


def cancel_issue(request, pk, reason=''):
    """A mistaken issue is cancelled by posting reversal rows, never by deleting anything."""
    user = request.user
    with transaction.atomic():
        issue = get_issue(user, pk, for_update=True)
        problem = cancel_problem(issue.status)
        if problem:
            raise Conflict(problem)
        # Rebuild the reversal from the issue itself, so an aged ledger row removed by the 30-day
        # cleanup never makes an older issue impossible to cancel.
        main = get_main_branch()
        branch_id = issue.branch_id or (main.pk if main else None)
        if not branch_id:
            raise Conflict('Cannot find the branch for this issue')
        lines = list(issue.lines.all())
        lock_items([l.item_id for l in lines])
        StockLedger.objects.bulk_create([
            StockLedger(item_id=l.item_id, branch_id=branch_id, quantity_change=l.quantity, type=LEDGER_TYPES.REVERSAL,
                        source_model='OfficeIssue', source_id=str(issue.pk), reason=reason or 'Issue cancelled', created_by=user)
            for l in lines])
        issue.status = ISSUE_STATUS.CANCELLED
        issue.cancelled_by = user
        issue.cancelled_at = timezone.now()
        issue.cancel_reason = reason or ''
        issue.save()
    log_audit(request, 'issue.cancel', 'OfficeIssue', issue.pk, new_value={'reason': reason})
    return issue
