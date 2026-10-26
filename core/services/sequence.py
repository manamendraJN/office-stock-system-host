from django.utils import timezone

from core.models import Counter


def next_number(prefix, yearly=False):
    """next_number('ITM') -> ITM-0001; next_number('REQ', yearly=True) -> REQ-2026-0001 (restarts each year)."""
    if not yearly:
        return f'{prefix}-{Counter.next(prefix):04d}'
    year = timezone.localtime().year
    return f'{prefix}-{year}-{Counter.next(f"{prefix}-{year}"):04d}'
