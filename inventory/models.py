from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.constants import ISSUE_STATUS, LEDGER_TYPES, PURCHASE_STATUS, choices
from core.models import AppendOnlyModel, AppendOnlyQuerySet


class StockLedgerQuerySet(AppendOnlyQuerySet):
    message = 'Stock ledger rows cannot be changed. Post a reversal instead.'


class StockLedger(AppendOnlyModel):
    """One row per stock movement. Balances are the SUM of quantity_change, never typed by hand.

    `branch` is the Branch holding the stock (the main office is a Branch of type "main");
    stock on its way between branches has branch=NULL and in_transit=True.
    """
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='ledger_rows')
    branch = models.ForeignKey('accounts.Branch', null=True, blank=True, on_delete=models.PROTECT, related_name='ledger_rows')
    in_transit = models.BooleanField(default=False)
    quantity_change = models.IntegerField()  # + in, - out
    type = models.CharField(max_length=20, choices=choices(LEDGER_TYPES))
    source_model = models.CharField(max_length=30, blank=True, default='')  # 'Purchase' | 'Dispatch' | 'OfficeIssue' ...
    source_id = models.CharField(max_length=40, blank=True, default='')
    reason = models.CharField(max_length=200, blank=True, default='')  # a code such as 'damaged', or free text
    note = models.CharField(max_length=200, blank=True, default='')
    reversal_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    # System-generated opening balances have no human author; all ordinary movements do.
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StockLedgerQuerySet.as_manager()
    objects_message = 'Stock ledger rows cannot be changed. Post a reversal instead.'

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['item', 'branch']),
            models.Index(fields=['branch', 'item']),
            models.Index(fields=['branch', '-created_at', '-id']),
            models.Index(fields=['-created_at', '-id']),
        ]

    def __str__(self):
        return f'{self.type} {self.quantity_change:+d} item {self.item_id}'


class Purchase(models.Model):
    number = models.CharField(max_length=30, unique=True)  # PUR-2026-0001
    supplier = models.ForeignKey('catalog.Supplier', on_delete=models.PROTECT, related_name='purchases')
    purchase_date = models.DateField()
    invoice_ref = models.CharField(max_length=80, blank=True, default='')
    # Where received stock is added. Older purchases have none and belong to the main office.
    branch = models.ForeignKey('accounts.Branch', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=20, choices=choices(PURCHASE_STATUS), default=PURCHASE_STATUS.ORDERED)
    notes = models.CharField(max_length=500, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']
        indexes = [
            models.Index(fields=['branch', '-purchase_date', '-created_at']),
            models.Index(fields=['status', '-purchase_date']),
        ]

    def __str__(self):
        return self.number


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='+')
    quantity_ordered = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_received = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        ordering = ['id']


class OfficeIssue(models.Model):
    """Items handed to staff for daily work. Stock leaves the issuing branch at once."""
    number = models.CharField(max_length=30, unique=True)  # ISS-2026-0001
    recipient = models.CharField(max_length=120)
    department = models.CharField(max_length=120, blank=True, default='')
    issue_date = models.DateField()
    # The branch whose stock is reduced. Older issues have none and belong to the main office.
    branch = models.ForeignKey('accounts.Branch', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=20, choices=choices(ISSUE_STATUS), default=ISSUE_STATUS.ISSUED)
    purpose = models.CharField(max_length=300, blank=True, default='')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issue_date', '-created_at']
        indexes = [
            models.Index(fields=['branch', '-issue_date', '-created_at']),
            models.Index(fields=['status', '-issue_date']),
        ]

    def __str__(self):
        return self.number


class OfficeIssueLine(models.Model):
    issue = models.ForeignKey(OfficeIssue, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='+')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ['id']
