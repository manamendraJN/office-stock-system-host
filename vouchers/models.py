from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import AppendOnlyModel, AppendOnlyQuerySet

MONEY = {'max_digits': 12, 'decimal_places': 2}


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True, default='')
    monthly_budget_limit = models.DecimalField(
        validators=[MinValueValidator(Decimal('0.00'))], default=Decimal('0.00'), **MONEY,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'expense categories'

    def __str__(self):
        return self.name


class VoucherSchedule(models.Model):
    class Frequency(models.TextChoices):
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'
        QUARTERLY = 'quarterly', 'Quarterly'
        YEARLY = 'yearly', 'Yearly'

    title = models.CharField(max_length=150)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='schedules')
    amount = models.DecimalField(validators=[MinValueValidator(Decimal('0.01'))], **MONEY)
    frequency = models.CharField(max_length=12, choices=Frequency.choices)
    next_run = models.DateField()
    cash = models.BooleanField(default=False)
    method_of_payment = models.CharField(max_length=20, choices=[
        ('cash', 'Cash'), ('cheque', 'Cheque'), ('bank_transfer', 'Bank transfer'), ('online', 'Online'),
    ])
    to = models.CharField(max_length=200)
    account_details = models.CharField(max_length=250, blank=True, default='')
    cheque_number = models.CharField(max_length=50, blank=True, default='')
    being = models.CharField(max_length=250)
    payee = models.CharField(max_length=150)
    recommender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                    null=True, blank=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                 null=True, blank=True)
    branch = models.ForeignKey('accounts.Branch', on_delete=models.PROTECT, related_name='voucher_schedules')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['next_run', 'title']

    def __str__(self):
        return self.title


class Voucher(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        CHEQUE = 'cheque', 'Cheque'
        BANK_TRANSFER = 'bank_transfer', 'Bank transfer'
        ONLINE = 'online', 'Online'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        RECOMMENDING = 'recommending', 'Awaiting recommendation'
        PENDING = 'pending', 'Awaiting approval'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    number = models.CharField(max_length=30, unique=True, blank=True)
    amount = models.DecimalField(validators=[MinValueValidator(Decimal('0.01'))], **MONEY)
    date = models.DateField(default=timezone.localdate, db_index=True)
    cash = models.BooleanField(default=False)
    method_of_payment = models.CharField(max_length=20, choices=PaymentMethod.choices)
    to = models.CharField(max_length=200, verbose_name='To')
    account_details = models.CharField(max_length=250, blank=True, default='')
    cheque_number = models.CharField(max_length=50, blank=True, default='')
    receipt_attached = models.BooleanField(default=False)
    being = models.CharField(max_length=250)
    payee = models.CharField(max_length=150)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='vouchers')
    recommender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                    null=True, blank=True)
    recommended_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                       null=True, blank=True)
    recommended_at = models.DateTimeField(null=True, blank=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                 null=True, blank=True)
    approval_requested_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    branch = models.ForeignKey('accounts.Branch', on_delete=models.PROTECT, related_name='payment_vouchers',
                               db_index=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                    null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default='')
    schedule = models.ForeignKey(VoucherSchedule, on_delete=models.PROTECT, related_name='generated_vouchers',
                                 null=True, blank=True)
    scheduled_for = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['schedule', 'scheduled_for'], name='unique_voucher_schedule_date'),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='payment_voucher_amount_positive'),
        ]
        indexes = [
            models.Index(fields=['branch', 'status', '-created_at'], name='voucher_branch_status_idx'),
            models.Index(fields=['status', 'approver', 'date'], name='voucher_approval_queue_idx'),
            models.Index(fields=['status', 'recommender', 'date'], name='voucher_recommend_queue_idx'),
        ]

    @property
    def is_printable(self):
        return self.status == self.Status.APPROVED

    def __str__(self):
        return self.number or 'New payment voucher'


class VoucherEventQuerySet(AppendOnlyQuerySet):
    message = 'Voucher history cannot be changed or deleted.'


class VoucherEvent(AppendOnlyModel):
    voucher = models.ForeignKey(Voucher, on_delete=models.SET_NULL, related_name='events',
                                null=True, blank=True)
    voucher_number = models.CharField(max_length=30, blank=True, default='')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    action = models.CharField(max_length=30)
    previous_status = models.CharField(max_length=12, blank=True, default='')
    new_status = models.CharField(max_length=12, blank=True, default='')
    note = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = VoucherEventQuerySet.as_manager()
    objects_message = 'Voucher history cannot be changed or deleted.'

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        number = self.voucher.number if self.voucher_id else self.voucher_number
        return f'{number}: {self.action}'
