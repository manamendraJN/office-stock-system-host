"""Builds the report inputs from the database and hands them to the pure rules in core.rules.report_rules."""
from accounts.models import Branch
from catalog.models import Item, Supplier
from core.rules.report_rules import balance_report, dispatch_report, purchase_report, usage_report
from inventory.models import OfficeIssue, Purchase
from inventory.services.stock import get_balances

REPORTS = {
    'balances': {'label': 'Current stock', 'title': 'Current stock', 'dated': False,
                 'description': 'What is in stock now, with its value at the last cost'},
    'purchases': {'label': 'Purchases', 'title': 'Purchases', 'dated': True,
                  'description': 'What was bought, from whom, and what is still to arrive'},
    'usage': {'label': 'Usage', 'title': 'Usage', 'dated': True, 'description': 'What was handed out to staff'},
    'dispatches': {'label': 'Dispatches', 'title': 'Dispatches', 'dated': True, 'needs_branch_module': True,
                   'description': 'What was sent to each branch and what arrived'},
}


def _item(i):
    return {'id': i.pk, 'code': i.code, 'name': i.name, 'unit': i.unit}


def _apply_dates(qs, field, rng):
    if rng.get('from'):
        qs = qs.filter(**{f'{field}__gte': rng['from']})
    if rng.get('to'):
        qs = qs.filter(**{f'{field}__lte': rng['to']})
    return qs


def stock_report(branch, low_only=False):
    items = list(Item.objects.select_related('category'))
    balances = get_balances(branch.pk)
    data = [{'id': i.pk, 'code': i.code, 'name': i.name, 'category': i.category.name, 'unit': i.unit,
             'min_stock': i.min_stock, 'last_unit_cost': i.last_unit_cost, 'active': i.active} for i in items]
    return balance_report(data, balances, low_only=low_only)


def purchases_report(rng, *, branch_id=None, supplier_id=None, by='supplier'):
    qs = Purchase.objects.select_related('supplier').prefetch_related('lines__item')
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    qs = _apply_dates(qs, 'purchase_date', rng)
    data = [{'id': p.pk, 'status': p.status, 'supplier': {'id': p.supplier_id, 'name': p.supplier.name},
             'lines': [{'item': _item(l.item), 'quantity_ordered': l.quantity_ordered,
                        'quantity_received': l.quantity_received, 'unit_cost': l.unit_cost} for l in p.lines.all()]}
            for p in qs]
    return purchase_report(data, by='item' if by == 'item' else 'supplier')


def usage_report_data(rng, *, branch_id=None, department='', by='item'):
    qs = OfficeIssue.objects.prefetch_related('lines__item')
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if department:
        qs = qs.filter(department__iexact=department.strip())
    qs = _apply_dates(qs, 'issue_date', rng)
    data = [{'id': i.pk, 'status': i.status, 'department': i.department,
             'lines': [{'item': _item(l.item), 'quantity': l.quantity} for l in i.lines.all()]} for i in qs]
    return usage_report(data, by='department' if by == 'department' else 'item')


def dispatches_report(rng, *, destination_id=None):
    from branchops.models import Dispatch
    qs = Dispatch.objects.select_related('destination').prefetch_related('lines__item')
    if destination_id:
        qs = qs.filter(destination_id=destination_id)
    qs = _apply_dates(qs, 'dispatch_date', rng)
    data = [{'id': d.pk, 'destination': {'id': d.destination_id, 'name': d.destination.name},
             'lines': [{'item': _item(l.item), 'quantity_sent': l.quantity_sent, 'quantity_received': l.quantity_received,
                        'quantity_damaged': l.quantity_damaged, 'quantity_short': l.quantity_short} for l in d.lines.all()]}
            for d in qs]
    return dispatch_report(data)


def filter_options(user_branch_id=None):
    """Choices for the filter boxes (main-office users get branch and supplier lists)."""
    branch_side = bool(user_branch_id)
    branches = [] if branch_side else list(Branch.objects.filter(active=True).order_by('type', 'name'))
    suppliers = [] if branch_side else list(Supplier.objects.order_by('name'))
    qs = OfficeIssue.objects.exclude(department='')
    if branch_side:
        qs = qs.filter(branch_id=user_branch_id)
    departments = sorted({d for d in qs.values_list('department', flat=True).distinct() if d}, key=str.lower)
    return {'branches': branches, 'suppliers': suppliers, 'departments': departments}
