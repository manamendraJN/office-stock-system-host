from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.errors import BadRequest, Conflict, Forbidden, NotFound
from core.models import Setting
from core.permissions import can_access_branch, has_any, is_branch_side
from core.services.audit import log_audit
from core.services.sequence import next_number
from vouchers.forms import eligible_approvers
from vouchers.models import ExpenseCategory, Voucher, VoucherEvent, VoucherSchedule


def _ensure_module():
    if not Setting.get().payment_voucher_module_enabled:
        raise Forbidden('The Payment Voucher module is switched off')


def get_voucher(user, pk, *, for_update=False):
    _ensure_module()
    if not has_any(user, ['vouchers.view']):
        raise Forbidden('You do not have permission to view payment vouchers')
    qs = Voucher.objects.select_related('branch', 'prepared_by', 'approver', 'approved_by', 'category')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    voucher = qs.filter(pk=pk).first()
    if voucher is None or not can_access_branch(user, voucher.branch_id):
        raise NotFound('Payment voucher not found')
    return voucher


def get_schedule(user, pk, *, for_update=False):
    _ensure_module()
    if not has_any(user, ['vouchers.schedule']):
        raise Forbidden('You do not have permission to view voucher schedules')
    qs = VoucherSchedule.objects.select_related('branch', 'created_by', 'approver', 'category')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    schedule = qs.filter(pk=pk).first()
    if schedule is None or not can_access_branch(user, schedule.branch_id):
        raise NotFound('Voucher schedule not found')
    if schedule.created_by_id != user.pk and not has_any(user, ['vouchers.approve']):
        raise NotFound('Voucher schedule not found')
    return schedule


def _event(voucher, actor, action, previous='', note=''):
    VoucherEvent.objects.create(
        voucher=voucher, actor=actor, action=action, previous_status=previous,
        new_status=voucher.status, note=(note or '')[:500],
    )


def _audit(request, action, voucher, *, old=None, new=None):
    log_audit(request, f'payment_voucher.{action}', 'PaymentVoucher', voucher.pk,
              old_value=old, new_value=new)


def _voucher_snapshot(voucher):
    return {
        'number': voucher.number,
        'amount': str(voucher.amount),
        'date': voucher.date.isoformat(),
        'payment_method': voucher.method_of_payment,
        'to': voucher.to,
        'account_details': voucher.account_details,
        'cheque_number': voucher.cheque_number,
        'receipt_attached': voucher.receipt_attached,
        'purpose': voucher.being,
        'payee': voucher.payee,
        'category_id': voucher.category_id,
        'branch_id': voucher.branch_id,
        'approver_id': voucher.approver_id,
    }


def _schedule_snapshot(schedule):
    return {
        'title': schedule.title,
        'category_id': schedule.category_id,
        'amount': str(schedule.amount),
        'frequency': schedule.frequency,
        'next_run': schedule.next_run.isoformat(),
        'method_of_payment': schedule.method_of_payment,
        'to': schedule.to,
        'account_details': schedule.account_details,
        'cheque_number': schedule.cheque_number,
        'purpose': schedule.being,
        'payee': schedule.payee,
        'branch_id': schedule.branch_id,
        'approver_id': schedule.approver_id,
        'is_active': schedule.is_active,
    }


def _valid_approver(user):
    return bool(user and user.active and not is_branch_side(user)
                and any(candidate.pk == user.pk for candidate in eligible_approvers(None)))


