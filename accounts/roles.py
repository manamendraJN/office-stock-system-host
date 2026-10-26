"""Role lookups and the first-run default roles."""
from django.db import transaction

from accounts.models import Role
from core.models import Setting
from core.permissions import DEFAULT_ROLES, SUPER_ADMIN_ROLE


def ensure_default_roles():
    """Creates Stock Officer, Viewer and Branch User the first time only. The flag lives in Settings,
    so a role the Super Admin deletes later is never brought back. Returns True if it created them."""
    settings = Setting.get()
    if settings.default_roles_seeded:
        return False
    with transaction.atomic():
        for d in DEFAULT_ROLES:
            Role.objects.get_or_create(key=d['key'], defaults={
                'name': d['name'], 'side': d['side'], 'description': d['description'],
                'permissions': list(d['permissions']),
            })
        Setting.objects.filter(key='app').update(default_roles_seeded=True)
    return True


def find_role_def(key):
    if key == SUPER_ADMIN_ROLE['key']:
        return SUPER_ADMIN_ROLE
    r = Role.objects.filter(key=key).first()
    return r.as_def() if r else None


def all_role_defs():
    """Built-in Super Admin first, then stored roles by name."""
    return [SUPER_ADMIN_ROLE] + [r.as_def() | {'id': r.pk} for r in Role.objects.all()]
