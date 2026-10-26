"""Pure rules for branch requests and dispatches (ported from requestRules.js).

Functions return an error message, a plan dict, or None; no database calls.
Request lines carry .id, .item_id, .quantity_requested, .quantity_approved, .quantity_dispatched.
Dispatch lines carry .item_id, .quantity_sent, .quantity_damaged, .quantity_short.
"""
from core.constants import REQUEST_STATUS, DISPATCH_STATUS
from core.rules.issue_rules import shortage_problem


def outstanding(line):
    return max((line.quantity_approved or 0) - (line.quantity_dispatched or 0), 0)


def can_dispatch(status, lines):
    return status in (REQUEST_STATUS.APPROVED, REQUEST_STATUS.PARTLY_APPROVED) and any(outstanding(l) > 0 for l in lines)


def cancel_request_problem(status):
    return None if status == REQUEST_STATUS.SUBMITTED else 'Only a request that is still waiting for review can be cancelled'


def review_plan(status, lines, decisions):
    """decisions: [{'line_id', 'quantity_approved', 'reason'}]. Every line needs a decision.
    Approving everything -> approved; less than asked -> partly approved; nothing -> rejected.
    Returns {'problem'} or {'lines': [(line, quantity_approved, reason)], 'status'}."""
    if status != REQUEST_STATUS.SUBMITTED:
        return {'problem': 'This request has already been reviewed'}
    seen = set()
    out = []
    for d in decisions:
        key = str(d['line_id'])
        if key in seen:
            return {'problem': 'A line was entered twice'}
        seen.add(key)
        line = next((l for l in lines if str(l.id) == key), None)
        if line is None:
            return {'problem': 'One of the lines does not belong to this request'}
        if d['quantity_approved'] > line.quantity_requested:
            return {'problem': f'Cannot approve more than the {line.quantity_requested} requested'}
        if d['quantity_approved'] < line.quantity_requested and not d.get('reason'):
            return {'problem': 'Give a reason for every line you reduce or reject'}
        out.append((line, d['quantity_approved'], d.get('reason') or ''))
    if len(out) != len(lines):
        return {'problem': 'Decide every item on the request'}

    approved = sum(q for _, q, _ in out)
    full = all(q == line.quantity_requested for line, q, _ in out)
    if approved == 0:
        new_status = REQUEST_STATUS.REJECTED
    elif full:
        new_status = REQUEST_STATUS.APPROVED
    else:
        new_status = REQUEST_STATUS.PARTLY_APPROVED
    return {'lines': out, 'status': new_status}


def status_after_dispatch(status, lines):
    """Once everything approved has been sent, the request is complete."""
    return status if can_dispatch(status, lines) else REQUEST_STATUS.COMPLETED


def dispatch_plan(*, request_status=None, request_lines=None, has_request=False, requested, balances, names):
    """What may be sent now. requested is [{'item': item_id, 'quantity': int}]; zero lines are ignored.
    Returns {'problem'} or {'postings': [{'item', 'quantity'}]}."""
    if has_request and not can_dispatch(request_status, request_lines):
        return {'problem': 'Nothing is left to send on this request'}
    postings = []
    for r in requested:
        if r['quantity'] == 0:
            continue
        if has_request:
            line = next((l for l in request_lines if l.item_id == r['item']), None)
            if line is None:
                return {'problem': 'One of the items is not on this request'}
            left = outstanding(line)
            if r['quantity'] > left:
                name = names.get(r['item']) or 'an item'
                return {'problem': f'Only {left} of "{name}" still to send on this request (you entered {r["quantity"]})'}
        postings.append({'item': r['item'], 'quantity': r['quantity']})
    if not postings:
        return {'problem': 'Enter a quantity for at least one item'}
    short = shortage_problem(postings, balances, names)
    return {'problem': short} if short else {'postings': postings}


def receipt_plan(status, lines, received):
    """The branch says what arrived. Anything not received or damaged counts as short.
    received: [{'item', 'received', 'damaged'}]. Returns {'problem'} or {'lines': [...], 'status'}."""
    if status != DISPATCH_STATUS.IN_TRANSIT:
        return {'problem': 'This dispatch has already been received'}
    seen = set()
    out = []
    for r in received:
        if r['item'] in seen:
            return {'problem': 'An item was entered twice'}
        seen.add(r['item'])
        line = next((l for l in lines if l.item_id == r['item']), None)
        if line is None:
            return {'problem': 'One of the items is not on this dispatch'}
        if r['received'] + r['damaged'] > line.quantity_sent:
            return {'problem': f'Received plus damaged is more than the {line.quantity_sent} sent on one of the lines'}
        out.append({
            'line': line, 'received': r['received'], 'damaged': r['damaged'],
            'short': line.quantity_sent - r['received'] - r['damaged'],
        })
    if len(out) != len(lines):
        return {'problem': 'Enter the result for every item'}
    clean = all(o['received'] == o['line'].quantity_sent for o in out)
    return {'lines': out, 'status': DISPATCH_STATUS.RECEIVED if clean else DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES}


def close_plan(status, lines):
    """Closing settles what was damaged or short. Returns {'problem'} or {'leftovers': [...]}."""
    if status != DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES:
        return {'problem': 'Only a dispatch received with differences can be closed'}
    leftovers = [
        {'item': l.item_id, 'damaged': l.quantity_damaged or 0, 'short': l.quantity_short or 0}
        for l in lines if (l.quantity_damaged or 0) + (l.quantity_short or 0) > 0
    ]
    return {'leftovers': leftovers}
