"""Sign-in, passwords, users, roles and branches (ported from the auth/user/role/branch controllers)."""
from datetime import timedelta

from django.contrib.auth import login as django_login
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from accounts.models import Branch, Role, User
from accounts.roles import find_role_def
from core.constants import BRANCH_TYPES, DISPATCH_STATUS, REQUEST_STATUS, ROLES
from core.errors import BadRequest, Conflict, Forbidden, NotFound, ServiceError, Unauthorized
from core.models import Setting
from core.permissions import SIDES, SUPER_ADMIN_ROLE, UNSET, effective_permissions, resolve_permissions
from core.rules import admin_rules, role_rules
from core.services.audit import log_audit

MAX_FAILED = 5
LOCK_MINUTES = 15


# ---------------------------------------------------------------- sign in
def sign_in(request, email, password):
    """Checks the credentials with the original lockout rules: 5 wrong passwords lock the account for 15 minutes."""
    email = (email or '').strip().lower()
    user = User.objects.select_related('branch').filter(email=email).first()

    if user and user.is_locked:
        raise Forbidden('Too many failed attempts. Try again in a few minutes')

    if user is None or not user.active or not user.check_password(password or ''):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until = timezone.now() + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
                # No one is signed in here, so name the locked account as the actor.
                log_audit(request, 'auth.locked', 'User', user.pk, new_value={'minutes': LOCK_MINUTES}, actor=user)
            user.save(update_fields=['failed_logins', 'locked_until'])
        else:
            # Burn the same time as a real check, so response time does not reveal which emails exist.
            User().set_password(password or '')
        raise Unauthorized('Incorrect email or password')

    user.failed_logins = 0
    user.locked_until = None
    user.save(update_fields=['failed_logins', 'locked_until'])
    user.backend = 'accounts.backends.EmailBackend'
    django_login(request, user)
    log_audit(request, 'auth.login', 'User', user.pk, actor=user)
    return user


def change_password(request, current, new):
    user = request.user
    if not user.check_password(current):
        raise BadRequest('Your current password is not correct', {'current_password': 'Your current password is not correct'})
    user.set_password(new)
    user.save(update_fields=['password'])
    log_audit(request, 'auth.change_password', 'User', user.pk)
    return user


# ---------------------------------------------------------------- users
def _require_role(key):
    role_def = find_role_def(key)
    if not role_def:
        raise BadRequest('Choose a valid role', {'role': 'Choose a valid role'})
    return role_def


def _assert_branch_usable(branch, role_def, allow_inactive=False):
    if branch is None:
        raise BadRequest('Choose a valid branch', {'branch': 'Choose a valid branch'})
    if not allow_inactive and not branch.active:
        raise BadRequest('That branch is inactive. Choose an active branch', {'branch': 'That branch is inactive'})
    if (role_def or {}).get('side') == SIDES.BRANCH and branch.type != BRANCH_TYPES.BRANCH:
        raise BadRequest('Branch-side users must be assigned to a branch, not the main office',
                         {'branch': 'Choose a branch, not the main office'})


def create_user(request, *, name, email, password, role, branch, requested_permissions):
    role_def = _require_role(role)
    _assert_branch_usable(branch, role_def)
    permissions = resolve_permissions(role_def, requested=requested_permissions)
    try:
        with transaction.atomic():
            user = User.objects.create_user(email=email, password=password, name=name, role=role, branch=branch,
                                            permissions=permissions)
    except IntegrityError:
        raise Conflict('That email is already in use', {'email': 'That email is already in use'})
    log_audit(request, 'user.create', 'User', user.pk,
              new_value={'name': user.name, 'email': user.email, 'role': user.role, 'branch': user.branch_id,
                         'permissions': user.permissions})
    return user


