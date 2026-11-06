from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from core.constants import ROLES
from core.decorators import permission_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.models import Setting
from core.permissions import has_any, is_branch_side
from vouchers.forms import DeleteVoucherForm, ExpenseCategoryForm, RejectVoucherForm, VoucherForm, VoucherScheduleForm
from vouchers.models import ExpenseCategory, Voucher, VoucherSchedule
from vouchers import services


def _module_enabled():
    if not Setting.get().payment_voucher_module_enabled:
        raise PermissionDenied('The Payment Voucher module is switched off')


def _can_self_approve(user):
    return (Setting.get().payment_voucher_self_approval_enabled
            and has_any(user, ['vouchers.self_approve']))


def _voucher_status_message(voucher):
    return {
        Voucher.Status.DRAFT: 'saved as a draft',
        Voucher.Status.RECOMMENDING: 'submitted for recommendation',
        Voucher.Status.PENDING: 'submitted for approval',
        Voucher.Status.APPROVED: 'approved and ready to print',
    }.get(voucher.status, voucher.get_status_display().lower())


def _require_main_office(user):
    if is_branch_side(user):
        raise PermissionDenied('Only main-office users can configure voucher categories')


def _voucher_queryset(user):
    qs = Voucher.objects.select_related(
        'branch', 'category', 'prepared_by', 'recommender', 'recommended_by', 'approver', 'approved_by',
    )
    if is_branch_side(user):
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
    if is_branch_side(request.user):
        raise PermissionDenied('Only main-office managers can review payment vouchers')
    pending = Voucher.objects.filter(status=Voucher.Status.PENDING, approver=request.user)
    return render(request, 'vouchers/approval_queue.html', {
        'vouchers': pending.select_related('branch', 'category', 'prepared_by').order_by('date', 'created_at'),
        'queue_title': 'Voucher approvals',
        'queue_description': 'Payment vouchers assigned to you for final approval',
    })


@permission_required('vouchers.recommend')
def recommendation_queue(request):
    _module_enabled()
    if is_branch_side(request.user):
        raise PermissionDenied('Only main-office users can recommend payment vouchers')
    pending = Voucher.objects.filter(status=Voucher.Status.RECOMMENDING, recommender=request.user)
    return render(request, 'vouchers/approval_queue.html', {
        'vouchers': pending.select_related('branch', 'category', 'prepared_by').order_by('date', 'created_at'),
        'queue_title': 'Voucher recommendations',
        'queue_description': 'Payment vouchers assigned to you for recommendation',
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
                            and voucher.status == Voucher.Status.DRAFT
                            and not voucher.recommender_id,
        'can_recommend': has_any(request.user, ['vouchers.recommend'])
                         and not is_branch_side(request.user)
                         and voucher.recommender_id == request.user.pk
                         and voucher.status == Voucher.Status.RECOMMENDING,
        'can_approve': has_any(request.user, ['vouchers.approve'])
                       and not is_branch_side(request.user)
                       and voucher.approver_id == request.user.pk
                       and voucher.status == Voucher.Status.PENDING,
        'can_delete': request.user.role == ROLES.SUPER_ADMIN,
        'reject_form': RejectVoucherForm(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def voucher_delete(request, pk):
    if request.user.role != ROLES.SUPER_ADMIN:
        raise PermissionDenied('Only the Super Admin can permanently delete payment vouchers.')
    voucher = get_object_or_404(
        Voucher.objects.select_related('branch', 'category', 'prepared_by'),
        pk=pk,
    )
    form = DeleteVoucherForm(request.POST or None, voucher_number=voucher.number)
    if request.method == 'POST' and form.is_valid():
        try:
            deleted = services.delete_voucher(request, voucher.pk, form.cleaned_data['voucher_id'])
        except ServiceError as exc:
            apply_service_error(form, exc)
        else:
            messages.success(request, f'Payment voucher {deleted["number"]} was permanently deleted.')
            return redirect('vouchers:voucher_list')
    return render(request, 'vouchers/voucher_delete.html', {
        'voucher': voucher,
        'form': form,
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
        elif action == 'self_approve' and form.cleaned_data.get('recommender'):
            form.add_error('recommender', 'A voucher assigned to a recommender must be submitted for recommendation.')
        else:
            try:
                voucher = services.create_voucher(request, form, action)
            except ServiceError as exc:
                apply_service_error(form, exc)
            else:
                messages.success(request, f'Payment voucher {voucher.number} {_voucher_status_message(voucher)}')
                return redirect('vouchers:voucher_detail', pk=voucher.pk)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'vouchers/voucher_form.html', {
        'form': form, 'title': 'Create payment voucher',
        'can_self_approve': _can_self_approve(request.user) and not form.data.get('recommender'),
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
        elif action == 'self_approve' and form.cleaned_data.get('recommender'):
            form.add_error('recommender', 'A voucher assigned to a recommender must be submitted for recommendation.')
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
                messages.success(request, f'Payment voucher {voucher.number} {_voucher_status_message(voucher)}')
                return redirect('vouchers:voucher_detail', pk=voucher.pk)
    elif request.method == 'POST':
        messages.error(request, 'Please check the highlighted fields.')
    return render(request, 'vouchers/voucher_form.html', {
        'form': form, 'title': f'Edit {voucher.number}', 'voucher': voucher,
        'can_self_approve': _can_self_approve(request.user) and not form.data.get('recommender'),
    })


@permission_required('vouchers.view')
@require_POST
def voucher_action(request, pk, action):
    _module_enabled()
    if action not in ('submit', 'self_approve', 'recommend', 'approve', 'reject'):
        raise PermissionDenied('Unknown voucher action')
    if action == 'submit' and not has_any(request.user, ['vouchers.create']):
        raise PermissionDenied('You do not have permission to submit payment vouchers')
    if action == 'self_approve' and not _can_self_approve(request.user):
        raise PermissionDenied('Self-approval is disabled or not permitted for your account')
    if action == 'recommend' and (
            not has_any(request.user, ['vouchers.recommend'])
            or is_branch_side(request.user)):
        raise PermissionDenied('Only an authorized main-office recommender can review payment vouchers')
    if action == 'approve' and (
            not has_any(request.user, ['vouchers.approve'])
            or is_branch_side(request.user)):
        raise PermissionDenied('Only an authorized main-office manager can review payment vouchers')
    if action == 'reject' and not has_any(request.user, ['vouchers.recommend', 'vouchers.approve']):
        raise PermissionDenied('You do not have permission to reject payment vouchers')
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
        elif action == 'recommend':
            voucher = services.recommend_voucher(request, pk)
        elif action == 'approve':
            voucher = services.approve_voucher(request, pk)
        else:
            current = services.get_voucher(request.user, pk)
            reject_service = (services.reject_recommendation_voucher
                              if current.status == Voucher.Status.RECOMMENDING
                              else services.reject_voucher)
            voucher = reject_service(request, pk, form.cleaned_data['reason'])
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
    schedules = VoucherSchedule.objects.select_related(
        'branch', 'category', 'created_by', 'recommender', 'approver',
    )
    if is_branch_side(request.user):
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
