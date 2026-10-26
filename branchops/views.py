from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Branch
from catalog.models import Item
from core.constants import BRANCH_TYPES, DISPATCH_STATUS, REQUEST_STATUS
from core.decorators import branch_module_required, permission_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.labels import DISPATCH_STATUS_LABELS, REQUEST_STATUS_LABELS
from core.lines import parse_lines, parse_pairs, whole_number
from core.permissions import has_any, is_branch_side
from branchops import forms as bforms
from branchops.models import Dispatch, Request
from branchops.services import dispatches, requests
from inventory.services.stock import get_balances, get_main_branch

BLANK_ROW = {'item_id': '', 'errors': {}, 'raw': {'item': '', 'quantity': '', 'unit_cost': ''}}
VIEW_REQUESTS = ('requests.create', 'requests.review', 'dispatches.manage')
VIEW_DISPATCHES = ('dispatches.manage', 'dispatches.receive')


def _left(line):
    return max((line.quantity_approved or 0) - (line.quantity_dispatched or 0), 0)


def _request_model(r):
    lines = list(r.lines.all())
    return {'r': r, 'lines': lines, 'total_requested': sum(l.quantity_requested for l in lines),
            'total_approved': sum(l.quantity_approved or 0 for l in lines),
            'total_dispatched': sum(l.quantity_dispatched or 0 for l in lines)}


def _dispatch_model(d):
    lines = list(d.lines.all())
    return {'d': d, 'lines': lines, 'total_sent': sum(l.quantity_sent for l in lines),
            'total_received': sum(l.quantity_received or 0 for l in lines),
            'differences': sum((l.quantity_damaged or 0) + (l.quantity_short or 0) for l in lines)}


def _dispatchable(r_lines, status):
    return status in (REQUEST_STATUS.APPROVED, REQUEST_STATUS.PARTLY_APPROVED) and any(_left(l) > 0 for l in r_lines)


# ================================================================== requests
@permission_required(*VIEW_REQUESTS)
@branch_module_required
def request_list(request):
    user = request.user
    search, status = request.GET.get('q', '').strip(), request.GET.get('status', '')
    qs = Request.objects.select_related('branch').prefetch_related('lines')
    if is_branch_side(user):
        qs = qs.filter(branch_id=user.branch_id)
    if status in REQUEST_STATUS_LABELS:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(number__icontains=search)
    rows = [_request_model(r) for r in qs.order_by('-created_at')]
    return render(request, 'branchops/request_list.html', {
        'rows': rows, 'statuses': REQUEST_STATUS_LABELS, 'f': {'q': search, 'status': status},
        'filters_on': bool(search or status), 'show_branch': not is_branch_side(user),
        'can_raise': has_any(user, ['requests.create'])})


@permission_required('requests.create')
@branch_module_required
def request_create(request):
    user = request.user
    if not user.branch_id or user.branch.type == BRANCH_TYPES.MAIN:
        messages.error(request, 'Requests are raised by branches. The main office does not request items from itself')
        return redirect('branchops:request_list')
    form = bforms.RequestForm(request.POST or None)
    line_error = None
    if request.method == 'POST':
        rows, lines_ok = parse_lines(request.POST, kind='simple')
        if form.is_valid() and lines_ok:
            try:
                req = requests.create_request(request, form.cleaned_data['notes'],
                                              [{'item': r['item'], 'quantity': r['quantity']} for r in rows])
                messages.success(request, 'Request sent to the main office')
                return redirect('branchops:request_detail', pk=req.pk)
            except ServiceError as exc:
                line_error = exc.message
        elif not rows:
            line_error = 'Add at least one item'
        else:
            messages.error(request, 'Please check the highlighted fields.')
    else:
        rows = [BLANK_ROW]
    return render(request, 'branchops/request_form.html', {
        'form': form, 'rows': rows, 'line_error': line_error, 'blank_row': BLANK_ROW,
        'items': Item.objects.filter(active=True).order_by('name')})


@permission_required(*VIEW_REQUESTS)
@branch_module_required
def request_detail(request, pk):
    user = request.user
    req = requests.get_request(user, pk)
    model = _request_model(req)
    own = bool(user.branch_id) and user.branch_id == req.branch_id
    can_review = req.status == REQUEST_STATUS.SUBMITTED and has_any(user, ['requests.review'])
    return render(request, 'branchops/request_detail.html', {
        **model, 'can_cancel': req.status == REQUEST_STATUS.SUBMITTED and own and has_any(user, ['requests.create']),
        'can_review': can_review,
        'can_dispatch': _dispatchable(model['lines'], req.status) and has_any(user, ['dispatches.manage']),
        'show_branch': not is_branch_side(user)})


@permission_required('requests.create')
@branch_module_required
@require_POST
def request_cancel(request, pk):
    try:
        requests.cancel_request(request, pk)
        messages.success(request, 'Request cancelled')
    except ServiceError as exc:
        if exc.status == 404:
            raise
        messages.error(request, exc.message)
    return redirect('branchops:request_detail', pk=pk)


