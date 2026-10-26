from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.constants import DISPATCH_STATUS, REQUEST_STATUS, choices


class Request(models.Model):
    number = models.CharField(max_length=30, unique=True)  # REQ-2026-0001
    branch = models.ForeignKey('accounts.Branch', on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=20, choices=choices(REQUEST_STATUS), default=REQUEST_STATUS.SUBMITTED)
    notes = models.CharField(max_length=300, blank=True, default='')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
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


class RequestLine(models.Model):
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='+')
    quantity_requested = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_approved = models.PositiveIntegerField(default=0)
    quantity_dispatched = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=200, blank=True, default='')  # officer's note when reducing or rejecting a line

    class Meta:
        ordering = ['id']


class Dispatch(models.Model):
    reference = models.CharField(max_length=30, unique=True)  # DSP-2026-0001
    request = models.ForeignKey(Request, null=True, blank=True, on_delete=models.PROTECT, related_name='dispatches')  # optional: urgent dispatches
    destination = models.ForeignKey('accounts.Branch', on_delete=models.PROTECT, related_name='+')
    dispatch_date = models.DateField()
    status = models.CharField(max_length=30, choices=choices(DISPATCH_STATUS), default=DISPATCH_STATUS.IN_TRANSIT)
    dispatched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-dispatch_date', '-created_at']
        indexes = [
            models.Index(fields=['destination', 'status', '-dispatch_date', '-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return self.reference


class DispatchLine(models.Model):
    dispatch = models.ForeignKey(Dispatch, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='+')
    quantity_sent = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_received = models.PositiveIntegerField(default=0)
    quantity_damaged = models.PositiveIntegerField(default=0)
    quantity_short = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        ordering = ['id']
