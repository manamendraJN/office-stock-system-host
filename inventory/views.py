import json
from datetime import datetime, time
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Branch
from catalog.models import Item, Supplier
from core.constants import LEDGER_TYPES, PURCHASE_STATUS
from core.decorators import permission_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.labels import (ISSUE_STATUS_LABELS, MOVEMENT_TYPES, PURCHASE_STATUS_LABELS, REASON_LABELS, REASONS_FOR)
from core.lines import parse_lines, parse_pairs, whole_number
from core.permissions import has_any, is_branch_side
from core.rules.issue_rules import total_units
from core.rules.purchase_rules import has_receipts, purchase_total
from core.rules.report_rules import parse_range
from inventory import forms as inv_forms
from inventory.models import OfficeIssue, Purchase, StockLedger
from inventory.services import adjustments, issues, purchases
from inventory.services.stock import get_balances, get_main_branch

PAGE_SIZE = 50
BLANK_ROW = {'item_id': '', 'errors': {}, 'raw': {'item': '', 'quantity': '', 'unit_cost': ''}}


def _day_bounds(range_):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(range_['from'], time.min), tz) if range_.get('from') else None
    end = timezone.make_aware(datetime.combine(range_['to'], time.max), tz) if range_.get('to') else None
    return start, end


def _date_range(request):
    """(from_text, to_text, range, problem). A bad date is shown as an error rather than ignored."""
    f, t = request.GET.get('from', ''), request.GET.get('to', '')
    r = parse_range(f, t)
    return f, t, r, r.get('problem')


def _item_options(user, only_in_stock=False):
    """Active items with their stock at the user's own branch (main office for main-side users)."""
    items = list(Item.objects.filter(active=True).order_by('name'))
    branch_id = user.branch_id if is_branch_side(user) else (get_main_branch().pk if get_main_branch() else None)
    balances = get_balances(branch_id, [i.pk for i in items])
    for i in items:
        i.stock = balances.get(i.pk, 0)
    return [i for i in items if i.stock > 0] if only_in_stock else items


# ================================================================== purchases
def _purchase_view_model(p):
    lines = list(p.lines.all())
    return {
        'p': p, 'lines': lines, 'total': purchase_total(lines),
        'total_ordered': sum(l.quantity_ordered for l in lines),
        'total_received': sum(l.quantity_received or 0 for l in lines),
    }


@permission_required('purchases.view')
def purchase_list(request):
    g = request.GET
    search, status, supplier = g.get('q', '').strip(), g.get('status', ''), g.get('supplier', '')
    f, t, rng, problem = _date_range(request)
    qs = Purchase.objects.select_related('supplier', 'branch', 'created_by').prefetch_related('lines')
    if is_branch_side(request.user):
        qs = qs.filter(branch_id=request.user.branch_id)
    if status in PURCHASE_STATUS_LABELS:
        qs = qs.filter(status=status)
    if supplier.isdigit():
        qs = qs.filter(supplier_id=int(supplier))
    if search:
        qs = qs.filter(Q(number__icontains=search) | Q(invoice_ref__icontains=search) | Q(supplier__name__icontains=search))
    if not problem:
        if rng.get('from'):
            qs = qs.filter(purchase_date__gte=rng['from'])
        if rng.get('to'):
            qs = qs.filter(purchase_date__lte=rng['to'])
    rows = [_purchase_view_model(p) for p in qs.order_by('-purchase_date', '-created_at')]
    spent = sum((r['total'] for r in rows if r['p'].status != PURCHASE_STATUS.CANCELLED), Decimal(0))
    return render(request, 'inventory/purchase_list.html', {
        'rows': rows, 'spent': spent, 'problem': problem, 'suppliers': Supplier.objects.order_by('name'),
        'statuses': PURCHASE_STATUS_LABELS, 'f': {'q': search, 'status': status, 'supplier': supplier, 'from': f, 'to': t},
        'filters_on': any([search, status, supplier, f, t]), 'show_branch': not is_branch_side(request.user),
        'can_manage': has_any(request.user, ['purchases.manage'])})


