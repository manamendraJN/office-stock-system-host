from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import permission_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.models import Setting
from core.permissions import has_any, is_branch_side
from vouchers.forms import ExpenseCategoryForm, RejectVoucherForm, VoucherForm, VoucherScheduleForm
from vouchers.models import ExpenseCategory, Voucher, VoucherSchedule
from vouchers import services


def _module_enabled():
    if not Setting.get().payment_voucher_module_enabled:
        raise PermissionDenied('The Payment Voucher module is switched off')


def _can_self_approve(user):
    return (Setting.get().payment_voucher_self_approval_enabled
            and has_any(user, ['vouchers.self_approve']))


def _require_main_office(user):
    if is_branch_side(user):
        raise PermissionDenied('Only main-office users can configure voucher categories')


def _voucher_queryset(user):
    qs = Voucher.objects.select_related('branch', 'category', 'prepared_by', 'approver', 'approved_by')
    if user.role != 'super_admin' and user.role_def and user.role_def.get('side') == 'branch':
        qs = qs.filter(branch_id=user.branch_id)
    return qs


@permission_required('vouchers.view')
def voucher_list(request):
    _module_enabled()
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    qs = _voucher_queryset(request.user)
    if query:
        qs = qs.filter(Q(number__icontains=query) | Q(payee__icontains=query) | Q(to__icontains=query)
                       | Q(being__icontains=query) | Q(cheque_number__icontains=query))
    if status in Voucher.Status.values:
        qs = qs.filter(status=status)
    return render(request, 'vouchers/voucher_list.html', {
        'vouchers': qs.order_by('-date', '-created_at')[:250], 'q': query, 'status': status,
        'statuses': Voucher.Status.choices, 'can_create': has_any(request.user, ['vouchers.create']),
        'can_schedule': has_any(request.user, ['vouchers.schedule']),
        'can_configure': has_any(request.user, ['vouchers.configure']),
    })


@permission_required('vouchers.approve')
def approval_queue(request):
    _module_enabled()
    if request.user.role_def and request.user.role_def.get('side') == 'branch':
        raise PermissionDenied('Only main-office managers can review payment vouchers')
    pending = Voucher.objects.filter(status=Voucher.Status.PENDING, approver=request.user)
    return render(request, 'vouchers/approval_queue.html', {
        'vouchers': pending.select_related('branch', 'category', 'prepared_by').order_by('date', 'created_at'),
    })


@permission_required('vouchers.view')
def voucher_detail(request, pk):
    _module_enabled()
    voucher = services.get_voucher(request.user, pk)
    return render(request, 'vouchers/voucher_detail.html', {
        'voucher': voucher, 'events': voucher.events.select_related('actor'),
        'can_edit': has_any(request.user, ['vouchers.create'])
                    and voucher.prepared_by_id == request.user.pk
                    and voucher.status in (Voucher.Status.DRAFT, Voucher.Status.REJECTED),
        'can_print': has_any(request.user, ['vouchers.print']) and voucher.is_printable,
        'can_submit': has_any(request.user, ['vouchers.create'])
                      and voucher.prepared_by_id == request.user.pk and voucher.status == Voucher.Status.DRAFT,
        'can_self_approve': _can_self_approve(request.user)
                            and voucher.prepared_by_id == request.user.pk
                            and voucher.status == Voucher.Status.DRAFT,
        'can_approve': has_any(request.user, ['vouchers.approve'])
                       and voucher.approver_id == request.user.pk
                       and voucher.status == Voucher.Status.PENDING,
        'reject_form': RejectVoucherForm(),
    })


@permission_required('vouchers.create')
def voucher_create(request):
    _module_enabled()
    form = VoucherForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        action = request.POST.get('action', 'draft')
        if action == 'self_approve' and not _can_self_approve(request.user):
            raise PermissionDenied('Self-approval is disabled or not permitted for your account')
        if action == 'submit' and not form.cleaned_data.get('approver'):
            form.add_error('approver', 'Choose an authorized manager before submitting.')
        else:
            try:
                voucher = services.create_voucher(request, form, action)
            except ServiceError as exc:
                apply_service_error(form, exc)
            else:
                messages.success(request, f'Payment voucher {voucher.number} '
                                 f'{ "submitted for approval" if voucher.status == Voucher.Status.PENDING else "saved" }')
                return redirect('vouchers:voucher_detail', pk=voucher.pk)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'vouchers/voucher_form.html', {
        'form': form, 'title': 'Create payment voucher', 'can_self_approve': _can_self_approve(request.user),
    })


@permission_required('vouchers.create')
def voucher_update(request, pk):
    _module_enabled()
    voucher = services.get_voucher(request.user, pk)
    if voucher.prepared_by_id != request.user.pk or voucher.status not in (
            Voucher.Status.DRAFT, Voucher.Status.REJECTED):
        raise PermissionDenied('Only your draft or rejected vouchers can be edited')
    form = VoucherForm(request.POST or None, user=request.user, instance=voucher)
    if request.method == 'POST' and form.is_valid():
        action = request.POST.get('action', 'draft')
        if action not in ('draft', 'submit', 'self_approve'):
            raise PermissionDenied('Unknown voucher action')
        if action == 'self_approve' and not _can_self_approve(request.user):
            raise PermissionDenied('Self-approval is disabled or not permitted for your account')
        if action == 'submit' and not form.cleaned_data.get('approver'):
            form.add_error('approver', 'Choose an authorized manager before submitting.')
        else:
            try:
                voucher = services.update_voucher(request, pk, form)
                if action == 'submit':
                    voucher = services.submit_voucher(request, voucher.pk)
                elif action == 'self_approve':
                    voucher = services.self_approve_voucher(request, voucher.pk)
            except ServiceError as exc:
                apply_service_error(form, exc)
            else:
                messages.success(request, f'Payment voucher {voucher.number} updated')
                return redirect('vouchers:voucher_detail', pk=voucher.pk)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'vouchers/voucher_form.html', {
        'form': form, 'title': f'Edit {voucher.number}', 'voucher': voucher,
        'can_self_approve': _can_self_approve(request.user),
    })


