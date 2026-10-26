"""Plain-language labels and badge tones for statuses, ledger types and audit actions.

Ported from the client's StatusBadges.jsx, PurchaseStatusBadge.jsx, IssueStatusBadge.jsx,
stockLabels.js and auditLabels.js. No Django imports.
"""
import re

PURCHASE_STATUS_LABELS = {
    'ordered': {'tone': 'blue', 'label': 'Waiting for delivery'},
    'partly_received': {'tone': 'amber', 'label': 'Partly received'},
    'received': {'tone': 'green', 'label': 'Received'},
    'cancelled': {'tone': 'gray', 'label': 'Cancelled'},
}

ISSUE_STATUS_LABELS = {
    'issued': {'tone': 'green', 'label': 'Issued'},
    'cancelled': {'tone': 'gray', 'label': 'Cancelled'},
}

REQUEST_STATUS_LABELS = {
    'submitted': {'tone': 'blue', 'label': 'Waiting for review'},
    'approved': {'tone': 'green', 'label': 'Approved'},
    'partly_approved': {'tone': 'amber', 'label': 'Partly approved'},
    'rejected': {'tone': 'red', 'label': 'Rejected'},
    'completed': {'tone': 'green', 'label': 'Completed'},
    'cancelled': {'tone': 'gray', 'label': 'Cancelled'},
}

DISPATCH_STATUS_LABELS = {
    'in_transit': {'tone': 'blue', 'label': 'On the way'},
    'received': {'tone': 'green', 'label': 'Received'},
    'received_with_differences': {'tone': 'amber', 'label': 'Received with differences'},
    'closed': {'tone': 'gray', 'label': 'Closed'},
}

PETTY_CASH_STATUS_LABELS = {
    'submitted': {'tone': 'blue', 'label': 'Waiting for approval'},
    'approved': {'tone': 'green', 'label': 'Approved'},
    'rejected': {'tone': 'red', 'label': 'Rejected'},
    'cancelled': {'tone': 'gray', 'label': 'Cancelled'},
}

PETTY_CASH_ENTRY_LABELS = {
    'top_up': {'tone': 'green', 'label': 'Cash received'},
    'expense': {'tone': 'amber', 'label': 'Spent'},
    'reversal': {'tone': 'gray', 'label': 'Reversal'},
}

STATUS_LABELS = {
    'petty_cash': PETTY_CASH_STATUS_LABELS,
    'petty_entry': PETTY_CASH_ENTRY_LABELS,
    'purchase': PURCHASE_STATUS_LABELS,
    'issue': ISSUE_STATUS_LABELS,
    'request': REQUEST_STATUS_LABELS,
    'dispatch': DISPATCH_STATUS_LABELS,
}

REASON_LABELS = {
    'count_difference': 'Count difference',
    'damaged': 'Damaged',
    'expired': 'Expired',
    'found': 'Found',
    'other': 'Other',
}

# Which reasons make sense when adding or removing (the server enforces the same rule).
REASONS_FOR = {
    'add': ['count_difference', 'found', 'other'],
    'remove': ['count_difference', 'damaged', 'expired', 'other'],
}

MOVEMENT_TYPES = {
    'purchase_receipt': {'label': 'Purchase received', 'tone': 'green'},
    'office_issue': {'label': 'Issued to staff', 'tone': 'amber'},
    'adjustment': {'label': 'Correction', 'tone': 'blue'},
    'reversal': {'label': 'Reversal', 'tone': 'gray'},
    'dispatch_out': {'label': 'Sent to branch', 'tone': 'amber'},
    'branch_receipt': {'label': 'Received from main office', 'tone': 'green'},
}

ACTION_LABELS = {
    'auth.login': 'Signed in',
    'auth.change_password': 'Changed own password',
    'auth.locked': 'Account locked after failed sign-ins',
    'user.create': 'Added a user',
    'user.update': 'Edited a user',
    'user.disable': 'Disabled a user',
    'user.enable': 'Enabled a user',
    'user.reset_password': 'Reset a user’s password',
    'role.create': 'Added a role',
    'role.update': 'Edited a role',
    'role.delete': 'Deleted a role',
    'branch.create': 'Added a branch',
    'branch.update': 'Edited a branch',
    'branch.deactivate': 'Deactivated a branch',
    'branch.delete': 'Deleted a branch',
    'settings.update': 'Changed settings',
    'audit.clear_range': 'Cleared audit entries',
    'category.create': 'Added a category',
    'category.update': 'Edited a category',
    'category.delete': 'Deleted a category',
    'item.create': 'Added an item',
    'item.update': 'Edited an item',
    'item.deactivate': 'Deactivated an item',
    'item.delete': 'Deleted an item',
    'supplier.create': 'Added a supplier',
    'supplier.update': 'Edited a supplier',
    'supplier.deactivate': 'Deactivated a supplier',
    'supplier.delete': 'Deleted a supplier',
    'purchase.create': 'Recorded a purchase',
    'purchase.update': 'Edited a purchase',
    'purchase.cancel': 'Cancelled a purchase',
    'purchase.receive': 'Received a purchase into stock',
    'issue.create': 'Issued items to staff',
    'issue.cancel': 'Cancelled an issue',
    'stock.adjust': 'Corrected stock',
    'request.create': 'Raised a request',
    'request.cancel': 'Cancelled a request',
    'request.review': 'Reviewed a request',
    'dispatch.create': 'Sent a dispatch',
    'dispatch.receive': 'Confirmed a delivery',
    'dispatch.close': 'Closed a dispatch',
    'stock.retention_cleanup': 'Removed old movement details',
    'petty_cash.create': 'Requested petty cash',
    'petty_cash.cancel': 'Cancelled a petty cash request',
    'petty_cash.review': 'Reviewed a petty cash request',
    'petty_cash.expense': 'Recorded a petty cash expense',
    'petty_cash.cancel_expense': 'Cancelled a petty cash expense',
    'petty_cash.set_low_level': 'Changed the low petty cash level',
}

AREA_LABELS = {
    'auth': 'Sign-in', 'user': 'Users', 'role': 'Roles', 'branch': 'Branches', 'settings': 'Settings',
    'audit': 'Audit log', 'category': 'Categories', 'item': 'Items', 'supplier': 'Suppliers',
    'purchase': 'Purchases', 'issue': 'Office issues', 'stock': 'Stock', 'request': 'Requests',
    'dispatch': 'Dispatches', 'petty_cash': 'Petty cash',
}

_RED = re.compile(r'\.(delete|cancel|cancel_expense|deactivate|disable|clear_range|retention_cleanup)$')
_GREEN = re.compile(r'\.(create|receive|enable)$')
_AMBER = re.compile(r'^(auth|settings|user\.reset)')


def action_label(code):
    return ACTION_LABELS.get(code, code)


def area_of(code):
    return str(code).split('.')[0]


def action_tone(code):
    """Removals and cancellations stand out."""
    if _RED.search(code):
        return 'red'
    if _GREEN.search(code):
        return 'green'
    if _AMBER.search(code):
        return 'amber'
    return 'blue'
