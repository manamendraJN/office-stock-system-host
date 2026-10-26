from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from core.constants import ROLES
from core.models import Setting
from core.permissions import has_any


def permission_required(*perms):
    """Signed in, and holding any one of these permissions (Super Admin always passes)."""
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not has_any(request.user, perms):
                raise PermissionDenied('You do not have permission to do this')
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def role_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied('You do not have permission to do this')
            return view(request, *args, **kwargs)
        return wrapper
    return deco


super_admin_required = role_required(ROLES.SUPER_ADMIN)


def branch_module_required(view):
    """Guards every branch-side screen (requests, dispatches). When the Super Admin has the branch
    module switched off, these are refused."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not Setting.get().branch_module_enabled:
            raise PermissionDenied('The branch module is switched off')
        return view(request, *args, **kwargs)
    return wrapper
