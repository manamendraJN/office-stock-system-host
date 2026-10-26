"""Pure rules for the dashboard and reports (ported from reportRules.js). No database calls.

Every report builder returns {'columns', 'rows', 'totals'} so one screen (and one CSV export)
can show them all. Inputs are plain dicts that the report service builds from the database:

  items:      [{id, code, name, unit, category, min_stock, last_unit_cost, active}]
  purchases:  [{id, status, supplier: {id, name}, lines: [{item: {id, code, name, unit},
               quantity_ordered, quantity_received, unit_cost}]}]
  issues:     [{id, status, department, lines: [{item: {...}, quantity}]}]
  dispatches: [{id, destination: {id, name}, lines: [{item: {...}, quantity_sent, quantity_received,
               quantity_damaged, quantity_short}]}]
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from core.rules.purchase_rules import round2

_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _parse_day(value):
    """A calendar day typed as YYYY-MM-DD, checked for real (2026-02-31 is refused)."""
    if not _DAY.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_range(from_value=None, to_value=None):
    """Turns the from/to boxes into an inclusive date range.

    Returns {'from': date|None, 'to': date|None} or {'problem': message}."""
    out = {'from': None, 'to': None}
    if from_value:
        out['from'] = _parse_day(str(from_value))
        if out['from'] is None:
            return {'problem': 'Enter the "from" date as a real date'}
    if to_value:
        out['to'] = _parse_day(str(to_value))
        if out['to'] is None:
            return {'problem': 'Enter the "to" date as a real date'}
    if out['from'] and out['to'] and out['from'] > out['to']:
        return {'problem': 'The "from" date is after the "to" date'}
    return out


def month_range(today):
    """First day of this month and of next month."""
    start = date(today.year, today.month, 1)
    nxt = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    return start, nxt


def quick_ranges(today):
    """The 'This month / Last month / This year / All time' shortcuts as (from, to) ISO strings."""
    start, _ = month_range(today)
    last_month_end = start - timedelta(days=1)
    last_month_start = date(last_month_end.year, last_month_end.month, 1)
    return {
        'month': (start.isoformat(), today.isoformat()),
        'last_month': (last_month_start.isoformat(), last_month_end.isoformat()),
        'year': (date(today.year, 1, 1).isoformat(), today.isoformat()),
        'all': ('', ''),
    }


def _name_key(row):
    return str(row.get('name') or row.get('supplier') or row.get('department') or '').lower()


def totals_for(columns, rows):
    """Adds up the columns marked sum=True."""
    totals = {}
    for c in columns:
        if c.get('sum'):
            totals[c['key']] = round2(sum((Decimal(r.get(c['key']) or 0) for r in rows), Decimal(0)))
    return totals


def _finish(columns, rows):
    return {'columns': columns, 'rows': rows, 'totals': totals_for(columns, rows)}


# ---------- current stock ----------
def balance_report(items, balances, low_only=False):
    rows = []
    for i in items:
        quantity = balances.get(i['id'], 0)
        min_stock = i.get('min_stock') or 0
        active = bool(i.get('active'))
        low = active and quantity <= min_stock
        if not active:
            status = 'Inactive'
        elif quantity <= 0:
            status = 'Out of stock'
        elif low:
            status = 'Low stock'
        else:
            status = 'In stock'
        cost = i.get('last_unit_cost')
        rows.append({
            'code': i['code'], 'name': i['name'], 'category': i.get('category') or '', 'unit': i['unit'],
            'quantity': quantity, 'min_stock': min_stock, 'status': status,
            'unit_cost': cost,
            # Value is only worked out when a cost is known; stock below zero never counts as value.
            'value': None if cost is None else round2(Decimal(max(quantity, 0)) * Decimal(cost)),
            '_low': low, '_active': active,
        })
    # Inactive items only matter while they still hold stock.
    rows = [r for r in rows if r['_active'] or r['quantity'] != 0]
    rows = [r for r in rows if not low_only or r['_low']]
    for r in rows:
        del r['_low'], r['_active']
    rows.sort(key=_name_key)
    return _finish([
        {'key': 'code', 'label': 'Code', 'type': 'code'},
        {'key': 'name', 'label': 'Item'},
        {'key': 'category', 'label': 'Category'},
        {'key': 'quantity', 'label': 'In stock', 'type': 'number'},
        {'key': 'unit', 'label': 'Unit'},
        {'key': 'min_stock', 'label': 'Minimum', 'type': 'number'},
        {'key': 'status', 'label': 'Status', 'type': 'status'},
        {'key': 'unit_cost', 'label': 'Last cost', 'type': 'money'},
        {'key': 'value', 'label': 'Stock value', 'type': 'money', 'sum': True},
    ], rows)


# ---------- purchases ----------
def purchase_report(purchases, by='supplier'):
    """Cancelled purchases never count."""
    live = [p for p in purchases if p['status'] != 'cancelled']
    groups = {}

    def add(key, base, p, l):
        g = groups.get(key)
        if g is None:
            g = {**base, 'purchases': set(), 'quantity_ordered': 0, 'quantity_received': 0,
                 'ordered_value': Decimal(0), 'received_value': Decimal(0)}
            groups[key] = g
        g['purchases'].add(p['id'])
        g['quantity_ordered'] += l['quantity_ordered']
        g['quantity_received'] += l.get('quantity_received') or 0
        g['ordered_value'] += Decimal(l['quantity_ordered']) * Decimal(l['unit_cost'])
        g['received_value'] += Decimal(l.get('quantity_received') or 0) * Decimal(l['unit_cost'])

    for p in live:
        for l in p['lines']:
            if by == 'item':
                it = l['item']
                add(it['id'], {'code': it['code'], 'name': it['name'], 'unit': it['unit']}, p, l)
            else:
                sup = p.get('supplier') or {}
                add(sup.get('id'), {'supplier': sup.get('name') or 'Unknown supplier'}, p, l)

    rows = []
    for g in groups.values():
        ordered = round2(g['ordered_value'])
        received = round2(g['received_value'])
        rows.append({**g, 'purchases': len(g['purchases']), 'ordered_value': ordered,
                     'received_value': received, 'outstanding_value': round2(g['ordered_value'] - g['received_value'])})
    rows.sort(key=lambda r: r['ordered_value'], reverse=True)

    money = [
        {'key': 'ordered_value', 'label': 'Ordered value', 'type': 'money', 'sum': True},
        {'key': 'received_value', 'label': 'Received value', 'type': 'money', 'sum': True},
        {'key': 'outstanding_value', 'label': 'Still to receive', 'type': 'money', 'sum': True},
    ]
    if by == 'item':
        lead = [{'key': 'code', 'label': 'Code', 'type': 'code'}, {'key': 'name', 'label': 'Item'}, {'key': 'unit', 'label': 'Unit'}]
    else:
        lead = [{'key': 'supplier', 'label': 'Supplier'}]
    return _finish([
        *lead,
        {'key': 'purchases', 'label': 'Purchases', 'type': 'number'},
        {'key': 'quantity_ordered', 'label': 'Qty ordered', 'type': 'number'},
        {'key': 'quantity_received', 'label': 'Qty received', 'type': 'number'},
        *money,
    ], rows)


# ---------- usage (office issues) ----------
def usage_report(issues, by='item'):
    """Cancelled issues never count. Units of different items are never added together."""
    live = [i for i in issues if i['status'] != 'cancelled']
    groups = {}
    for issue in live:
        for l in issue['lines']:
            dept = (issue.get('department') or '').strip() or 'No department'
            if by == 'department':
                key, base = dept, {'department': dept}
            else:
                it = l['item']
                key, base = it['id'], {'code': it['code'], 'name': it['name'], 'unit': it['unit']}
            g = groups.get(key)
            if g is None:
                g = {**base, 'issues': set(), 'quantity': 0}
                groups[key] = g
            g['issues'].add(issue['id'])
            g['quantity'] += l['quantity']
    rows = [{**g, 'issues': len(g['issues'])} for g in groups.values()]
    rows.sort(key=lambda r: r['quantity'], reverse=True)
    if by == 'department':
        lead = [{'key': 'department', 'label': 'Department'}]
    else:
        lead = [{'key': 'code', 'label': 'Code', 'type': 'code'}, {'key': 'name', 'label': 'Item'}, {'key': 'unit', 'label': 'Unit'}]
    # No total: units of different items (reams, boxes, pens) are not worth adding together.
    return _finish([*lead, {'key': 'issues', 'label': 'Times issued', 'type': 'number'},
                    {'key': 'quantity', 'label': 'Quantity issued', 'type': 'number'}], rows)


# ---------- dispatches ----------
def dispatch_report(dispatches):
    groups = {}
    for d in dispatches:
        dest = d.get('destination') or {}
        for l in d['lines']:
            it = l['item']
            key = (dest.get('id'), it['id'])
            g = groups.get(key)
            if g is None:
                g = {'branch': dest.get('name') or 'Unknown branch', 'code': it['code'], 'name': it['name'],
                     'unit': it['unit'], 'dispatches': set(), 'sent': 0, 'received': 0, 'damaged': 0, 'short': 0}
                groups[key] = g
            g['dispatches'].add(d['id'])
            g['sent'] += l['quantity_sent']
            g['received'] += l.get('quantity_received') or 0
            g['damaged'] += l.get('quantity_damaged') or 0
            g['short'] += l.get('quantity_short') or 0
    rows = [{**g, 'dispatches': len(g['dispatches'])} for g in groups.values()]
    rows.sort(key=lambda r: (r['branch'].lower(), str(r['name']).lower()))
    return _finish([
        {'key': 'branch', 'label': 'Branch'},
        {'key': 'code', 'label': 'Code', 'type': 'code'},
        {'key': 'name', 'label': 'Item'},
        {'key': 'unit', 'label': 'Unit'},
        {'key': 'dispatches', 'label': 'Dispatches', 'type': 'number'},
        {'key': 'sent', 'label': 'Sent', 'type': 'number'},
        {'key': 'received', 'label': 'Received', 'type': 'number'},
        {'key': 'damaged', 'label': 'Damaged', 'type': 'number'},
        {'key': 'short', 'label': 'Missing', 'type': 'number'},
    ], rows)


# ---------- dashboard ----------
def low_stock_items(items, balances, limit=6):
    """The items running low or out, most urgent first (largest shortfall against the minimum)."""
    low = []
    for i in items:
        if not i.get('active'):
            continue
        minimum = i.get('min_stock') or 0
        quantity = balances.get(i['id'], 0)
        if quantity <= minimum:
            low.append({'id': i['id'], 'code': i['code'], 'name': i['name'], 'unit': i['unit'],
                        'min_stock': minimum, 'quantity': quantity})
    low.sort(key=lambda i: (-(i['min_stock'] - i['quantity']), i['name'].lower()))
    return {
        'count': len(low),
        'out_of_stock': sum(1 for i in low if i['quantity'] <= 0),
        'items': low[:limit],
    }


def spent_total(purchases):
    """purchases: [{'status', 'lines': [{'quantity_ordered', 'unit_cost'}]}]; cancelled ones never count."""
    total = Decimal(0)
    for p in purchases:
        if p['status'] == 'cancelled':
            continue
        total += sum((Decimal(l['quantity_ordered']) * Decimal(l['unit_cost']) for l in p['lines']), Decimal(0))
    return round2(total)