@permission_required('purchases.view')
def purchase_detail(request, pk):
    p = purchases.get_purchase(request.user, pk)
    vm = _purchase_view_model(p)
    open_ = p.status in (PURCHASE_STATUS.ORDERED, PURCHASE_STATUS.PARTLY_RECEIVED)
    return render(request, 'inventory/purchase_detail.html', {
        **vm, 'open': open_, 'has_receipts': has_receipts(vm['lines']), 'cancelled': p.status == PURCHASE_STATUS.CANCELLED,
        'show_branch_name': not is_branch_side(request.user),
        'can_manage': has_any(request.user, ['purchases.manage']), 'can_receive': has_any(request.user, ['purchases.receive'])})


def _line_rows_from_purchase(p):
    return [{'item_id': l.item_id, 'errors': {}, 'raw': {'item': str(l.item_id), 'quantity': str(l.quantity_ordered),
                                                       'unit_cost': f'{l.unit_cost:.2f}'}} for l in p.lines.all()]


def _purchase_form(request, purchase=None):
    initial = ({'supplier': purchase.supplier_id, 'purchase_date': purchase.purchase_date, 'invoice_ref': purchase.invoice_ref,
                'notes': purchase.notes} if purchase else {'purchase_date': timezone.localdate()})
    form = inv_forms.PurchaseHeaderForm(request.POST or None, initial=initial,
                                        current_supplier_id=purchase.supplier_id if purchase else None)
    line_error = None
    if request.method == 'POST':
        rows, lines_ok = parse_lines(request.POST, kind='purchase')
        if form.is_valid() and lines_ok:
            cd = form.cleaned_data
            data = {'supplier': cd['supplier'], 'purchase_date': cd['purchase_date'], 'invoice_ref': cd['invoice_ref'], 'notes': cd['notes'],
                    'lines': [{'item': r['item'], 'quantity_ordered': r['quantity'], 'unit_cost': r['unit_cost']} for r in rows]}
            try:
                if purchase is None:
                    p = purchases.create_purchase(request, data)
                    messages.success(request, 'Purchase recorded')
                else:
                    p = purchases.update_purchase(request, purchase.pk, data)
                    messages.success(request, 'Purchase updated')
                return redirect('inventory:purchase_detail', pk=p.pk)
            except ServiceError as exc:
                if exc.field_errors and set(exc.field_errors) & set(form.fields):
                    apply_service_error(form, exc)
                else:
                    line_error = exc.message
        elif not rows:
            line_error = 'Add at least one item'
        else:
            messages.error(request, 'Please check the highlighted fields.')
    else:
        rows = _line_rows_from_purchase(purchase) if purchase else [{'item_id': '', 'errors': {}, 'raw': {'item': '', 'quantity': '', 'unit_cost': ''}}]
    return render(request, 'inventory/purchase_form.html', {
        'form': form, 'purchase': purchase, 'rows': rows, 'line_error': line_error,
        'items': Item.objects.filter(active=True).order_by('name'), 'blank_row': BLANK_ROW,
        'today': timezone.localdate().isoformat()})


@permission_required('purchases.manage')
def purchase_create(request):
    return _purchase_form(request)


@permission_required('purchases.manage')
def purchase_edit(request, pk):
    p = purchases.get_purchase(request.user, pk)
    problem = None
    from core.rules.purchase_rules import locked_problem
    problem = locked_problem(p.status, list(p.lines.all()), 'edited')
    if problem:
        messages.error(request, problem)
        return redirect('inventory:purchase_detail', pk=p.pk)
    return _purchase_form(request, p)


@permission_required('purchases.manage')
@require_POST
def purchase_cancel(request, pk):
    try:
        purchases.cancel_purchase(request, pk)
        messages.success(request, 'Purchase cancelled')
    except ServiceError as exc:
        if exc.status == 404:
            raise  # shown as a "not found" page by the middleware
        messages.error(request, exc.message)
    return redirect('inventory:purchase_detail', pk=pk)


