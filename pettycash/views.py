from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Branch
from core.constants import PETTY_CASH_ENTRY, PETTY_CASH_STATUS
from core.decorators import permission_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.labels import PETTY_CASH_ENTRY_LABELS, PETTY_CASH_STATUS_LABELS
from core.permissions import has_any, is_branch_side
from core.rules.petty_cash_rules import is_low
from pettycash import forms as pforms
from pettycash import services
from pettycash.models import PettyCashEntry, PettyCashRequest

PAGE_SIZE = 50
VIEW_ANY = ('petty_cash.view', 'petty_cash.request', 'petty_cash.approve', 'petty_cash.configure')


def _entry_rows(entries, user):
    """Entries with what the user may do to each one."""
    entries = list(entries)
    reversed_ids = set(PettyCashEntry.objects.filter(reversal_of__in=[e.pk for e in entries]).values_list('reversal_of_id', flat=True))
    can_approve = has_any(user, ['petty_cash.approve'])
    can_request = has_any(user, ['petty_cash.request'])
    rows = []
    for e in entries:
        mine = e.branch_id == user.branch_id
        spent = e.type == PETTY_CASH_ENTRY.EXPENSE
        rows.append({'e': e, 'cancelled': e.pk in reversed_ids,
                     'can_cancel': spent and e.pk not in reversed_ids and ((mine and can_request) or (can_approve and not is_branch_side(user)))})
    return rows


# ================================================================== overview
@permission_required(*VIEW_ANY)
def overview(request):
    user = request.user
    summaries = services.branch_summaries(user)
    own = next((s for s in summaries if s['branch'].pk == user.branch_id), None)
    all_branches = services.scope_branch_id(user) is None
    pending_qs = PettyCashRequest.objects.select_related('branch', 'requested_by').filter(status=PETTY_CASH_STATUS.SUBMITTED)
    if not all_branches:
        pending_qs = pending_qs.filter(branch_id=user.branch_id)
    recent_qs = PettyCashEntry.objects.select_related('branch', 'created_by')
    if not all_branches:
        recent_qs = recent_qs.filter(branch_id=user.branch_id)
    return render(request, 'pettycash/overview.html', {
        'summaries': summaries, 'own': own, 'all_branches': all_branches,
        'low_level': services.get_low_level(), 'low_count': sum(1 for s in summaries if s['low']),
        'pending': list(pending_qs.order_by('created_at')[:10]),
        'can_request': has_any(user, ['petty_cash.request']) and bool(user.branch_id),
        'can_approve': has_any(user, ['petty_cash.approve']) and not is_branch_side(user),
        'can_configure': has_any(user, ['petty_cash.configure']) and not is_branch_side(user),
        'recent': _entry_rows(recent_qs.order_by('-entry_date', '-created_at', '-id')[:8], user)})


# ================================================================== requests
@permission_required(*VIEW_ANY)
def request_list(request):
    user = request.user
    search, status = request.GET.get('q', '').strip(), request.GET.get('status', '')
    qs = PettyCashRequest.objects.select_related('branch', 'requested_by')
    scope = services.scope_branch_id(user)
    if scope is not None:
        qs = qs.filter(branch_id=scope)
    if status in PETTY_CASH_STATUS_LABELS:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(number__icontains=search)
    return render(request, 'pettycash/request_list.html', {
        'rows': list(qs.order_by('-created_at')), 'statuses': PETTY_CASH_STATUS_LABELS, 'f': {'q': search, 'status': status},
        'filters_on': bool(search or status), 'show_branch': scope is None,
        'can_raise': has_any(user, ['petty_cash.request']) and bool(user.branch_id)})


@permission_required('petty_cash.request')
def request_create(request):
    user = request.user
    if not user.branch_id:
        messages.error(request, 'Your account is not assigned to a branch')
        return redirect('pettycash:overview')
    form = pforms.RequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            req = services.create_request(request, form.cleaned_data['amount'], form.cleaned_data['purpose'])
            messages.success(request, 'Petty cash request sent for approval')
            return redirect('pettycash:request_detail', pk=req.pk)
        except ServiceError as exc:
            apply_service_error(form, exc)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'pettycash/request_form.html', {
        'form': form, 'balance': services.get_balance(user.branch_id), 'low_level': services.get_low_level()})


@permission_required(*VIEW_ANY)
def request_detail(request, pk):
    user = request.user
    req = services.get_request(user, pk)
    own = bool(user.branch_id) and user.branch_id == req.branch_id
    waiting = req.status == PETTY_CASH_STATUS.SUBMITTED
    return render(request, 'pettycash/request_detail.html', {
        'r': req, 'show_branch': services.scope_branch_id(user) is None,
        'can_cancel': waiting and own and has_any(user, ['petty_cash.request']),
        'can_review': waiting and has_any(user, ['petty_cash.approve']) and not is_branch_side(user)})


@permission_required('petty_cash.request')
@require_POST
def request_cancel(request, pk):
    try:
        services.cancel_request(request, pk)
        messages.success(request, 'Request cancelled')
    except ServiceError as exc:
        if exc.status == 404:
            raise
        messages.error(request, exc.message)
    return redirect('pettycash:request_detail', pk=pk)


