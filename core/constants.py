"""Shared constants.

Ported from server/src/config/constants.js. Plain strings (not Enums) so they compare
directly with values stored in the database. No Django imports: this module is also used
by the pure business-rule modules, which are unit-tested without Django.
"""


class ROLES:
    SUPER_ADMIN = 'super_admin'
    STOCK_OFFICER = 'stock_officer'
    BRANCH_USER = 'branch_user'
    VIEWER = 'viewer'


class BRANCH_TYPES:
    MAIN = 'main'
    BRANCH = 'branch'


class REQUEST_STATUS:
    SUBMITTED = 'submitted'
    APPROVED = 'approved'
    PARTLY_APPROVED = 'partly_approved'
    REJECTED = 'rejected'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'


class DISPATCH_STATUS:
    IN_TRANSIT = 'in_transit'
    RECEIVED = 'received'
    RECEIVED_WITH_DIFFERENCES = 'received_with_differences'
    CLOSED = 'closed'


class PURCHASE_STATUS:
    ORDERED = 'ordered'
    PARTLY_RECEIVED = 'partly_received'
    RECEIVED = 'received'
    CANCELLED = 'cancelled'


class ISSUE_STATUS:
    ISSUED = 'issued'
    CANCELLED = 'cancelled'


class PETTY_CASH_STATUS:
    SUBMITTED = 'submitted'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'


class PETTY_CASH_ENTRY:
    TOP_UP = 'top_up'
    EXPENSE = 'expense'
    REVERSAL = 'reversal'


DEFAULT_PETTY_CASH_LOW_LEVEL = 2000


class LEDGER_TYPES:
    PURCHASE_RECEIPT = 'purchase_receipt'
    DISPATCH_OUT = 'dispatch_out'
    BRANCH_RECEIPT = 'branch_receipt'
    OFFICE_ISSUE = 'office_issue'
    ADJUSTMENT = 'adjustment'
    REVERSAL = 'reversal'
    OPENING_BALANCE = 'opening_balance'


ADJUSTMENT_REASONS = ['count_difference', 'damaged', 'expired', 'found', 'other']

SIDES_MAIN = 'main'
SIDES_BRANCH = 'branch'


def choices(cls):
    """(value, value) pairs for every public string attribute of a constants class."""
    return [(v, v) for k, v in vars(cls).items() if not k.startswith('_') and isinstance(v, str)]


def values(cls):
    return [v for k, v in vars(cls).items() if not k.startswith('_') and isinstance(v, str)]