def update_user(request, user, *, changes=None, requested_permissions=UNSET, password=None):
    """changes: any of name, email, role, branch (Branch), active. Only the keys present are changed."""
    changes = dict(changes or {})
    me = request.user
    is_self = user.pk == me.pk
    new_active = changes.get('active')
    new_role = changes.get('role')

    if is_self and new_active is False:
        raise BadRequest('You cannot disable your own account')
    if is_self and new_role is not None and new_role != user.role:
        raise BadRequest('You cannot change your own role. Ask another Super Admin')

    other_admins = User.objects.filter(role=ROLES.SUPER_ADMIN, active=True).exclude(pk=user.pk).count()
    problem = admin_rules.last_admin_problem(role=user.role, active=user.active, change_role=new_role,
                                             change_active=new_active, other_active_admins=other_admins)
    if problem:
        raise Conflict(problem)

    role_changed = new_role is not None and new_role != user.role
    target_role_def = _require_role(new_role) if role_changed else _require_role(user.role)
    new_branch = changes.get('branch')
    branch_changed = new_branch is not None and new_branch.pk != user.branch_id
    activating_branch_role = role_changed and target_role_def['side'] == SIDES.BRANCH
    _assert_branch_usable(new_branch or user.branch, target_role_def,
                          allow_inactive=not branch_changed and not activating_branch_role)

    was_active = user.active
    old = {'name': user.name, 'email': user.email, 'role': user.role, 'branch': user.branch_id, 'active': user.active,
           'permissions': user.permissions}
    if requested_permissions is not UNSET or role_changed:
        user.permissions = resolve_permissions(target_role_def, requested=requested_permissions,
                                               current=user.permissions, role_changed=role_changed)
    for key in ('name', 'email', 'role', 'branch', 'active'):
        if key in changes and changes[key] is not None:
            setattr(user, key, changes[key])
    if password:
        user.set_password(password)
        # A reset by the admin also clears any lock from failed sign-in attempts.
        user.failed_logins = 0
        user.locked_until = None
    try:
        with transaction.atomic():
            user.save()
    except IntegrityError:
        raise Conflict('That email is already in use', {'email': 'That email is already in use'})

    log_audit(request, admin_rules.user_audit_action(password=password, was_active=was_active, change_active=new_active),
              'User', user.pk, old_value=old,
              new_value={**{k: (v.pk if hasattr(v, 'pk') else v) for k, v in changes.items()},
                         'permissions': None if requested_permissions is UNSET else requested_permissions,
                         'password_changed': bool(password)})
    return user


# ---------------------------------------------------------------- roles
def role_user_counts():
    return {r['role']: r['n'] for r in User.objects.order_by().values('role').annotate(n=Count('pk'))}


def create_role(request, *, name, description, side, permissions):
    existing = list(Role.objects.values_list('key', 'name'))
    if role_rules.name_taken(name, [n for _, n in existing]):
        raise Conflict('A role with that name already exists', {'name': 'A role with that name already exists'})
    key = role_rules.unique_key(name, [k for k, _ in existing])
    try:
        with transaction.atomic():
            role = Role.objects.create(key=key, name=name, description=description or '', side=side,
                                       permissions=role_rules.resolve_role_permissions(permissions or []))
    except IntegrityError:
        raise Conflict('A role with that name already exists', {'name': 'A role with that name already exists'})
    log_audit(request, 'role.create', 'Role', role.pk, new_value={'name': name, 'side': side, 'permissions': role.permissions})
    return role


def get_stored_role(pk):
    if pk == SUPER_ADMIN_ROLE['key']:
        raise Conflict('Super Admin is built in and cannot be changed')
    role = Role.objects.filter(pk=pk).first() if str(pk).isdigit() else None
    if not role:
        raise NotFound('Role not found')
    return role


def update_role(request, role, *, name=None, description=None, side=None, permissions=None, apply_to_users=False):
    user_count = User.objects.filter(role=role.key).count()
    problem = role_rules.role_edit_problem(key=role.key, change_side=side, current_side=role.side, user_count=user_count)
    if problem:
        raise Conflict(problem)
    if name is not None:
        others = list(Role.objects.exclude(pk=role.pk).values_list('name', flat=True))
        if role_rules.name_taken(name, others):
            raise Conflict('A role with that name already exists', {'name': 'A role with that name already exists'})
    old = {'name': role.name, 'description': role.description, 'side': role.side, 'permissions': role.permissions}
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    if side is not None:
        role.side = side
    if permissions is not None:
        role.permissions = role_rules.resolve_role_permissions(permissions)
    users_updated = 0
    with transaction.atomic():
        role.save()
        # Users keep the ticks saved on their own account. Only when asked, overwrite them with the role's.
        if apply_to_users and user_count > 0:
            users_updated = User.objects.filter(role=role.key).update(permissions=role.permissions)
    log_audit(request, 'role.update', 'Role', role.pk, old_value=old,
              new_value={'name': name, 'description': description, 'side': side, 'permissions': permissions,
                         'apply_to_users': bool(apply_to_users), 'users_updated': users_updated})
    return role, users_updated


def delete_role(request, role):
    problem = role_rules.role_delete_problem(key=role.key, user_count=User.objects.filter(role=role.key).count())
    if problem:
        raise Conflict(problem)
    snap = role.as_def()
    pk = role.pk
    role.delete()
    log_audit(request, 'role.delete', 'Role', pk, old_value=snap)