@permission_required('petty_cash.approve')
def request_review(request, pk):
    user = request.user
    if is_branch_side(user):
        messages.error(request, 'Only main-office managers can approve petty cash')
        return redirect('pettycash:request_detail', pk=pk)
    req = services.get_request(user, pk)
    if req.status != PETTY_CASH_STATUS.SUBMITTED:
        messages.error(request, 'This request has already been reviewed')
        return redirect('pettycash:request_detail', pk=pk)
    form = pforms.ReviewForm(request.POST or None, initial={'decision': 'approve', 'amount': req.amount_requested})
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        approve = cd['decision'] == 'approve'
        try:
            done = services.review_request(request, pk, approve=approve, amount=cd.get('amount'), note=cd['note'])
            messages.success(request, f'Request rejected' if done.status == PETTY_CASH_STATUS.REJECTED
                             else f'Approved. Give {done.branch.name} Rs. {done.amount_approved:,.2f}; it is now in their petty cash balance.')
            return redirect('pettycash:request_detail', pk=pk)
        except ServiceError as exc:
            if exc.status == 404:
                raise
            apply_service_error(form, exc)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'pettycash/request_review.html', {
        'r': req, 'form': form, 'balance': services.get_balance(req.branch_id), 'low_level': services.get_low_level(),
        'own_request': req.requested_by_id == user.pk and user.role != 'super_admin'})


# ================================================================== spending and the cash book
@permission_required(*VIEW_ANY)
def ledger(request):
    user = request.user
    scope = services.scope_branch_id(user)
    g = request.GET
    branch_id, kind = g.get('branch', ''), g.get('type', '')
    qs = PettyCashEntry.objects.select_related('branch', 'created_by', 'request')
    if scope is not None:
        qs = qs.filter(branch_id=scope)
    elif branch_id.isdigit():
        qs = qs.filter(branch_id=int(branch_id))
    if kind in PETTY_CASH_ENTRY_LABELS:
        qs = qs.filter(type=kind)
    try:
        page_no = max(int(g.get('page', 1)), 1)
    except ValueError:
        page_no = 1
    paginator = Paginator(qs.order_by('-entry_date', '-created_at', '-id'), PAGE_SIZE)
    page = paginator.get_page(page_no)
    shown_branch = scope if scope is not None else (int(branch_id) if branch_id.isdigit() else None)
    balance = services.get_balance(shown_branch) if shown_branch else None
    return render(request, 'pettycash/ledger.html', {
        'rows': _entry_rows(page.object_list, user), 'page': page.number, 'pages': paginator.num_pages, 'total': paginator.count,
        'branches': Branch.objects.order_by('type', 'name') if scope is None else [], 'types': PETTY_CASH_ENTRY_LABELS,
        'f': {'branch': branch_id, 'type': kind}, 'filters_on': bool(kind or (scope is None and branch_id)),
        'show_branch': scope is None, 'balance': balance, 'low': balance is not None and is_low(balance, services.get_low_level()),
        'can_spend': has_any(user, ['petty_cash.request']) and bool(user.branch_id)})


@permission_required('petty_cash.request')
def expense_create(request):
    user = request.user
    if not user.branch_id:
        messages.error(request, 'Your account is not assigned to a branch')
        return redirect('pettycash:overview')
    form = pforms.ExpenseForm(request.POST or None, initial={'entry_date': timezone.localdate()})
    balance = services.get_balance(user.branch_id)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        try:
            services.record_expense(request, cd['amount'], cd['description'], cd.get('entry_date') or timezone.localdate())
            left = services.get_balance(user.branch_id)
            messages.success(request, f'Spending recorded. Petty cash left: Rs. {left:,.2f}'
                             + (' (low, please request more)' if is_low(left, services.get_low_level()) else ''))
            return redirect('pettycash:ledger')
        except ServiceError as exc:
            apply_service_error(form, exc)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'pettycash/expense_form.html', {'form': form, 'balance': balance, 'low_level': services.get_low_level(),
                                                          'today': timezone.localdate().isoformat()})


@permission_required(*VIEW_ANY)
@require_POST
def expense_cancel(request, pk):
    try:
        services.cancel_expense(request, pk)
        messages.success(request, 'Expense cancelled. The money is back in petty cash')
    except ServiceError as exc:
        if exc.status == 404:
            raise
        messages.error(request, exc.message)
    return redirect('pettycash:ledger')


# ================================================================== settings
@permission_required('petty_cash.configure')
def settings_view(request):
    if is_branch_side(request.user):
        messages.error(request, 'Only top management can change the low level')
        return redirect('pettycash:overview')
    form = pforms.LowLevelForm(request.POST or None, initial={'level': services.get_low_level()})
    if request.method == 'POST' and form.is_valid():
        try:
            services.set_low_level(request, form.cleaned_data['level'])
            messages.success(request, 'Low petty cash level saved')
            return redirect('pettycash:overview')
        except ServiceError as exc:
            apply_service_error(form, exc)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    summaries = services.branch_summaries(request.user)
    return render(request, 'pettycash/settings.html', {'form': form, 'low_level': services.get_low_level(),
                                                      'low_branches': [s for s in summaries if s['low']]})