@permission_required('vouchers.view')
@require_POST
def voucher_action(request, pk, action):
    _module_enabled()
    if action not in ('submit', 'self_approve', 'approve', 'reject'):
        raise PermissionDenied('Unknown voucher action')
    if action == 'submit' and not has_any(request.user, ['vouchers.create']):
        raise PermissionDenied('You do not have permission to submit payment vouchers')
    if action == 'self_approve' and not _can_self_approve(request.user):
        raise PermissionDenied('Self-approval is disabled or not permitted for your account')
    if action in ('approve', 'reject') and (
            not has_any(request.user, ['vouchers.approve'])
            or (request.user.role_def and request.user.role_def.get('side') == 'branch')):
        raise PermissionDenied('Only an authorized main-office manager can review payment vouchers')
    if action == 'reject':
        form = RejectVoucherForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Enter a reason before rejecting a voucher.')
            return redirect('vouchers:voucher_detail', pk=pk)
    try:
        if action == 'submit':
            voucher = services.submit_voucher(request, pk)
        elif action == 'self_approve':
            voucher = services.self_approve_voucher(request, pk)
        elif action == 'approve':
            voucher = services.approve_voucher(request, pk)
        else:
            voucher = services.reject_voucher(request, pk, form.cleaned_data['reason'])
    except ServiceError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f'Payment voucher {voucher.number} {voucher.get_status_display().lower()}')
    return redirect('vouchers:voucher_detail', pk=pk)


@permission_required('vouchers.print')
def voucher_print(request, pk):
    _module_enabled()
    voucher = services.get_voucher(request.user, pk)
    if not voucher.is_printable:
        raise PermissionDenied('A payment voucher can only be printed after approval')
    return render(request, 'vouchers/voucher_print.html', {'voucher': voucher, 'printed_at': timezone.localdate()})


@permission_required('vouchers.schedule')
def schedule_list(request):
    _module_enabled()
    schedules = VoucherSchedule.objects.select_related('branch', 'category', 'created_by', 'approver')
    if request.user.role != 'super_admin' and request.user.role_def and request.user.role_def.get('side') == 'branch':
        schedules = schedules.filter(branch_id=request.user.branch_id)
    if not has_any(request.user, ['vouchers.approve']):
        schedules = schedules.filter(created_by=request.user)
    return render(request, 'vouchers/schedule_list.html', {'schedules': schedules})


@permission_required('vouchers.schedule')
def schedule_create(request):
    _module_enabled()
    form = VoucherScheduleForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            schedule = services.create_schedule(request, form)
        except ServiceError as exc:
            apply_service_error(form, exc)
        else:
            messages.success(request, f'Schedule "{schedule.title}" created')
            return redirect('vouchers:schedule_list')
    return render(request, 'vouchers/schedule_form.html', {'form': form, 'title': 'Schedule payment vouchers'})


@permission_required('vouchers.schedule')
def schedule_update(request, pk):
    _module_enabled()
    schedule = services.get_schedule(request.user, pk)
    if schedule.created_by_id != request.user.pk and (
            is_branch_side(request.user) or not has_any(request.user, ['vouchers.approve'])):
        raise PermissionDenied
    form = VoucherScheduleForm(request.POST or None, user=request.user, instance=schedule)
    if request.method == 'POST' and form.is_valid():
        try:
            schedule = services.update_schedule(request, pk, form)
        except ServiceError as exc:
            apply_service_error(form, exc)
        else:
            messages.success(request, f'Schedule "{schedule.title}" updated')
            return redirect('vouchers:schedule_list')
    return render(request, 'vouchers/schedule_form.html', {'form': form, 'title': f'Edit {schedule.title}'})


@permission_required('vouchers.configure')
def category_list(request):
    _module_enabled()
    _require_main_office(request.user)
    return render(request, 'vouchers/category_list.html', {
        'categories': ExpenseCategory.objects.all(),
    })


@permission_required('vouchers.configure')
def category_create(request):
    _module_enabled()
    _require_main_office(request.user)
    form = ExpenseCategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        from core.services.audit import log_audit
        log_audit(request, 'payment_voucher.category_create', 'ExpenseCategory', category.pk,
                  new_value={'name': category.name, 'monthly_budget_limit': str(category.monthly_budget_limit)})
        messages.success(request, f'Expense category "{category.name}" created')
        return redirect('vouchers:category_list')
    return render(request, 'vouchers/category_form.html', {'form': form, 'title': 'Add expense category'})


@permission_required('vouchers.configure')
def category_update(request, pk):
    _module_enabled()
    _require_main_office(request.user)
    category = get_object_or_404(ExpenseCategory, pk=pk)
    form = ExpenseCategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        old = {'name': category.name, 'monthly_budget_limit': str(category.monthly_budget_limit),
               'is_active': category.is_active}
        category = form.save()
        from core.services.audit import log_audit
        log_audit(request, 'payment_voucher.category_update', 'ExpenseCategory', category.pk,
                  old_value=old, new_value={'name': category.name,
                                            'monthly_budget_limit': str(category.monthly_budget_limit),
                                            'is_active': category.is_active})
        messages.success(request, f'Expense category "{category.name}" updated')
        return redirect('vouchers:category_list')
    return render(request, 'vouchers/category_form.html', {'form': form, 'title': f'Edit {category.name}'})
