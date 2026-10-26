"""Pure business rules for purchases (ported from purchaseRules.js).

Functions return an error message (string) or a value; no database calls. `lines` are objects with
.id, .item_id, .quantity_ordered, .quantity_received and .unit_cost (ORM rows or stand-ins).
"""
from decimal import Decimal, ROUND_HALF_UP

from core.constants import PURCHASE_STATUS

_CENT = Decimal('0.01')


def round2(value):
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def purchase_total(lines):
    return round2(sum((Decimal(l.quantity_ordered) * Decimal(l.unit_cost) for l in lines), Decimal(0)))


def status_from_lines(lines):
    """ordered -> partly_received -> received. Cancelled is set explicitly, never derived."""
    received = sum((l.quantity_received or 0) for l in lines)
    if received == 0:
        return PURCHASE_STATUS.ORDERED
    complete = all((l.quantity_received or 0) >= l.quantity_ordered for l in lines)
    return PURCHASE_STATUS.RECEIVED if complete else PURCHASE_STATUS.PARTLY_RECEIVED


def has_receipts(lines):
    return any((l.quantity_received or 0) > 0 for l in lines)


def locked_problem(status, lines, verb):
    """Editing or cancelling is only safe while no stock has been posted against the purchase."""
    if status == PURCHASE_STATUS.CANCELLED:
        return 'This purchase was cancelled'
    if has_receipts(lines):
        return f'Some items were already received, so this purchase can no longer be {verb}'
    return None


def duplicate_item_problem(item_ids):
    seen = set()
    for item_id in item_ids:
        key = str(item_id)
        if key in seen:
            return 'The same item is listed twice. Combine it into one line'
        seen.add(key)
    return None


def receipt_plan(status, lines, requested):
    """Validates a receipt request against the purchase and returns the lines to post.

    requested: [{'line_id': id, 'quantity': int}]
    Returns {'problem': str} or {'postings': [(line, quantity), ...]}.
    """
    if status == PURCHASE_STATUS.CANCELLED:
        return {'problem': 'This purchase was cancelled'}
    if status == PURCHASE_STATUS.RECEIVED:
        return {'problem': 'This purchase is already fully received'}

    postings = []
    seen = set()
    for r in requested:
        key = str(r['line_id'])
        if key in seen:
            return {'problem': 'A line was entered twice'}
        seen.add(key)

        line = next((l for l in lines if str(l.id) == key), None)
        if line is None:
            return {'problem': 'One of the lines does not belong to this purchase'}
        if r['quantity'] == 0:
            continue

        outstanding = line.quantity_ordered - (line.quantity_received or 0)
        if r['quantity'] > outstanding:
            return {'problem': f"Only {outstanding} still to receive on one of the lines (you entered {r['quantity']})"}
        postings.append((line, r['quantity']))
    if not postings:
        return {'problem': 'Enter a quantity for at least one item'}
    return {'postings': postings}
