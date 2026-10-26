"""Pure rules about roles (ported from roleRules.js). No database calls."""
import re

from core.permissions import SUPER_ADMIN_ROLE, normalize_permissions


def normalize_name(name):
    return re.sub(r'\s+', ' ', name.strip()).lower()


def slugify(name):
    """'Front Desk Clerk' -> 'front_desk_clerk'"""
    slug = re.sub(r'[^a-z0-9]+', '_', normalize_name(name))
    slug = slug.strip('_')[:40]
    return slug or 'role'


def unique_key(name, taken_keys):
    """First free key: front_desk, front_desk_2, front_desk_3 ..."""
    taken = set(taken_keys) | {SUPER_ADMIN_ROLE['key']}
    base = slugify(name)
    if base not in taken:
        return base
    n = 2
    while f'{base}_{n}' in taken:
        n += 1
    return f'{base}_{n}'


def name_taken(name, other_names):
    wanted = normalize_name(name)
    return any(normalize_name(n) == wanted for n in [*other_names, SUPER_ADMIN_ROLE['name']])


def resolve_role_permissions(permissions):
    """Ticks to store for a role: dependencies added, unknown keys dropped. Any role, main office or
    branch, may hold any feature; the side only decides whose stock its users see."""
    return normalize_permissions(permissions)


def _plural_users(count):
    return f"{count} user{' has' if count == 1 else 's have'}"


def role_edit_problem(*, key, built_in=False, change_side=None, current_side=None, user_count=0):
    if built_in or key == SUPER_ADMIN_ROLE['key']:
        return 'Super Admin is built in and cannot be changed'
    if change_side is not None and change_side != current_side and user_count > 0:
        return f'{_plural_users(user_count)} this role, so its side cannot be changed. Move them to another role first'
    return None


def role_delete_problem(*, key, built_in=False, user_count=0):
    if built_in or key == SUPER_ADMIN_ROLE['key']:
        return 'Super Admin is built in and cannot be deleted'
    if user_count > 0:
        return f'{_plural_users(user_count)} this role. Move them to another role before deleting it'
    return None