@permission_required('requests.review')
@branch_module_required
def request_review(request, pk):
    req = requests.get_request(request.user, pk)
    lines = list(req.lines.select_related('item'))
    if req.status != REQUEST_STATUS.SUBMITTED:
        messages.error(request, 'This request has already been reviewed')
        return redirect('branchops:request_detail', pk=pk)
    main = get_main_branch()
    stock = get_balances(main.pk, [l.item_id for l in lines]) if main else {}
    values = {l.pk: {'quantity': str(l.quantity_requested), 'reason': ''} for l in lines}
    errors = {}
    if request.method == 'POST':
        pairs = parse_pairs(request.POST, ['approve', 'reason'])
        decisions = []
        for l in lines:
            p = pairs.get(l.pk, {})
            values[l.pk] = {'quantity': p.get('approve', ''), 'reason': p.get('reason', '').strip()}
            n, err = whole_number(p.get('approve', ''), 0)
            if err:
                errors[l.pk] = err
            else:
                if n > l.quantity_requested:
                    errors[l.pk] = f'Cannot approve more than the {l.quantity_requested} requested'
                elif n < l.quantity_requested and not values[l.pk]['reason']:
                    errors[l.pk] = 'Give a reason'
                decisions.append({'line_id': l.pk, 'quantity_approved': n, 'reason': values[l.pk]['reason'][:200]})
        if not errors:
            try:
                reviewed = requests.review_request(request, pk, decisions)
                messages.success(request, 'Request rejected' if reviewed.status == REQUEST_STATUS.REJECTED
                                 else 'Review saved. The main office can now send the items.')
                return redirect('branchops:request_detail', pk=pk)
            except ServiceError as exc:
                if exc.status == 404:
                    raise
                messages.error(request, exc.message)
        else:
            messages.error(request, 'Please check the highlighted fields.')
    rows = [{'l': l, 'stock': stock.get(l.item_id, 0), 'value': values[l.pk], 'error': errors.get(l.pk)} for l in lines]
    return render(request, 'branchops/request_review.html', {'r': req, 'rows': rows})


# ================================================================== dispatches
@permission_required(*VIEW_DISPATCHES)
@branch_module_required
def dispatch_list(request):
    user = request.user
    search, status = request.GET.get('q', '').strip(), request.GET.get('status', '')
    qs = Dispatch.objects.select_related('destination', 'request').prefetch_related('lines')
    if is_branch_side(user):
        qs = qs.filter(destination_id=user.branch_id)
    if status == 'open':
        qs = qs.filter(status__in=[DISPATCH_STATUS.IN_TRANSIT, DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES])
    elif status in DISPATCH_STATUS_LABELS:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(reference__icontains=search)
    rows = [_dispatch_model(d) for d in qs.order_by('-dispatch_date', '-created_at')]
    return render(request, 'branchops/dispatch_list.html', {
        'rows': rows, 'statuses': DISPATCH_STATUS_LABELS, 'f': {'q': search, 'status': status},
        'filters_on': bool(search or status), 'show_branch': not is_branch_side(user),
        'can_send': has_any(user, ['dispatches.manage'])})


@permission_required(*VIEW_DISPATCHES)
@branch_module_required
def dispatch_detail(request, pk):
    user = request.user
    d = dispatches.get_dispatch(user, pk)
    model = _dispatch_model(d)
    is_dest = bool(user.branch_id) and user.branch_id == d.destination_id
    return render(request, 'branchops/dispatch_detail.html', {
        **model, 'can_confirm': is_dest and d.status == DISPATCH_STATUS.IN_TRANSIT and has_any(user, ['dispatches.receive']),
        'can_close': d.status == DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES and has_any(user, ['dispatches.manage']),
        'show_result': d.status != DISPATCH_STATUS.IN_TRANSIT, 'show_branch': not is_branch_side(user)})


