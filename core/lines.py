"""Reads the repeating "line item" rows of a document form (purchase, issue, request, dispatch...).

The page posts parallel lists such as item=3&item=7&quantity=2&quantity=5. parse_lines turns them
into rows and per-row errors, and keeps the typed values so the form can be shown again unchanged.
"""
import re
from decimal import Decimal, InvalidOperation

from catalog.models import Item


def _whole(text, minimum, label='Enter a quantity'):
    text = (text or '').strip()
    if text == '':
        return None, label
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None, 'Enter a number'
    if d != d.to_integral_value():
        return None, 'Use a whole number'
    n = int(d)
    if n < minimum:
        return None, 'Cannot be negative' if minimum == 0 else f'At least {minimum}'
    return n, None


def _money(text):
    text = (text or '').strip()
    if text == '':
        return None, 'Enter the unit cost'
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None, 'Enter a number'
    if not d.is_finite():
        return None, 'Enter a number'
    if d < 0:
        return None, 'Cannot be negative'
    return d.quantize(Decimal('0.01')), None


def parse_lines(post, *, kind, min_quantity=1, key='quantity'):
    """kind: 'purchase' (item, quantity_ordered, unit_cost) or 'simple' (item, quantity).

    Returns (rows, ok). Each row is {'item_id', 'item' (Item or None), 'quantity', 'unit_cost',
    'raw': {...typed text...}, 'errors': {field: message}}; ok is False if any row has errors or none were entered.
    """
    items = post.getlist('line_item')
    qtys = post.getlist('line_quantity')
    costs = post.getlist('line_unit_cost')
    rows, ok = [], True
    ids = []
    for raw in items:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            pass
    found = {i.pk: i for i in Item.objects.filter(pk__in=ids)}
    for n, raw_item in enumerate(items):
        raw_q = qtys[n] if n < len(qtys) else ''
        raw_c = costs[n] if n < len(costs) else ''
        if not (raw_item or '').strip() and not (raw_q or '').strip() and not (raw_c or '').strip():
            continue  # a completely empty spare row is ignored
        errors = {}
        item = None
        try:
            item = found.get(int(raw_item))
        except (TypeError, ValueError):
            item = None
        if item is None:
            errors['item'] = 'Choose an item'
        qty, err = _whole(raw_q, min_quantity)
        if err:
            errors['quantity'] = err
        cost = None
        if kind == 'purchase':
            cost, err = _money(raw_c)
            if err:
                errors['unit_cost'] = err
        if errors:
            ok = False
        rows.append({'item_id': item.pk if item else (raw_item or ''), 'item': item, 'quantity': qty, 'unit_cost': cost,
                     'raw': {'item': raw_item, 'quantity': raw_q, 'unit_cost': raw_c}, 'errors': errors})
    if not rows:
        ok = False
    return rows, ok


def lines_error(rows):
    return 'Add at least one item' if not rows else None


def parse_pairs(post, names, minimum=0):
    """For forms that decide on existing rows (review, receive, dispatch quantities):
    returns {row_id: {name: int}} read from fields like  approved_<id>  /  reason_<id>."""
    out = {}
    pat = re.compile(r'^(' + '|'.join(re.escape(n) for n in names) + r')_(\d+)$')
    for k in post:
        m = pat.match(k)
        if m:
            out.setdefault(int(m.group(2)), {})[m.group(1)] = post.get(k, '')
    return out


def whole_number(text, minimum=0):
    return _whole(text, minimum)
