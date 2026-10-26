from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.constants import PETTY_CASH_ENTRY, PETTY_CASH_STATUS, choices
from core.models import AppendOnlyModel, AppendOnlyQuerySet

MONEY = dict(max_digits=12, decimal_places=2)


class PettyCashRequest(models.Model):
    number = models.CharField(max_length=30, unique=True)  # PCR-2026-0001
    branch = models.ForeignKey('accounts.Branch', on_delete=models.PROTECT, related_name='+')  # the main office counts too
    amount_requested = models.DecimalField(validators=[MinValueValidator(Decimal('0.01'))], **MONEY)
    amount_approved = models.DecimalField(default=Decimal('0.00'), **MONEY)
    purpose = models.CharField(max_length=300, blank=True, default='')
    status = models.CharField(max_length=20, choices=choices(PETTY_CASH_STATUS), default=PETTY_CASH_STATUS.SUBMITTED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=200, blank=True, default='')  # reason for a reduced amount or a rejection
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['branch', 'status', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return self.number


class PettyCashEntryQuerySet(AppendOnlyQuerySet):
    message = 'Petty cash entries cannot be changed. Post a reversal instead.'


class PettyCashEntry(AppendOnlyModel):
    """One row per cash movement. A branch's balance is the SUM of `amount` (+ in, - out), never typed by hand."""
    branch = models.ForeignKey('accounts.Branch', on_delete=models.PROTECT, related_name='petty_cash_entries')
    type = models.CharField(max_length=20, choices=choices(PETTY_CASH_ENTRY))
    amount = models.DecimalField(**MONEY)
    description = models.CharField(max_length=300, blank=True, default='')
    entry_date = models.DateField()  # the day the money was received or spent
    request = models.ForeignKey(PettyCashRequest, null=True, blank=True, on_delete=models.PROTECT, related_name='entries')
    reversal_of = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='reversed_by')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PettyCashEntryQuerySet.as_manager()
    objects_message = 'Petty cash entries cannot be changed. Post a reversal instead.'

    class Meta:
        ordering = ['-entry_date', '-created_at', '-id']
        indexes = [models.Index(fields=['branch', '-entry_date', '-id'])]

    def __str__(self):
        return f'{self.type} {self.amount:+} branch {self.branch_id}'
