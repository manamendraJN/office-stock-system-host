"""Pure business rules for the admin area (ported from adminRules.js).

Each returns an error message (string) or None. Kept free of database calls so they can be
tested directly; services gather the facts.
"""
from core.constants import ROLES, BRANCH_TYPES


def last_admin_problem(*, role, active, change_role=None, change_active=None, other_active_admins):
    """The company must always keep at least one active Super Admin, or nobody can manage users."""
    is_active_admin = role == ROLES.SUPER_ADMIN and active
    if not is_active_admin:
        return None
    demoted = change_role is not None and change_role != ROLES.SUPER_ADMIN
    disabled = change_active is False
    if (demoted or disabled) and other_active_admins == 0:
        return 'This is the only active Super Admin. Create another Super Admin first'
    return None


def main_branch_problem(*, branch_type, change_active=None, change_type=None):
    """The main office is where all stock is held; it cannot be switched off or turned into a branch."""
    if branch_type != BRANCH_TYPES.MAIN:
        return None
    if change_active is False:
        return 'The main office cannot be deactivated'
    if change_type is not None and change_type != BRANCH_TYPES.MAIN:
        return 'The main office cannot be changed into a branch'
    return None


def second_main_branch_problem(*, wants_type, existing_main_id, branch_id=None):
    """Only one main office may exist."""
    if wants_type != BRANCH_TYPES.MAIN:
        return None
    if existing_main_id and str(existing_main_id) != str(branch_id):
        return 'A main office already exists'
    return None


def branch_module_off_problem(*, currently_on, wants_on, open_requests, open_dispatches):
    """Switching the branch module off while work is in flight would strand stock in transit."""
    if not currently_on or wants_on is not False:
        return None
    if open_requests == 0 and open_dispatches == 0:
        return None
    parts = []
    if open_requests:
        parts.append(f"{open_requests} open request{'' if open_requests == 1 else 's'}")
    if open_dispatches:
        parts.append(f"{open_dispatches} dispatch{'' if open_dispatches == 1 else 'es'} not yet closed")
    return f"Cannot switch the branch module off while work is still open: {' and '.join(parts)}. Finish or close them first"


def user_audit_action(*, password, was_active, change_active=None):
    """Which audit entry an edit to a user should leave. Turning an account on or off and resetting
    a password matter most, so they get their own names instead of hiding inside "edited a user"."""
    if password:
        return 'user.reset_password'
    if change_active is False and was_active:
        return 'user.disable'
    if change_active is True and not was_active:
        return 'user.enable'
    return 'user.update'