@permission_required('purchases.receive')
def purchase_receive(request, pk):
    p = purchases.get_purchase(request.user, pk)
    lines = list(p.lines.all())
    if p.status not in (PURCHASE_STATUS.ORDERED, PURCHASE_STATUS.PARTLY_RECEIVED):
        messages.error(request, 'This purchase was cancelled' if p.status == PURCHASE_STATUS.CANCELLED else 'This purchase is already fully received')
        return redirect('inventory:purchase_detail', pk=p.pk)
    errors = {}
    values = {l.pk: str(l.quantity_ordered - (l.quantity_received or 0)) for l in lines}
    if request.method == 'POST':
        pairs = parse_pairs(request.POST, ['receive'])
        requested = []
        for l in lines:
            raw = pairs.get(l.pk, {}).get('receive', '')
            values[l.pk] = raw
            if l.quantity_ordered - (l.quantity_received or 0) <= 0:
                continue
            n, err = whole_number(raw, 0)
            if err:
                errors[l.pk] = err
            else:
                requested.append({'line_id': l.pk, 'quantity': n})
        if not errors:
            if sum(r['quantity'] for r in requested) == 0:
                messages.error(request, 'Enter a quantity for at least one item')
            else:
                try:
                    purchases.receive_purchase(request, pk, requested)
                    messages.success(request, 'Stock updated. The items now show the new quantities.')
                    return redirect('inventory:purchase_detail', pk=pk)
                except ServiceError as exc:
                    messages.error(request, exc.message)
    rows = [{'l': l, 'outstanding': l.quantity_ordered - (l.quantity_received or 0), 'value': values.get(l.pk, ''), 'error': errors.get(l.pk)} for l in lines]
    return render(request, 'inventory/purchase_receive.html', {'p': p, 'rows': rows})


# ================================================================== office issues
def _issue_view_model(i):
    lines = list(i.lines.all())
    return {'i': i, 'lines': lines, 'units': total_units(lines)}


@permission_required('issues.view')
def issue_list(request):
    g = request.GET
    search, status = g.get('q', '').strip(), g.get('status', '')
    f, t, rng, problem = _date_range(request)
    qs = OfficeIssue.objects.select_related('branch', 'issued_by', 'cancelled_by').prefetch_related('lines')
    if is_branch_side(request.user):
        qs = qs.filter(branch_id=request.user.branch_id)
    if status in ISSUE_STATUS_LABELS:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(Q(number__icontains=search) | Q(recipient__icontains=search) | Q(department__icontains=search))
    if not problem:
        if rng.get('from'):
            qs = qs.filter(issue_date__gte=rng['from'])
        if rng.get('to'):
            qs = qs.filter(issue_date__lte=rng['to'])
    rows = [_issue_view_model(i) for i in qs.order_by('-issue_date', '-created_at')]
    return render(request, 'inventory/issue_list.html', {
        'rows': rows, 'problem': problem, 'statuses': ISSUE_STATUS_LABELS, 'f': {'q': search, 'status': status, 'from': f, 'to': t},
        'filters_on': any([search, status, f, t]), 'show_branch': not is_branch_side(request.user),
        'can_issue': has_any(request.user, ['issues.manage']), 'branch_side': is_branch_side(request.user)})


@permission_required('issues.view')
def issue_detail(request, pk):
    issue = issues.get_issue(request.user, pk)
    form = inv_forms.CancelIssueForm()
    return render(request, 'inventory/issue_detail.html', {
        **_issue_view_model(issue), 'form': form, 'cancelled': issue.status == 'cancelled',
        'can_issue': has_any(request.user, ['issues.manage']), 'show_branch': not is_branch_side(request.user)})


