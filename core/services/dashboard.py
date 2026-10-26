"""The dashboard returns only the sections this user may see (ported from dashboardController.js).

A branch-side user sees their own branch only.
"""
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from catalog.models import Item
from core.constants import DISPATCH_STATUS, ISSUE_STATUS, LEDGER_TYPES, PURCHASE_STATUS, REQUEST_STATUS
from core.models import Setting
from core.permissions import effective_permissions, is_branch_side
from core.rules.report_rules import low_stock_items, month_range, spent_total


def build_dashboard(user):
    from branchops.models import Dispatch, Request
    from pettycash.models import PettyCashRequest
    from inventory.models import OfficeIssue, OfficeIssueLine, Purchase, StockLedger
    from inventory.services.stock import get_balances, get_main_branch

    have = effective_permissions(user)

    def can(*perms):
        return any(p in have for p in perms)

    branch_side = is_branch_side(user)
    own_branch_id = user.branch_id
    start, nxt = month_range(timezone.localdate())
    out = {'scope': {'branch_side': branch_side, 'branch_name': user.branch.name if branch_side else None}}

    if can('stock.view', 'items.view'):
        items = list(Item.objects.filter(active=True).values('id', 'code', 'name', 'unit', 'min_stock', 'active'))
        main = None if branch_side else get_main_branch()
        stock_branch = own_branch_id if branch_side else (main.pk if main else None)
        balances = get_balances(stock_branch, [i['id'] for i in items])
        out['low_stock'] = low_stock_items(items, balances)
        out['item_count'] = len(items)

    if can('purchases.view'):
        scope = {'branch_id': own_branch_id} if branch_side else {}
        awaiting = Purchase.objects.filter(**scope, status__in=[PURCHASE_STATUS.ORDERED, PURCHASE_STATUS.PARTLY_RECEIVED]).count()
        month = list(Purchase.objects.filter(**scope, purchase_date__gte=start, purchase_date__lt=nxt).prefetch_related('lines'))
        shaped = [{'status': p.status, 'lines': [{'quantity_ordered': l.quantity_ordered, 'unit_cost': l.unit_cost} for l in p.lines.all()]}
                  for p in month]
        out['purchases'] = {'awaiting_delivery': awaiting, 'spent_this_month': spent_total(shaped),
                            'count_this_month': sum(1 for p in month if p.status != PURCHASE_STATUS.CANCELLED)}

    if can('issues.view'):
        scope = {'branch_id': own_branch_id} if branch_side else {}
        issues = OfficeIssue.objects.filter(**scope, status=ISSUE_STATUS.ISSUED, issue_date__gte=start, issue_date__lt=nxt)
        units = OfficeIssueLine.objects.filter(issue__in=issues).aggregate(n=Sum('quantity'))['n'] or 0
        out['issues'] = {'count_this_month': issues.count(), 'units_this_month': units}

    if can('stock.view'):
        qs = StockLedger.objects.exclude(type=LEDGER_TYPES.OPENING_BALANCE).select_related('item', 'branch', 'created_by')
        if branch_side:
            qs = qs.filter(branch_id=own_branch_id)
        out['recent_movements'] = list(qs.order_by('-created_at', '-id')[:8])

    if can('petty_cash.view', 'petty_cash.request', 'petty_cash.approve', 'petty_cash.configure'):
        from pettycash import services as petty
        sums = petty.branch_summaries(user)
        out['petty_cash'] = {
            'all_branches': petty.scope_branch_id(user) is None,
            'balance': sum((s['balance'] for s in sums), Decimal('0.00')),
            'low_count': sum(1 for s in sums if s['low']),
            'waiting': PettyCashRequest.objects.filter(status='submitted', **({} if petty.scope_branch_id(user) is None else {'branch_id': own_branch_id})).count(),
            'low_level': petty.get_low_level()}

    # The branch module switch gates the branch-workflow tiles.
    if Setting.get().branch_module_enabled:
        if can('requests.review', 'requests.create', 'dispatches.manage'):
            scope = {'branch_id': own_branch_id} if branch_side else {}
            out['requests'] = {
                'waiting_for_review': Request.objects.filter(**scope, status=REQUEST_STATUS.SUBMITTED).count(),
                'ready_to_send': Request.objects.filter(**scope, status__in=[REQUEST_STATUS.APPROVED, REQUEST_STATUS.PARTLY_APPROVED]).count(),
            }
        if can('dispatches.manage', 'dispatches.receive'):
            scope = {'destination_id': own_branch_id} if branch_side else {}
            out['dispatches'] = {
                'in_transit': Dispatch.objects.filter(**scope, status=DISPATCH_STATUS.IN_TRANSIT).count(),
                'with_differences': Dispatch.objects.filter(**scope, status=DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES).count(),
            }
    return out
