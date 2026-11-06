"""Builds the report inputs from the database and hands them to the pure rules in core.rules.report_rules."""
from decimal import Decimal

from accounts.models import Branch
from catalog.models import Item, Supplier
from core.labels import PETTY_CASH_ENTRY_LABELS
from core.rules.report_rules import balance_report, dispatch_report, purchase_report, usage_report
from inventory.models import OfficeIssue, Purchase
from inventory.services.stock import get_balances
from pettycash.models import PettyCashEntry
from vouchers.models import ExpenseCategory, Voucher, VoucherSchedule

REPORTS = {
    'balances': {'label': 'Current stock', 'title': 'Current stock', 'dated': False,
                 'description': 'What is in stock now, with its value at the last cost'},
    'purchases': {'label': 'Purchases', 'title': 'Purchases', 'dated': True,
                  'description': 'What was bought, from whom, and what is still to arrive'},
    'usage': {'label': 'Usage', 'title': 'Usage', 'dated': True, 'description': 'What was handed out to staff'},
    'dispatches': {'label': 'Dispatches', 'title': 'Dispatches', 'dated': True, 'needs_branch_module': True,
                   'description': 'What was sent to each branch and what arrived'},
    'petty_cash': {'label': 'Petty cash', 'title': 'Petty cash', 'dated': True,
                   'description': 'Cash received, spent and reversed'},
    'payment_vouchers': {'label': 'Payment vouchers', 'title': 'Payment vouchers', 'dated': True,
                         'needs_voucher_module': True,
                         'description': 'Payment vouchers, approvals, amounts and recurring schedule details'},
    'money_flow': {'label': 'Money flow', 'title': 'Money flow', 'dated': True, 'needs_voucher_module': True,
                   'description': 'Money movement from petty cash and approved payment vouchers'},
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


def petty_cash_report(rng, *, branch_id=None, entry_type=''):
    qs = PettyCashEntry.objects.select_related('branch', 'created_by').order_by('-entry_date', '-created_at', '-id')
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if entry_type in PETTY_CASH_ENTRY_LABELS:
        qs = qs.filter(type=entry_type)
    qs = _apply_dates(qs, 'entry_date', rng)
    rows = [{
        'date': entry.entry_date.strftime('%Y-%m-%d'),
        'branch': entry.branch.name,
        'description': entry.description or '—',
        'type': PETTY_CASH_ENTRY_LABELS.get(entry.type, {}).get('label', entry.type),
        'amount': entry.amount,
    } for entry in qs]
    return {
        'columns': [
            {'key': 'date', 'label': 'Date', 'type': 'code'},
            {'key': 'branch', 'label': 'Branch'},
            {'key': 'description', 'label': 'Description'},
            {'key': 'type', 'label': 'Type'},
            {'key': 'amount', 'label': 'Amount', 'type': 'money', 'sum': True},
        ],
        'rows': rows,
        'totals': {'amount': sum((row['amount'] for row in rows), Decimal('0.00'))},
    }


def payment_vouchers_report(rng, *, branch_id=None, status='', category_id=None, method='', schedule=''):
    qs = Voucher.objects.select_related('branch', 'category', 'prepared_by', 'approver', 'approved_by', 'schedule')
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if status in dict(Voucher.Status.choices):
        qs = qs.filter(status=status)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if method in dict(Voucher.PaymentMethod.choices):
        qs = qs.filter(method_of_payment=method)
    if schedule == 'scheduled':
        qs = qs.filter(schedule__isnull=False)
    elif schedule == 'unscheduled':
        qs = qs.filter(schedule__isnull=True)
    qs = _apply_dates(qs, 'date', rng).order_by('-date', '-created_at', '-id')
    rows = []
    approved_amount = pending_amount = Decimal('0.00')
    for v in qs:
        rows.append({
            'date': v.date.strftime('%Y-%m-%d'),
            'number': v.number or '—',
            'branch': v.branch.name,
            'payee': v.payee,
            'purpose': v.being,
            'category': v.category.name,
            'method': v.get_method_of_payment_display(),
            'status': v.get_status_display(),
            'schedule': v.schedule.title if v.schedule_id else '—',
            'scheduled_for': v.scheduled_for.strftime('%Y-%m-%d') if v.scheduled_for else '—',
            'prepared_by': v.prepared_by.name,
            'approved_by': v.approved_by.name if v.approved_by_id else '—',
            'amount': v.amount,
        })
        if v.status == Voucher.Status.APPROVED:
            approved_amount += v.amount
        elif v.status in (Voucher.Status.RECOMMENDING, Voucher.Status.PENDING):
            pending_amount += v.amount
    return {
        'columns': [
            {'key': 'date', 'label': 'Date', 'type': 'code'},
            {'key': 'number', 'label': 'Voucher', 'type': 'code'},
            {'key': 'branch', 'label': 'Branch'},
            {'key': 'payee', 'label': 'Payee'},
            {'key': 'purpose', 'label': 'Purpose'},
            {'key': 'category', 'label': 'Category'},
            {'key': 'method', 'label': 'Method'},
            {'key': 'status', 'label': 'Status', 'type': 'status'},
            {'key': 'schedule', 'label': 'Schedule'},
            {'key': 'scheduled_for', 'label': 'Scheduled for', 'type': 'code'},
            {'key': 'prepared_by', 'label': 'Prepared by'},
            {'key': 'approved_by', 'label': 'Approved by'},
            {'key': 'amount', 'label': 'Amount', 'type': 'money', 'sum': True},
        ],
        'rows': rows,
        'totals': {'amount': sum((row['amount'] for row in rows), Decimal('0.00'))},
        'meta_counts': {'count': len(rows), 'approved_amount': approved_amount, 'pending_amount': pending_amount},
    }


def money_flow_report(rng, *, branch_id=None):
    pc_qs = PettyCashEntry.objects.select_related('branch')
    if branch_id:
        pc_qs = pc_qs.filter(branch_id=branch_id)
    pc_qs = _apply_dates(pc_qs, 'entry_date', rng).order_by('entry_date', 'created_at', 'id')

    pv_qs = Voucher.objects.filter(status=Voucher.Status.APPROVED).select_related('branch', 'category')
    if branch_id:
        pv_qs = pv_qs.filter(branch_id=branch_id)
    pv_qs = _apply_dates(pv_qs, 'date', rng).order_by('date', 'created_at', 'id')

    rows = []
    petty_in = petty_out = voucher_out = Decimal('0.00')
    for entry in pc_qs:
        amount = entry.amount
        if amount >= 0:
            petty_in += amount
        else:
            petty_out += -amount
        rows.append({
            'date': entry.entry_date.strftime('%Y-%m-%d'),
            'branch': entry.branch.name,
            'source': 'Petty cash',
            'reference': f'PC-{entry.pk}',
            'description': entry.description or '—',
            'inflow': amount if amount > 0 else None,
            'outflow': -amount if amount < 0 else None,
            'amount': amount,
            '_sort': (entry.entry_date.isoformat(), f'a{entry.created_at.isoformat() if entry.created_at else ""}', entry.pk),
        })
    for v in pv_qs:
        voucher_out += v.amount
        rows.append({
            'date': v.date.strftime('%Y-%m-%d'),
            'branch': v.branch.name,
            'source': 'Payment voucher',
            'reference': v.number or '—',
            'description': f'{v.payee} — {v.being}',
            'inflow': None,
            'outflow': v.amount,
            'amount': -v.amount,
            '_sort': (v.date.isoformat(), f'b{v.created_at.isoformat() if v.created_at else ""}', v.pk),
        })
    rows.sort(key=lambda r: r['_sort'])
    for r in rows:
        r.pop('_sort', None)
    net = petty_in - petty_out - voucher_out
    return {
        'columns': [
            {'key': 'date', 'label': 'Date', 'type': 'code'},
            {'key': 'branch', 'label': 'Branch'},
            {'key': 'source', 'label': 'Source'},
            {'key': 'reference', 'label': 'Reference', 'type': 'code'},
            {'key': 'description', 'label': 'Description'},
            {'key': 'inflow', 'label': 'Inflow', 'type': 'money', 'sum': True},
            {'key': 'outflow', 'label': 'Outflow', 'type': 'money', 'sum': True},
            {'key': 'amount', 'label': 'Net amount', 'type': 'money', 'sum': True},
        ],
        'rows': rows,
        'totals': {'inflow': petty_in, 'outflow': petty_out + voucher_out, 'amount': net},
        'meta_counts': {'petty_in': petty_in, 'petty_out': petty_out, 'voucher_out': voucher_out, 'net': net},
    }


def filter_options(user_branch_id=None):
    """Choices for the filter boxes (main-office users get branch and supplier lists)."""
    branch_side = bool(user_branch_id)
    branches = [] if branch_side else list(Branch.objects.filter(active=True).order_by('type', 'name'))
    suppliers = [] if branch_side else list(Supplier.objects.order_by('name'))
    qs = OfficeIssue.objects.exclude(department='')
    if branch_side:
        qs = qs.filter(branch_id=user_branch_id)
    departments = sorted({d for d in qs.values_list('department', flat=True).distinct() if d}, key=str.lower)
    return {'branches': branches, 'suppliers': suppliers, 'departments': departments,
            'petty_cash_types': PETTY_CASH_ENTRY_LABELS,
            'voucher_statuses': Voucher.Status.choices, 'voucher_methods': Voucher.PaymentMethod.choices,
            'voucher_categories': list(ExpenseCategory.objects.order_by('name'))}