@permission_required('issues.manage')
def issue_create(request):
    form = inv_forms.IssueHeaderForm(request.POST or None, initial={'issue_date': timezone.localdate()})
    options = _item_options(request.user)
    line_error = None
    if request.method == 'POST':
        rows, lines_ok = parse_lines(request.POST, kind='simple')
        if form.is_valid() and lines_ok:
            cd = form.cleaned_data
            data = {'recipient': cd['recipient'], 'department': cd['department'], 'issue_date': cd['issue_date'], 'purpose': cd['purpose'],
                    'lines': [{'item': r['item'], 'quantity': r['quantity']} for r in rows]}
            try:
                issue = issues.create_issue(request, data)
                messages.success(request, 'Items issued. Stock has been reduced.')
                return redirect('inventory:issue_detail', pk=issue.pk)
            except ServiceError as exc:
                line_error = exc.message
        elif not rows:
            line_error = 'Add at least one item'
        else:
            messages.error(request, 'Please check the highlighted fields.')
    else:
        rows = [{'item_id': '', 'errors': {}, 'raw': {'item': '', 'quantity': '', 'unit_cost': ''}}]
    return render(request, 'inventory/issue_form.html', {
        'form': form, 'rows': rows, 'line_error': line_error, 'items': [i for i in options if i.stock > 0 or str(i.pk) in
                                                                        {r['raw']['item'] for r in rows}],
        'nothing_in_stock': all(i.stock <= 0 for i in options), 'blank_row': BLANK_ROW, 'show_stock': True,
        'today': timezone.localdate().isoformat()})


@permission_required('issues.manage')
@require_POST
def issue_cancel(request, pk):
    form = inv_forms.CancelIssueForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Use 200 characters or fewer')
        return redirect('inventory:issue_detail', pk=pk)
    try:
        issues.cancel_issue(request, pk, form.cleaned_data['reason'])
        messages.success(request, 'Issue cancelled. The items are back in stock.')
    except ServiceError as exc:
        if exc.status == 404:
            raise
        messages.error(request, exc.message)
    return redirect('inventory:issue_detail', pk=pk)


# ================================================================== stock & movements
def _balance_rows(branch):
    items = list(Item.objects.select_related('category').order_by('name'))
    balances = get_balances(branch.pk)
    rows = []
    for i in items:
        qty = balances.get(i.pk, 0)
        # Inactive items only matter while they still hold stock.
        if not i.active and qty == 0:
            continue
        rows.append({'item': i, 'quantity': qty, 'low': i.active and qty <= i.min_stock})
    return rows


def _resolve_branch(request, requested):
    try:
        return adjustments.resolve_branch(request.user, requested)
    except ServiceError as exc:
        messages.error(request, exc.message)
        return adjustments.resolve_branch(request.user, None)


def _movement_ref_numbers(rows):
    from branchops.models import Dispatch
    ids = {}
    for r in rows:
        if r.source_model and r.source_id.isdigit():
            ids.setdefault(r.source_model, set()).add(int(r.source_id))
    out = {}
    if ids.get('Purchase'):
        out.update({('Purchase', p.pk): p.number for p in Purchase.objects.filter(pk__in=ids['Purchase']).only('number')})
    if ids.get('OfficeIssue'):
        out.update({('OfficeIssue', p.pk): p.number for p in OfficeIssue.objects.filter(pk__in=ids['OfficeIssue']).only('number')})
    if ids.get('Dispatch'):
        out.update({('Dispatch', d.pk): d.reference for d in Dispatch.objects.filter(pk__in=ids['Dispatch']).only('reference')})
    return out


