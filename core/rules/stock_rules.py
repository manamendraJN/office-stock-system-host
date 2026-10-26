"""Pure rules for stock corrections (ported from stockRules.js). Return an error message or None."""

# Some reasons only make sense in one direction.
ADD_ONLY = ['found']
REMOVE_ONLY = ['damaged', 'expired']


def adjustment_problem(direction, reason, note):
    if reason in ADD_ONLY and direction != 'add':
        return 'Found stock can only be added'
    if reason in REMOVE_ONLY and direction != 'remove':
        return 'Damaged or expired stock can only be removed'
    if reason == 'other' and not note:
        return 'Please explain the reason in the note'
    return None


def signed_quantity(direction, quantity):
    return -quantity if direction == 'remove' else quantity


def negative_stock_problem(current, change, item_name):
    """Stock may never go below zero."""
    if current + change >= 0:
        return None
    return f'Only {max(current, 0)} of "{item_name}" in stock, so {-change} cannot be removed'


def stock_level(active, quantity, min_stock):
    return {'out': quantity <= 0, 'low': bool(active) and quantity <= min_stock}
