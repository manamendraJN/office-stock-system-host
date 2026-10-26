"""Pure rules for office issues (ported from issueRules.js). Return an error message or None."""
from core.constants import ISSUE_STATUS


def shortage_problem(lines, balances, names):
    """Every item must have enough stock at the issuing branch.

    lines:    [{'item': item_id, 'quantity': int}]
    balances: {item_id: quantity}
    names:    {item_id: name}
    """
    short = []
    for l in lines:
        have = balances.get(l['item'], 0)
        if l['quantity'] > have:
            short.append((names.get(l['item']) or 'An item', have, l['quantity']))
    if not short:
        return None
    parts = [f'{name} ({max(have, 0)} in stock, you entered {want})' for name, have, want in short]
    return f"Not enough stock for: {'; '.join(parts)}"


def cancel_problem(status):
    return 'This issue was already cancelled' if status == ISSUE_STATUS.CANCELLED else None


def total_units(lines):
    return sum(l.quantity for l in lines)
