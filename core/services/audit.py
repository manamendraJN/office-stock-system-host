"""Records who did what. Never raises: an audit failure must not break the user's action."""
import ipaddress
import logging

from django.conf import settings
from django.db import transaction

from core.models import AuditLog, Setting

log = logging.getLogger(__name__)

_REDACT = {'password', 'new_password', 'current_password', 'token'}


def _clean(value):
    """Plain JSON-safe copy with anything secret removed."""
    if isinstance(value, dict):
        return {str(k): ('[hidden]' if str(k).lower() in _REDACT else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def client_ip(request):
    """The caller's address, for the audit log and the sign-in throttle.

    Behind a cloud load balancer REMOTE_ADDR is the balancer, so every user would share one address (one
    shared sign-in throttle, wrong audit IPs). When TRUSTED_PROXY_COUNT = N > 0 we read X-Forwarded-For and
    take the Nth entry from the RIGHT: those are the entries appended by our own proxies, whereas anything
    further left can be forged by the client. Falls back to REMOTE_ADDR if the header is short or malformed.
    """
    if request is None:
        return ''
    remote = request.META.get('REMOTE_ADDR', '') or ''
    hops = getattr(settings, 'TRUSTED_PROXY_COUNT', 0)
    if hops <= 0:
        return remote
    forwarded = [p.strip() for p in (request.META.get('HTTP_X_FORWARDED_FOR', '') or '').split(',') if p.strip()]
    if len(forwarded) < hops:
        return remote
    candidate = forwarded[-hops]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return remote
    return candidate


def log_audit(request, action, record_type='', record_id='', old_value=None, new_value=None, force=False, actor=None):
    """`actor` names the user when nobody is signed in (e.g. an account locked out of signing in)."""
    try:
        if not force and not Setting.get().audit_logging_enabled:
            return
        user = actor or getattr(request, 'user', None)
        if user is not None and not getattr(user, 'pk', None):
            user = None
        with transaction.atomic():  # savepoint, so a failure cannot poison an outer transaction
            AuditLog.objects.create(
                user=user,
                action=action,
                record_type=record_type or '',
                record_id='' if record_id in (None, '') else str(record_id),
                old_value=_clean(old_value),
                new_value=_clean(new_value),
                ip=client_ip(request),
            )
    except Exception:  # noqa: BLE001 - by design
        log.exception('Audit log failed')