# ---------------------------------------------------------------- branches
def create_branch(request, *, name, code, type=BRANCH_TYPES.BRANCH, address='', phone=''):
    main = Branch.objects.filter(type=BRANCH_TYPES.MAIN).first()
    problem = admin_rules.second_main_branch_problem(wants_type=type, existing_main_id=main.pk if main else None)
    if problem:
        raise Conflict(problem)
    try:
        with transaction.atomic():
            branch = Branch.objects.create(name=name, code=code, type=type, address=address or '', phone=phone or '')
    except IntegrityError:
        raise Conflict('That code is already in use', {'code': 'That code is already in use'})
    log_audit(request, 'branch.create', 'Branch', branch.pk,
              new_value={'name': name, 'code': branch.code, 'type': type, 'address': address, 'phone': phone})
    return branch


def update_branch(request, branch, changes):
    """changes: any of name, code, type, address, phone, active."""
    main = Branch.objects.filter(type=BRANCH_TYPES.MAIN).first()
    problem = (admin_rules.main_branch_problem(branch_type=branch.type, change_active=changes.get('active'),
                                               change_type=changes.get('type'))
               or admin_rules.second_main_branch_problem(wants_type=changes.get('type'),
                                                         existing_main_id=main.pk if main else None, branch_id=branch.pk))
    if problem:
        raise Conflict(problem)
    old = {k: getattr(branch, k) for k in ('name', 'code', 'type', 'address', 'phone', 'active')}
    for k, v in changes.items():
        setattr(branch, k, v)
    try:
        with transaction.atomic():
            branch.save()
    except IntegrityError:
        raise Conflict('That code is already in use', {'code': 'That code is already in use'})
    log_audit(request, 'branch.update', 'Branch', branch.pk, old_value=old, new_value=changes)
    return branch


def delete_branch(request, branch):
    """A branch can only be deleted if it has no users or stock history (e.g. created by mistake).
    Otherwise it is deactivated, so past records and reports stay intact. Returns 'deleted' or 'deactivated'."""
    from inventory.models import StockLedger
    if branch.type == BRANCH_TYPES.MAIN:
        raise BadRequest('The main office cannot be deleted')
    if branch.users.exists() or StockLedger.objects.filter(branch=branch).exists() or _branch_has_documents(branch):
        branch.active = False
        branch.save(update_fields=['active', 'updated_at'])
        log_audit(request, 'branch.deactivate', 'Branch', branch.pk)
        return 'deactivated'
    snap = {'name': branch.name, 'code': branch.code}
    pk = branch.pk
    branch.delete()
    log_audit(request, 'branch.delete', 'Branch', pk, old_value=snap)
    return 'deleted'


def _branch_has_documents(branch):
    """Requests, dispatches, purchases and issues point at the branch with PROTECT, so check them too."""
    from branchops.models import Dispatch, Request
    from inventory.models import OfficeIssue, Purchase
    return (Request.objects.filter(branch=branch).exists() or Dispatch.objects.filter(destination=branch).exists()
            or Purchase.objects.filter(branch=branch).exists() or OfficeIssue.objects.filter(branch=branch).exists())


# ---------------------------------------------------------------- settings
def update_settings(request, *, branch_module_enabled=None, audit_logging_enabled=None, company_name=None):
    from branchops.models import Dispatch, Request
    settings = Setting.get()
    if branch_module_enabled is False and settings.branch_module_enabled:
        open_requests = Request.objects.filter(status__in=[REQUEST_STATUS.SUBMITTED, REQUEST_STATUS.APPROVED,
                                                           REQUEST_STATUS.PARTLY_APPROVED]).count()
        open_dispatches = Dispatch.objects.filter(status__in=[DISPATCH_STATUS.IN_TRANSIT,
                                                              DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES]).count()
        problem = admin_rules.branch_module_off_problem(currently_on=settings.branch_module_enabled, wants_on=False,
                                                        open_requests=open_requests, open_dispatches=open_dispatches)
        if problem:
            raise Conflict(problem)
    old = {'branch_module_enabled': settings.branch_module_enabled, 'audit_logging_enabled': settings.audit_logging_enabled,
           'company_name': settings.company_name}
    new = {}
    if branch_module_enabled is not None:
        settings.branch_module_enabled = branch_module_enabled
        new['branch_module_enabled'] = branch_module_enabled
    if audit_logging_enabled is not None:
        settings.audit_logging_enabled = audit_logging_enabled
        new['audit_logging_enabled'] = audit_logging_enabled
    if company_name is not None:
        settings.company_name = company_name
        new['company_name'] = company_name
    settings.save()
    # Turning logging off is itself always recorded, so there is a trace of who stopped it.
    log_audit(request, 'settings.update', 'Setting', settings.pk, old_value=old, new_value=new,
              force=old['audit_logging_enabled'] is not False and audit_logging_enabled is False)
    return settings