@permission_required('stock.view')
def stock_page(request):
    user = request.user
    tab = 'movements' if request.GET.get('tab') == 'movements' else 'stock'
    can_adjust = has_any(user, ['stock.adjust'])
    branch = _resolve_branch(request, request.GET.get('branch') if tab == 'stock' else None)
    branches = [] if is_branch_side(user) else list(Branch.objects.filter(active=True).order_by('type', 'name'))
    can_pick_branch = len(branches) > 1
    ctx = {'tab': tab, 'branch': branch, 'branches': branches, 'can_pick_branch': can_pick_branch, 'can_adjust': can_adjust}

    if tab == 'stock':
        rows = _balance_rows(branch) if branch else []
        q = request.GET.get('q', '').strip().lower()
        low_only = request.GET.get('low') == '1'
        shown = [r for r in rows if (not low_only or r['low']) and (not q or q in r['item'].name.lower() or q in r['item'].code.lower())]
        ctx.update({'rows': shown, 'f': {'q': request.GET.get('q', ''), 'low': low_only}, 'filters_on': bool(q or low_only)})
        return render(request, 'inventory/stock.html', ctx)

    g = request.GET
    branch_f, item_f, type_f = g.get('branch', ''), g.get('item', ''), g.get('type', '')
    f, t, rng, problem = _date_range(request)
    qs = StockLedger.objects.exclude(type=LEDGER_TYPES.OPENING_BALANCE).select_related('item', 'branch', 'created_by')
    if is_branch_side(user):
        qs = qs.filter(branch_id=user.branch_id)
    elif branch_f == 'in_transit':
        qs = qs.filter(in_transit=True)
    elif branch_f.isdigit():
        qs = qs.filter(branch_id=int(branch_f))
    if item_f.isdigit():
        qs = qs.filter(item_id=int(item_f))
    if type_f in MOVEMENT_TYPES:
        qs = qs.filter(type=type_f)
    if not problem:
        start, end = _day_bounds(rng)
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)
    try:
        page_no = max(int(g.get('page', 1)), 1)
    except ValueError:
        page_no = 1
    paginator = Paginator(qs.order_by('-created_at', '-id'), PAGE_SIZE)
    page = paginator.get_page(page_no)
    refs = _movement_ref_numbers(page.object_list)
    movements = []
    for m in page.object_list:
        reason = REASON_LABELS.get(m.reason, m.reason)
        ref = refs.get((m.source_model, int(m.source_id))) if m.source_id.isdigit() else None
        detail = ' · '.join(x for x in [ref, ': '.join(x for x in [reason, m.note] if x)] if x)
        movements.append({'m': m, 'detail': detail, 'ref': ref, 'text': ': '.join(x for x in [reason, m.note] if x)})
    ctx.update({'movements': movements, 'page': page.number, 'pages': paginator.num_pages, 'total': paginator.count,
                'items': Item.objects.order_by('name'), 'types': MOVEMENT_TYPES, 'problem': problem,
                'f': {'branch': branch_f, 'item': item_f, 'type': type_f, 'from': f, 'to': t},
                'filters_on': any([branch_f, item_f, type_f, f, t])})
    return render(request, 'inventory/stock.html', ctx)


@permission_required('stock.adjust')
def stock_correct(request):
    user = request.user
    branch = _resolve_branch(request, request.POST.get('branch') or request.GET.get('branch'))
    if not branch:
        messages.error(request, 'No main office exists. Run the seed command first')
        return redirect('inventory:stock')
    rows = _balance_rows(branch)
    allowed = Item.objects.filter(pk__in=[r['item'].pk for r in rows])
    qty_by_item = {r['item'].pk: r['quantity'] for r in rows}
    initial = {'item': request.GET.get('item') or None, 'direction': 'add', 'branch': branch.pk}
    form = inv_forms.CorrectionForm(request.POST or None, initial=initial, item_queryset=allowed)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        try:
            balance = adjustments.create_adjustment(request, branch=branch, item=cd['item'], direction=cd['direction'],
                                                    quantity=cd['quantity'], reason=cd['reason'], note=cd['note'])
            messages.success(request, f'Stock corrected. {cd["item"].name} now shows {balance} at {branch.name}.')
            return redirect(f"{reverse('inventory:stock')}?branch={branch.pk}")
        except ServiceError as exc:
            apply_service_error(form, exc)
    return render(request, 'inventory/stock_correct.html', {
        'form': form, 'branch': branch, 'rows': rows, 'qty_by_item': qty_by_item,
        'reasons_for_json': json.dumps(REASONS_FOR), 'reason_labels_json': json.dumps(REASON_LABELS)})
