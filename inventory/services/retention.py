"""The 30-day ledger retention job (ported from stockRetentionService.js).

Movements older than 30 days are replaced by one hidden "opening balance" row per item and location, so
balances keep summing correctly while the detailed rows are permanently removed.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.constants import LEDGER_TYPES
from core.models import Setting
from inventory.models import StockLedger

RETENTION_DAYS = 30


def prune_old_stock_movements(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    lock_until = timezone.now() + timedelta(hours=1)
    result = {'cutoff': cutoff, 'deleted_count': 0, 'opening_balance_count': 0, 'skipped': False}

    # Only one cleanup at a time: take the lock only if nobody holds it (or it has expired).
    got = Setting.objects.filter(key='app').filter(
        Q(stock_retention_lock_until__isnull=True) | Q(stock_retention_lock_until__lte=timezone.now())
    ).update(stock_retention_lock_until=lock_until)
    if not got:
        result['skipped'] = True
        return result

    try:
        with transaction.atomic():
            groups = (StockLedger.objects.filter(created_at__lt=cutoff).order_by()
                      .values('item_id', 'branch_id', 'in_transit').annotate(total=Sum('quantity_change')))
            openings = [g for g in groups if g['total']]
            if openings:
                StockLedger.objects.bulk_create([
                    StockLedger(item_id=g['item_id'], branch_id=g['branch_id'], in_transit=bool(g['in_transit']),
                                quantity_change=g['total'], type=LEDGER_TYPES.OPENING_BALANCE,
                                source_model='StockRetention', reason='retention_baseline',
                                note='Net balance retained after 30-day movement cleanup')
                    for g in openings])
                result['opening_balance_count'] = len(openings)
            # The explicit maintenance path: the only code that bypasses the ledger's delete guard.
            result['deleted_count'] = StockLedger.objects.filter(created_at__lt=cutoff).unsafe_delete()
    finally:
        Setting.objects.filter(key='app', stock_retention_lock_until=lock_until).update(stock_retention_lock_until=None)
    return result
