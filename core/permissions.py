"""Who may do what.

Ported from server/src/config/permissions.js and server/src/services/permissionRules.js
(plus the navigation/feature tables that lived in client/src/utils/permissions.js).
Pure Python, no Django imports, so it can be unit-tested directly.

A "role definition" is a dict {key, name, side, permissions, description, builtIn?} taken
from the Role table (or the built-in Super Admin). `user.role_def` carries it.
"""
from .constants import ROLES

# Every feature the Super Admin can tick for a user. Keep the keys in sync with FEATURES below.
STAFF_PERMISSIONS = (
    'items.view', 'items.manage',
    'suppliers.view', 'suppliers.manage',
    'purchases.view', 'purchases.manage', 'purchases.receive',
    'issues.view', 'issues.manage',
    'stock.view', 'stock.adjust',
    'reports.view',
    'requests.review',
    'dispatches.manage',
    'petty_cash.view', 'petty_cash.approve', 'petty_cash.configure',
)

# Branch-side features: only for branch users, always limited to their own branch.
BRANCH_PERMISSIONS = ('requests.create', 'dispatches.receive')

# Works for either side, always limited to the user's own branch (the main office counts as a branch).
SHARED_PERMISSIONS = ('petty_cash.request',)

ALL_PERMISSIONS = STAFF_PERMISSIONS + BRANCH_PERMISSIONS + SHARED_PERMISSIONS

# Ticking the key needs the listed permissions, so they are added automatically.
IMPLIES = {
    'items.manage': ['items.view'],
    'suppliers.manage': ['suppliers.view'],
    'purchases.manage': ['purchases.view'],
    'purchases.receive': ['purchases.view'],
    'issues.manage': ['issues.view'],
    'stock.adjust': ['stock.view'],
    'petty_cash.approve': ['petty_cash.view'],
    'petty_cash.configure': ['petty_cash.view'],
}


class SIDES:
    MAIN = 'main'
    BRANCH = 'branch'


SIDE_LABELS = {SIDES.MAIN: 'Main office', SIDES.BRANCH: 'Branch'}

# Roles created once, the first time the system starts. After that they are ordinary roles
# that the Super Admin can edit or delete. Never re-created once deleted.
DEFAULT_ROLES = (
    {
        'key': ROLES.STOCK_OFFICER, 'name': 'Stock Officer', 'side': SIDES.MAIN,
        'description': 'Records stock, handles requests and dispatches',
        'permissions': [x for x in STAFF_PERMISSIONS if x not in ('petty_cash.approve', 'petty_cash.configure')]
                       + list(SHARED_PERMISSIONS),
    },
    {
        'key': ROLES.VIEWER, 'name': 'Viewer / Approver', 'side': SIDES.MAIN,
        'description': 'Read-only access to reports and dashboards',
        'permissions': ['items.view', 'suppliers.view', 'purchases.view', 'issues.view', 'stock.view', 'reports.view'],
    },
    {
        'key': ROLES.BRANCH_USER, 'name': 'Branch User', 'side': SIDES.BRANCH,
        'description': 'Requests items and confirms receipts for their branch',
        'permissions': list(BRANCH_PERMISSIONS) + list(SHARED_PERMISSIONS),
    },
)

# Built in: always exists, always has everything, cannot be edited or deleted.
SUPER_ADMIN_ROLE = {
    'key': ROLES.SUPER_ADMIN, 'name': 'Super Admin', 'side': SIDES.MAIN, 'builtIn': True,
    'description': 'Full access, including users, roles, branches and settings',
    'permissions': list(ALL_PERMISSIONS),
}