@permission_required('dispatches.manage')
@branch_module_required
def dispatch_create(request):
    user = request.user
    main = get_main_branch()
    request_id = request.POST.get('request') or request.GET.get('request') or ''
    req = None
    if request_id.isdigit():
        req = Request.objects.select_related('branch').filter(pk=int(request_id)).first()
    open_requests = list(Request.objects.select_related('branch').prefetch_related('lines')
                         .filter(status__in=[REQUEST_STATUS.APPROVED, REQUEST_STATUS.PARTLY_APPROVED]).order_by('-created_at'))
    open_requests = [r for r in open_requests if any(_left(l) > 0 for l in r.lines.all())]
    if req and req.pk not in {r.pk for r in open_requests} and request.method == 'GET':
        messages.error(request, 'Nothing is left to send on that request')
        req = None
    items = list(Item.objects.filter(active=True).order_by('name'))
    balances = get_balances(main.pk, [i.pk for i in items]) if main else {}
    for i in items:
        i.stock = balances.get(i.pk, 0)
    form = bforms.DirectDispatchForm(request.POST or None, initial={'dispatch_date': timezone.localdate()})
    if req:
        del form.fields['destination']
    line_error = None
    rows = [BLANK_ROW]
    req_rows = []
    if req:
        by_item = {i.pk: i for i in items}
        for l in req.lines.select_related('item'):
            if _left(l) > 0:
                stock = by_item[l.item_id].stock if l.item_id in by_item else get_balances(main.pk, [l.item_id]).get(l.item_id, 0)
                req_rows.append({'l': l, 'left': _left(l), 'stock': stock, 'value': str(_left(l)), 'error': None})

    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        lines = []
        ok = True
        if req:
            for r in req_rows:
                raw = request.POST.get(f'qty_{r["l"].item_id}', '')
                r['value'] = raw
                n, err = whole_number(raw, 0)
                if err:
                    r['error'] = err
                    ok = False
                elif n > 0:
                    lines.append({'item': r['l'].item, 'quantity': n})
        else:
            rows, ok = parse_lines(request.POST, kind='simple')
            lines = [{'item': r['item'], 'quantity': r['quantity']} for r in rows]
            if not rows:
                line_error = 'Add at least one item'
        if ok:
            try:
                dsp = dispatches.create_dispatch(
                    request, request_obj_id=req.pk if req else None,
                    destination_id=None if req else cd['destination'].pk,
                    dispatch_date=cd.get('dispatch_date') or timezone.localdate(), lines=lines)
                messages.success(request, f'{dsp.reference} is on its way to {dsp.destination.name}.')
                return redirect('branchops:dispatch_detail', pk=dsp.pk)
            except ServiceError as exc:
                line_error = exc.message
        else:
            messages.error(request, 'Please check the highlighted fields.')
    elif request.method == 'POST':
        if not req:
            rows, _ = parse_lines(request.POST, kind='simple')
            rows = rows or [BLANK_ROW]
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'branchops/dispatch_form.html', {
        'form': form, 'req': req, 'open_requests': open_requests, 'req_rows': req_rows, 'rows': rows,
        'items': items, 'line_error': line_error, 'blank_row': BLANK_ROW, 'show_stock': True,
        'today': timezone.localdate().isoformat()})


@permission_required('dispatches.receive')
@branch_module_required
def dispatch_receive(request, pk):
    user = request.user
    d = dispatches.get_dispatch(user, pk)
    if d.destination_id != user.branch_id:
        messages.error(request, 'Only the receiving branch can confirm this delivery')
        return redirect('branchops:dispatch_detail', pk=pk)
    if d.status != DISPATCH_STATUS.IN_TRANSIT:
        messages.error(request, 'This dispatch has already been received')
        return redirect('branchops:dispatch_detail', pk=pk)
    lines = list(d.lines.select_related('item'))
    values = {l.pk: {'received': str(l.quantity_sent), 'damaged': '0'} for l in lines}
    errors = {}
    if request.method == 'POST':
        pairs = parse_pairs(request.POST, ['received', 'damaged'])
        received = []
        for l in lines:
            p = pairs.get(l.pk, {})
            values[l.pk] = {'received': p.get('received', ''), 'damaged': p.get('damaged', '')}
            r, e1 = whole_number(p.get('received', ''), 0)
            dm, e2 = whole_number(p.get('damaged', '') or '0', 0)
            if e1 or e2:
                errors[l.pk] = e1 or e2
            elif r + dm > l.quantity_sent:
                errors[l.pk] = f'Received plus damaged is more than the {l.quantity_sent} sent'
            else:
                received.append({'item': l.item_id, 'received': r, 'damaged': dm})
        if not errors:
            try:
                dispatches.receive_dispatch(request, pk, received)
                messages.success(request, 'Receipt confirmed. The items are now in your branch stock.')
                return redirect('branchops:dispatch_detail', pk=pk)
            except ServiceError as exc:
                if exc.status == 404:
                    raise
                messages.error(request, exc.message)
        else:
            messages.error(request, 'Please check the highlighted fields.')
    rows = [{'l': l, 'value': values[l.pk], 'error': errors.get(l.pk)} for l in lines]
    return render(request, 'branchops/dispatch_receive.html', {'d': d, 'rows': rows})


@permission_required('dispatches.manage')
@branch_module_required
def dispatch_close(request, pk):
    d = dispatches.get_dispatch(request.user, pk)
    if d.status != DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES:
        messages.error(request, 'Only a dispatch received with differences can be closed')
        return redirect('branchops:dispatch_detail', pk=pk)
    lines = list(d.lines.select_related('item'))
    form = bforms.CloseDispatchForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            dispatches.close_dispatch(request, pk, form.cleaned_data['resolution'], form.cleaned_data['note'])
            messages.success(request, 'Dispatch closed')
            return redirect('branchops:dispatch_detail', pk=pk)
        except ServiceError as exc:
            if exc.status == 404:
                raise
            apply_service_error(form, exc)
    differences = sum((l.quantity_damaged or 0) + (l.quantity_short or 0) for l in lines)
    return render(request, 'branchops/dispatch_close.html', {'d': d, 'lines': lines, 'form': form, 'differences': differences})
