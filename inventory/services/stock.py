"""Stock balances and the locks that keep them honest.

Balances are never stored: they are the sum of ledger rows.
"""
from django.db.models import Sum

from accounts.models import Branch
from catalog.models import Item
from core.constants import BRANCH_TYPES
from inventory.models import StockLedger


def get_main_branch():
    return Branch.objects.filter(type=BRANCH_TYPES.MAIN).first()


def get_balances(branch_id, item_ids=None):
    """{item_id: quantity} at one branch (a branch id, never in-transit)."""
    if not branch_id:
        return {}
    qs = StockLedger.objects.filter(branch_id=branch_id)
    if item_ids is not None:
        qs = qs.filter(item_id__in=list(item_ids))
    rows = qs.order_by().values('item_id').annotate(quantity=Sum('quantity_change'))
    return {r['item_id']: r['quantity'] or 0 for r in rows}


def get_balance(branch_id, item_id):
    return get_balances(branch_id, [item_id]).get(item_id, 0)


def lock_items(item_ids):
    """Call inside transaction.atomic(). Takes a row lock on each item (always in id order, so two
    people locking the same items cannot deadlock). Anyone else checking or posting stock for the
    same item waits here and then re-reads the balance, so two people cannot both spend the last unit.
    SQLite ignores the lock hint but serialises writers on its own."""
    ids = sorted({int(i) for i in item_ids})
    list(Item.objects.select_for_update().filter(pk__in=ids).order_by('pk').values_list('pk', flat=True))
    return ids
