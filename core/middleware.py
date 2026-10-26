import logging

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from core.constants import BRANCH_TYPES
from core.permissions import effective_permissions, is_branch_side

log = logging.getLogger(__name__)
_roles_ready = False


def _ensure_default_roles_once():
    """Creates the default roles the first time the app handles a request after the database exists.
    A failed attempt (e.g. migrations not run yet) is retried on the next request."""
    global _roles_ready
    if _roles_ready:
        return
    try:
        from accounts.roles import ensure_default_roles
        if ensure_default_roles():
            log.info('Created the default roles (Stock Officer, Viewer, Branch User)')
        _roles_ready = True
    except Exception:  # noqa: BLE001
        log.debug('Default roles not ready yet', exc_info=True)


class CurrentUserMiddleware:
    """Per request: default roles exist, the signed-in account is still allowed in, and the user's
    effective permissions are worked out once (request.perms)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _ensure_default_roles_once()
        request.perms = []
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            if not user.active:
                logout(request)
                messages.error(request, 'This account is not active')
                return redirect('accounts:login')
            # Fail closed if a branch-side account is misassigned to the Main Office record.
            if is_branch_side(user) and user.branch.type != BRANCH_TYPES.BRANCH:
                logout(request)
                resp = TemplateResponse(request, '403.html', {'message': 'This branch account must be assigned to a branch'}, status=403)
                resp.render()
                return resp
            request.perms = effective_permissions(user)
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Service errors that a view lets through become the right page instead of a server error."""
        from core.errors import Forbidden, NotFound, ServiceError, Unauthorized
        if not isinstance(exception, ServiceError):
            return None
        from core import views as core_views
        if isinstance(exception, NotFound):
            return core_views.not_found(request)
        if isinstance(exception, Forbidden):
            return core_views.permission_denied(request, exception)
        if isinstance(exception, Unauthorized):
            return redirect('accounts:login')
        messages.error(request, exception.message)
        from django.utils.http import url_has_allowed_host_and_scheme
        back = request.META.get('HTTP_REFERER', '')
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(back)
        return redirect('core:dashboard')


class RequestSettingCacheMiddleware:
    """Lets Setting.get() reuse one database read for the duration of a single request (see core.models.Setting.get)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.models import _SETTING_CACHE
        token = _SETTING_CACHE.set({})
        try:
            return self.get_response(request)
        finally:
            _SETTING_CACHE.reset(token)


class DatabaseUnavailableMiddleware:
    """A lost database connection becomes a friendly 503 page instead of a crash."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from django.db import InterfaceError, OperationalError
        if isinstance(exception, (OperationalError, InterfaceError)):
            log.warning('Database unavailable: %s', exception.__class__.__name__)  # never log the message: may hold host details
            from django.db import connections
            connections.close_all()
            from django.http import HttpResponse
            return HttpResponse('<h1>Connection lost</h1><p>The database cannot be reached. Reconnecting automatically&hellip;</p>',
                                status=503, headers={'X-Office-Stock': 'db-unavailable', 'Retry-After': '10'})
        return None


class ContentSecurityPolicyMiddleware:
    """Apply the app's restrictive CSP to pages and downloads."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if 'Content-Security-Policy' not in response:
            from django.conf import settings
            response['Content-Security-Policy'] = settings.CSP_POLICY
        return response
