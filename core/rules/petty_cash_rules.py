"""Pure rules for petty cash. Return an error message, a plan dict, or None; no database calls.

Money is Decimal (Rs.). A branch's balance is the sum of its ledger entries: approved top-ups add,
expenses subtract, a reversal undoes one expense.
"""
from decimal import Decimal

from core.constants import PETTY_CASH_ENTRY, PETTY_CASH_STATUS

MAX_AMOUNT = Decimal('99999999.99')


def is_low(balance, level):
    """Low means at or below the level the top management has set."""
    return Decimal(balance) <= Decimal(level)


def amount_problem(amount):
    if amount is None or Decimal(amount) <= 0:
        return 'Enter an amount above zero'
    if Decimal(amount) > MAX_AMOUNT:
        return 'That amount is too large'
    return None


def cancel_request_problem(status):
    return None if status == PETTY_CASH_STATUS.SUBMITTED else 'Only a request that is still waiting for approval can be cancelled'


def review_plan(status, requested, approve, approved_amount, note, *, is_requester, is_super_admin):
    """The manager approves (maybe a smaller amount, with a reason) or rejects (with a reason).
    A manager cannot review their own request, except the Super Admin, so a lone administrator is never locked out.
    Returns {'problem'} or {'status', 'amount'}."""
    if status != PETTY_CASH_STATUS.SUBMITTED:
        return {'problem': 'This request has already been reviewed'}
    if is_requester and not is_super_admin:
        return {'problem': 'You cannot review your own request. Ask another manager'}
    note = (note or '').strip()
    if not approve:
        if not note:
            return {'problem': 'Give a reason for rejecting the request'}
        return {'status': PETTY_CASH_STATUS.REJECTED, 'amount': Decimal('0.00')}
    problem = amount_problem(approved_amount)
    if problem:
        return {'problem': problem}
    approved_amount = Decimal(approved_amount)
    if approved_amount > Decimal(requested):
        return {'problem': 'Cannot approve more than was requested'}
    if approved_amount < Decimal(requested) and not note:
        return {'problem': 'Give a reason for approving less than was requested'}
    return {'status': PETTY_CASH_STATUS.APPROVED, 'amount': approved_amount}


def expense_problem(balance, amount):
    problem = amount_problem(amount)
    if problem:
        return problem
    if Decimal(amount) > Decimal(balance):
        return f'Only Rs. {Decimal(balance):,.2f} is available, you entered Rs. {Decimal(amount):,.2f}'
    return None


def cancel_expense_problem(entry_type, already_reversed):
    if entry_type != PETTY_CASH_ENTRY.EXPENSE:
        return 'Only an expense can be cancelled'
    if already_reversed:
        return 'This expense was already cancelled'
    return None