# The tick boxes on the role and user forms (labels and ordering only; the keys above are the truth).
FEATURES = (
    {'label': 'Items & categories', 'group': 'staff', 'hint': 'The item list and stock levels',
     'perms': (('items.view', 'View'), ('items.manage', 'Add, edit, delete'))},
    {'label': 'Suppliers', 'group': 'staff', 'hint': 'Who you buy from',
     'perms': (('suppliers.view', 'View'), ('suppliers.manage', 'Add, edit, delete'))},
    {'label': 'Purchases', 'group': 'staff', 'hint': 'What was bought and received',
     'perms': (('purchases.view', 'View'), ('purchases.manage', 'Record, edit, cancel'), ('purchases.receive', 'Receive into stock'))},
    {'label': 'Office issues', 'group': 'staff', 'hint': 'Items handed to office staff',
     'perms': (('issues.view', 'View'), ('issues.manage', 'Issue items'))},
    {'label': 'Stock & movements', 'group': 'staff', 'hint': 'Balances and every movement',
     'perms': (('stock.view', 'View'), ('stock.adjust', 'Correct stock'))},
    {'label': 'Reports', 'group': 'staff', 'hint': 'Purchases, usage and balances',
     'perms': (('reports.view', 'View'),)},
    {'label': 'Branch requests', 'group': 'staff', 'hint': 'Requests sent by branches',
     'perms': (('requests.review', 'Review and approve'),)},
    {'label': 'Dispatches', 'group': 'staff', 'hint': 'Items sent to branches',
     'perms': (('dispatches.manage', 'Prepare and send'),)},
    {'label': 'Petty cash', 'group': 'staff', 'hint': 'Cash held by the main office and each branch',
     'perms': (('petty_cash.view', 'View all branches'), ('petty_cash.approve', 'Approve requests'),
               ('petty_cash.configure', 'Set the low level'))},
    {'label': 'Requests', 'group': 'branch', 'hint': 'Asking the main office for items',
     'perms': (('requests.create', 'Raise requests'),)},
    {'label': 'Deliveries', 'group': 'branch', 'hint': 'Items arriving at the branch',
     'perms': (('dispatches.receive', 'Confirm receipts'),)},
    {'label': 'Own petty cash', 'group': 'shared', 'hint': 'Cash held by the user’s own branch (or the main office)',
     'perms': (('petty_cash.request', 'Request cash, record spending'),)},
)

# Single place that decides who sees which menu entry.
#   perms:  any one of these shows the entry
#   roles:  fixed to those roles (admin screens)
#   branch_side: hidden when the branch module is switched off
NAV_ITEMS = (
    {'url': 'core:dashboard', 'match': '/', 'exact': True, 'label': 'Dashboard', 'icon': 'home'},
    {'url': 'catalog:item_list', 'match': '/items/', 'label': 'Items', 'icon': 'box', 'perms': ('items.view',)},
    {'url': 'catalog:supplier_list', 'match': '/suppliers/', 'label': 'Suppliers', 'icon': 'store', 'perms': ('suppliers.view',)},
    {'url': 'inventory:purchase_list', 'match': '/purchases/', 'label': 'Purchases', 'icon': 'cart', 'perms': ('purchases.view',)},
    {'url': 'inventory:issue_list', 'match': '/office-issues/', 'label': 'Office Issues', 'icon': 'hand', 'perms': ('issues.view',)},
    {'url': 'branchops:request_list', 'match': '/requests/', 'label': 'Requests', 'icon': 'inbox',
     'perms': ('requests.create', 'requests.review'), 'branch_side': True},
    {'url': 'branchops:dispatch_list', 'match': '/dispatches/', 'label': 'Dispatches', 'icon': 'truck',
     'perms': ('dispatches.manage', 'dispatches.receive'), 'branch_side': True},
    {'url': 'pettycash:overview', 'match': '/petty-cash/', 'label': 'Petty Cash', 'icon': 'wallet',
     'perms': ('petty_cash.view', 'petty_cash.request', 'petty_cash.approve', 'petty_cash.configure')},
    {'url': 'inventory:stock', 'match': '/stock/', 'label': 'Stock & Movements', 'icon': 'list', 'perms': ('stock.view',)},
    {'url': 'reports:index', 'match': '/reports/', 'label': 'Reports', 'icon': 'chart', 'perms': ('reports.view',)},
    {'url': 'core:audit', 'match': '/audit/', 'label': 'Audit Log', 'icon': 'clock', 'roles': (ROLES.SUPER_ADMIN,)},
    {'url': 'accounts:branch_list', 'match': '/branches/', 'label': 'Branches', 'icon': 'building', 'roles': (ROLES.SUPER_ADMIN,)},
    {'url': 'accounts:user_list', 'match': '/users/', 'label': 'Users', 'icon': 'users', 'roles': (ROLES.SUPER_ADMIN,)},
    {'url': 'accounts:role_list', 'match': '/roles/', 'label': 'Roles', 'icon': 'shield', 'roles': (ROLES.SUPER_ADMIN,)},
    {'url': 'core:settings', 'match': '/settings/', 'label': 'Settings', 'icon': 'cog', 'roles': (ROLES.SUPER_ADMIN,)},
)