def _check_budget(voucher):
    category = ExpenseCategory.objects.select_for_update().get(pk=voucher.category_id)
    if category.monthly_budget_limit <= Decimal('0.00'):
        return
    month_start = date(voucher.date.year, voucher.date.month, 1)
    month_end = date(voucher.date.year + (voucher.date.month == 12),
                     1 if voucher.date.month == 12 else voucher.date.month + 1, 1)
    spent = (Voucher.objects.filter(category=category, status=Voucher.Status.APPROVED,
                                    date__gte=month_start, date__lt=month_end)
             .exclude(pk=voucher.pk).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'))
    if spent + voucher.amount > category.monthly_budget_limit:
        remaining = max(category.monthly_budget_limit - spent, Decimal('0.00'))
        raise Conflict(f'Submitting this voucher would exceed the monthly budget for {category.name}. '
                       f'Remaining budget: {remaining:.2f}.')


def create_voucher(request, form, action):
    _ensure_module()
    if not has_any(request.user, ['vouchers.create']):
        raise Forbidden('You do not have permission to create payment vouchers')
    if action not in ('draft', 'submit', 'self_approve'):
        raise BadRequest('Choose a valid voucher action')
    with transaction.atomic():
        voucher = form.save(commit=False)
        voucher.prepared_by = request.user
        voucher.number = next_number('PV', yearly=True)
        voucher.status = Voucher.Status.DRAFT
        voucher.save()
        _event(voucher, request.user, 'created')
        if action == 'submit':
            voucher = submit_voucher(request, voucher.pk)
        elif action == 'self_approve':
            voucher = self_approve_voucher(request, voucher.pk)
    _audit(request, 'create', voucher, new=_voucher_snapshot(voucher))
    return voucher


def update_voucher(request, voucher_id, form):
    _ensure_module()
    if not has_any(request.user, ['vouchers.create']):
        raise Forbidden('You do not have permission to edit payment vouchers')
    with transaction.atomic():
        voucher = get_voucher(request.user, voucher_id, for_update=True)
        if voucher.prepared_by_id != request.user.pk or voucher.status not in (
                Voucher.Status.DRAFT, Voucher.Status.REJECTED):
            raise Conflict('Only your draft or rejected vouchers can be edited.')
        previous = voucher.status
        old_snapshot = _voucher_snapshot(voucher)
        updated = form.save(commit=False)
        updated.pk = voucher.pk
        updated.number = voucher.number
        updated.prepared_by = voucher.prepared_by
        updated.status = Voucher.Status.DRAFT
        updated.approver = form.cleaned_data.get('approver')
        updated.approval_requested_at = None
        updated.approved_at = None
        updated.approved_by = None
        updated.rejected_at = None
        updated.rejection_reason = ''
        updated.schedule = voucher.schedule
        updated.scheduled_for = voucher.scheduled_for
        updated.save()
        _event(updated, request.user, 'edited', previous)
    _audit(request, 'update', updated, old=old_snapshot, new=_voucher_snapshot(updated))
    return updated


def submit_voucher(request, voucher_id):
    _ensure_module()
    if not has_any(request.user, ['vouchers.create']):
        raise Forbidden('You do not have permission to submit payment vouchers')
    with transaction.atomic():
        voucher = get_voucher(request.user, voucher_id, for_update=True)
        if voucher.prepared_by_id != request.user.pk or voucher.status != Voucher.Status.DRAFT:
            raise Conflict('Only the creator can submit a draft voucher.')
        if voucher.approver_id == request.user.pk:
            raise BadRequest('A voucher cannot be submitted to its creator for approval.')
        if not voucher.approver_id or not _valid_approver(voucher.approver):
            raise BadRequest('Choose an active manager with voucher approval permission.')
        previous = voucher.status
        voucher.status = Voucher.Status.PENDING
        voucher.approval_requested_at = timezone.now()
        voucher.save(update_fields=['status', 'approval_requested_at', 'updated_at'])
        _event(voucher, request.user, 'submitted', previous)
    _audit(request, 'submit', voucher, new={'status': voucher.status, 'approver': voucher.approver_id})
    return voucher


def self_approve_voucher(request, voucher_id):
    _ensure_module()
    if not Setting.get().payment_voucher_self_approval_enabled:
        raise Forbidden('Self-approval is disabled by the administrator')
    if not has_any(request.user, ['vouchers.self_approve']):
        raise Forbidden('You do not have permission to self-approve payment vouchers')
    with transaction.atomic():
        voucher = get_voucher(request.user, voucher_id, for_update=True)
        if voucher.prepared_by_id != request.user.pk or voucher.status != Voucher.Status.DRAFT:
            raise Conflict('Only the creator can self-approve their own draft voucher.')
        _check_budget(voucher)
        previous = voucher.status
        voucher.status = Voucher.Status.APPROVED
        voucher.approver = None
        voucher.approved_by = request.user
        voucher.approved_at = timezone.now()
        voucher.save(update_fields=['status', 'approver', 'approved_by', 'approved_at', 'updated_at'])
        _event(voucher, request.user, 'self_approved', previous)
    _audit(request, 'self_approve', voucher, new={'status': voucher.status})
    return voucher


def approve_voucher(request, voucher_id):
    _ensure_module()
    if not has_any(request.user, ['vouchers.approve']) or is_branch_side(request.user):
        raise Forbidden('Only an authorized main-office manager can approve payment vouchers')
    with transaction.atomic():
        voucher = get_voucher(request.user, voucher_id, for_update=True)
        if voucher.status != Voucher.Status.PENDING or voucher.approver_id != request.user.pk:
            raise Conflict('This voucher is not assigned to you for approval.')
        if voucher.prepared_by_id == request.user.pk:
            raise Conflict('The voucher creator cannot approve their own voucher through the manager workflow.')
        _check_budget(voucher)
        previous = voucher.status
        voucher.status = Voucher.Status.APPROVED
        voucher.approved_by = request.user
        voucher.approved_at = timezone.now()
        voucher.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        _event(voucher, request.user, 'approved', previous)
    _audit(request, 'approve', voucher, new={'status': voucher.status})
    return voucher


def reject_voucher(request, voucher_id, reason):
    _ensure_module()
    if not has_any(request.user, ['vouchers.approve']) or is_branch_side(request.user):
        raise Forbidden('Only an authorized main-office manager can reject payment vouchers')
    reason = (reason or '').strip()
    if not reason:
        raise BadRequest('Enter a reason before rejecting a voucher.')
    with transaction.atomic():
        voucher = get_voucher(request.user, voucher_id, for_update=True)
        if voucher.status != Voucher.Status.PENDING or voucher.approver_id != request.user.pk:
            raise Conflict('This voucher is not assigned to you for review.')
        previous = voucher.status
        voucher.status = Voucher.Status.REJECTED
        voucher.rejected_at = timezone.now()
        voucher.rejection_reason = reason[:500]
        voucher.save(update_fields=['status', 'rejected_at', 'rejection_reason', 'updated_at'])
        _event(voucher, request.user, 'rejected', previous, voucher.rejection_reason)
    _audit(request, 'reject', voucher, new={'status': voucher.status, 'reason': voucher.rejection_reason})
    return voucher


def create_schedule(request, form):
    _ensure_module()
    if not has_any(request.user, ['vouchers.schedule']):
        raise Forbidden('You do not have permission to schedule payment vouchers')
    with transaction.atomic():
        schedule = form.save(commit=False)
        schedule.created_by = request.user
        schedule.save()
    log_audit(request, 'payment_voucher.schedule_create', 'VoucherSchedule', schedule.pk,
              new_value=_schedule_snapshot(schedule))
    return schedule


def update_schedule(request, schedule_id, form):
    _ensure_module()
    if not has_any(request.user, ['vouchers.schedule']):
        raise Forbidden('You do not have permission to edit voucher schedules')
    with transaction.atomic():
        schedule = get_schedule(request.user, schedule_id, for_update=True)
        if schedule.created_by_id != request.user.pk and (
                is_branch_side(request.user) or not has_any(request.user, ['vouchers.approve'])):
            raise Forbidden('You cannot edit this voucher schedule')
        old = _schedule_snapshot(schedule)
        updated = form.save(commit=False)
        updated.pk = schedule.pk
        updated.created_by = schedule.created_by
        updated.save()
    log_audit(request, 'payment_voucher.schedule_update', 'VoucherSchedule', updated.pk,
              old_value=old, new_value=_schedule_snapshot(updated))
    return updated


def advance_date(current, frequency):
    if frequency == VoucherSchedule.Frequency.WEEKLY:
        return current + timedelta(days=7)
    months = {VoucherSchedule.Frequency.MONTHLY: 1, VoucherSchedule.Frequency.QUARTERLY: 3,
              VoucherSchedule.Frequency.YEARLY: 12}[frequency]
    month_index = current.month - 1 + months
    year = current.year + month_index // 12
    month = month_index % 12 + 1
    day = min(current.day, monthrange(year, month)[1])
    return date(year, month, day)


def generate_due_schedules(today=None):
    _ensure_module()
    today = today or timezone.localdate()
    generated = 0
    errors = []
    schedule_ids = VoucherSchedule.objects.filter(is_active=True, next_run__lte=today).values_list('pk', flat=True)
    for schedule_id in schedule_ids:
        try:
            with transaction.atomic():
                schedule = (VoucherSchedule.objects.select_for_update()
                            .select_related('category', 'created_by', 'approver', 'branch').get(pk=schedule_id))
                while schedule.is_active and schedule.next_run <= today:
                    due_date = schedule.next_run
                    if schedule.approver_id and schedule.approver_id != schedule.created_by_id \
                            and _valid_approver(schedule.approver):
                        status = Voucher.Status.PENDING
                        approved_by = None
                        approved_at = None
                        submitted_at = timezone.now()
                    elif (not schedule.approver_id and Setting.get().payment_voucher_self_approval_enabled
                          and has_any(schedule.created_by, ['vouchers.self_approve'])):
                        status = Voucher.Status.APPROVED
                        approved_by = schedule.created_by
                        approved_at = timezone.now()
                        submitted_at = None
                    else:
                        raise BadRequest(f'Schedule "{schedule.title}" has no active authorized approver.')
                    voucher, created = Voucher.objects.get_or_create(
                        schedule=schedule, scheduled_for=due_date,
                        defaults={
                            'number': next_number('PV', yearly=True), 'amount': schedule.amount, 'date': due_date,
                            'cash': schedule.cash, 'method_of_payment': schedule.method_of_payment, 'to': schedule.to,
                            'account_details': schedule.account_details, 'cheque_number': schedule.cheque_number,
                            'being': schedule.being, 'payee': schedule.payee, 'category': schedule.category,
                            'branch': schedule.branch, 'prepared_by': schedule.created_by,
                            'approver': schedule.approver if status == Voucher.Status.PENDING else None,
                            'status': status, 'approval_requested_at': submitted_at,
                            'approved_by': approved_by, 'approved_at': approved_at,
                        },
                    )
                    if created:
                        _event(voucher, schedule.created_by,
                               'submitted' if status == Voucher.Status.PENDING else 'self_approved',
                               Voucher.Status.DRAFT, f'Generated from schedule: {schedule.title}')
                        log_audit(None, 'payment_voucher.schedule_generate', 'PaymentVoucher', voucher.pk,
                                  new_value={'number': voucher.number, 'scheduled_for': str(due_date)},
                                  actor=schedule.created_by)
                        generated += 1
                    schedule.next_run = advance_date(due_date, schedule.frequency)
                schedule.save(update_fields=['next_run', 'updated_at'])
        except BadRequest as exc:
            errors.append(str(exc))
    return generated, errors