# --------------------------------------------------------------------------------------
# Rules (user = any object with .role, .permissions (None or list) and .role_def (dict|None))
# --------------------------------------------------------------------------------------

def side_of(user, role_def=None):
    role_def = role_def if role_def is not None else getattr(user, 'role_def', None)
    return (role_def or {}).get('side') or SIDES.MAIN


def is_branch_side(user, role_def=None):
    return side_of(user, role_def) == SIDES.BRANCH


def effective_permissions(user, role_def=None):
    """The permissions a user really has. Super Admin always has everything. Anyone else has the
    ticks saved on their account or, for accounts with none saved, their role's typical set."""
    if user.role == ROLES.SUPER_ADMIN:
        return list(ALL_PERMISSIONS)
    if isinstance(user.permissions, (list, tuple)):
        return list(user.permissions)
    role_def = role_def if role_def is not None else getattr(user, 'role_def', None)
    return list((role_def or {}).get('permissions') or [])


def has_any(user, perms):
    have = effective_permissions(user)
    return any(p in have for p in perms)


def normalize_permissions(items):
    """Drops duplicates and unknown keys and adds what a ticked feature depends on."""
    chosen = {p for p in items if p in ALL_PERMISSIONS}
    for p in list(chosen):
        chosen.update(IMPLIES.get(p, []))
    return [p for p in ALL_PERMISSIONS if p in chosen]  # stable order


def can_access_branch(user, record_branch_id):
    """A branch-side user works with their own branch's records only; main-office users see everything.
    Records without a branch (older data) belong to the main office, so a branch user cannot reach them."""
    if not is_branch_side(user):
        return True
    if not record_branch_id:
        return False
    return str(record_branch_id) == str(user.branch_id)


UNSET = object()


def resolve_permissions(role_def, requested=UNSET, current=None, role_changed=False):
    """What to store when a user is created or edited.

    requested:    ticks sent by the form (UNSET when not sent)
    current:      what is saved now (None for a new or older account)
    role_changed: True when an edit changes the role (the old ticks may not fit the new role)
    Returns the permission list to store; Super Admin stores None because it always has everything.
    """
    if role_def['key'] == ROLES.SUPER_ADMIN:
        return None
    if requested is not UNSET and requested is not None:
        base = requested
    elif role_changed or not isinstance(current, (list, tuple)):
        base = role_def['permissions']
    else:
        base = current
    return normalize_permissions(base)


def visible_nav(user, permissions, branch_module_enabled):
    """The menu entries this user sees."""
    out = []
    for n in NAV_ITEMS:
        if n.get('branch_side') and not branch_module_enabled:
            continue
        if n.get('roles'):
            if user.role not in n['roles']:
                continue
        elif n.get('perms'):
            if not any(p in permissions for p in n['perms']):
                continue
        out.append(n)
    return out
