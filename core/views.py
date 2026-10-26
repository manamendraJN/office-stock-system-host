import json
import secrets
from datetime import datetime, time

from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts import services as account_services
from accounts.forms import SettingsCompanyForm
from accounts.models import User
from core.decorators import super_admin_required
from core.errors import ServiceError
from core.labels import AREA_LABELS, action_label, area_of
from core.models import AuditLog, Setting
from core.permissions import can_access_branch  # noqa: F401
from core.rules.report_rules import parse_range
from core.services.audit import log_audit
from core.services.dashboard import build_dashboard

PAGE_SIZE = 50


@login_required
def dashboard(request):
    data = build_dashboard(request.user)
    perms = request.perms
    stock_link = 'inventory:stock' if 'stock.view' in perms else 'catalog:item_list'
    tiles = []
    if 'low_stock' in data:
        ls = data['low_stock']
        tiles.append({'label': 'Items below minimum', 'value': ls['count'], 'url': stock_link,
                      'tone': 'bad' if ls['out_of_stock'] > 0 else ('warn' if ls['count'] > 0 else ''),
                      'note': f"{ls['out_of_stock']} out of stock" if ls['out_of_stock'] > 0
                      else ('All items are above their minimum' if ls['count'] == 0 else '')})
    if 'purchases' in data:
        p = data['purchases']
        tiles.append({'label': 'Purchases waiting for delivery', 'value': p['awaiting_delivery'], 'url': 'inventory:purchase_list'})
        tiles.append({'label': 'Spent this month', 'value': p['spent_this_month'], 'money': True, 'url': 'inventory:purchase_list',
                      'note': f"{p['count_this_month']} purchase{'' if p['count_this_month'] == 1 else 's'}, cancelled ones left out"})
    if 'issues' in data:
        i = data['issues']
        tiles.append({'label': 'Issued to staff this month', 'value': i['units_this_month'], 'url': 'inventory:issue_list',
                      'note': f"{i['count_this_month']} issue{'' if i['count_this_month'] == 1 else 's'}"})
    if 'petty_cash' in data:
        pc = data['petty_cash']
        if pc['all_branches']:
            tiles.append({'label': 'Places low on petty cash', 'value': pc['low_count'], 'url': 'pettycash:overview',
                          'tone': 'bad' if pc['low_count'] else '',
                          'note': f"Low means {pc['low_level']:,.2f} or less"})
            if 'petty_cash.approve' in perms:
                tiles.append({'label': 'Petty cash requests waiting', 'value': pc['waiting'], 'url': 'pettycash:request_list',
                              'tone': 'warn' if pc['waiting'] else ''})
        else:
            low = pc['low_count'] > 0
            tiles.append({'label': 'Your petty cash', 'value': pc['balance'], 'money': True, 'url': 'pettycash:overview',
                          'tone': 'bad' if low else '', 'note': 'Low, please request more' if low else ''})
    if 'requests' in data:
        r = data['requests']
        reviewer = 'requests.review' in perms
        tiles.append({'label': 'Requests waiting for review' if reviewer else 'Your requests waiting for review',
                      'value': r['waiting_for_review'], 'url': 'branchops:request_list',
                      'tone': 'warn' if reviewer and r['waiting_for_review'] > 0 else ''})
        if 'dispatches.manage' in perms:
            tiles.append({'label': 'Approved, ready to send', 'value': r['ready_to_send'], 'url': 'branchops:request_list'})
    if 'dispatches' in data:
        d = data['dispatches']
        receiver = 'dispatches.receive' in perms and 'dispatches.manage' not in perms
        tiles.append({'label': 'Deliveries on the way to you' if receiver else 'Dispatches in transit',
                      'value': d['in_transit'], 'url': 'branchops:dispatch_list'})
        if d['with_differences'] > 0:
            tiles.append({'label': 'Delivered with differences', 'value': d['with_differences'], 'url': 'branchops:dispatch_list',
                          'tone': 'warn', 'note': 'Damaged or missing goods to settle'})
    return render(request, 'core/dashboard.html', {
        'data': data, 'tiles': tiles, 'stock_link': stock_link, 'first_name': request.user.name.split(' ')[0],
        'has_content': bool(tiles) or 'recent_movements' in data, 'recent': data.get('recent_movements', [])})


# ------------------------------------------------------------------ settings
@super_admin_required
def settings_view(request):
    settings_obj = Setting.get()
    company_data = request.POST if request.POST.get('action') == 'company' else None
    company_form = SettingsCompanyForm(company_data, initial={'company_name': settings_obj.company_name})
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'audit_toggle':
                stop = settings_obj.audit_logging_enabled
                account_services.update_settings(request, audit_logging_enabled=not stop)
                messages.success(request, 'Audit logging stopped' if stop else 'Audit logging resumed')
            elif action == 'module_toggle':
                on = settings_obj.branch_module_enabled
                account_services.update_settings(request, branch_module_enabled=not on)
                messages.success(request, 'Branch module switched off' if on else 'Branch module switched on')
            elif action == 'company' and company_form.is_valid():
                account_services.update_settings(request, company_name=company_form.cleaned_data['company_name'])
                messages.success(request, 'Company name saved')
            else:
                if action != 'company':
                    messages.error(request, 'Unknown action')
                else:
                    return render(request, 'core/settings.html', {'s': settings_obj, 'company_form': company_form})
        except ServiceError as exc:
            messages.error(request, exc.message)
        return redirect('core:settings')
    return render(request, 'core/settings.html', {'s': settings_obj, 'company_form': company_form})


# ------------------------------------------------------------------ audit log
def _day_bounds(range_):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(range_['from'], time.min), tz) if range_.get('from') else None
    end = timezone.make_aware(datetime.combine(range_['to'], time.max), tz) if range_.get('to') else None
    return start, end


@super_admin_required
def audit_log(request):
    g = request.GET
    user_id, area, from_, to = g.get('user', ''), g.get('area', ''), g.get('from', ''), g.get('to', '')
    range_ = parse_range(from_, to)
    problem = range_.get('problem')
    qs = AuditLog.objects.select_related('user')
    if user_id.isdigit():
        qs = qs.filter(user_id=int(user_id))
    elif user_id:
        problem = problem or 'Choose a valid user'
    if area:
        qs = qs.filter(action__startswith=f'{area}.')
    start, end = _day_bounds(range_) if not problem else (None, None)
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    try:
        page_no = max(int(g.get('page', 1)), 1)
    except ValueError:
        page_no = 1
    paginator = Paginator(qs.order_by('-created_at', '-id'), PAGE_SIZE)
    page = paginator.get_page(page_no)

    actions = sorted(AuditLog.objects.values_list('action', flat=True).distinct())
    areas = sorted({area_of(a) for a in actions}, key=lambda a: AREA_LABELS.get(a, a).lower())
    users = User.objects.filter(pk__in=AuditLog.objects.exclude(user=None).values('user_id').distinct()).order_by('name')
    entries = []
    for e in page.object_list:
        has_vals = any(v not in (None, {}, []) for v in (e.old_value, e.new_value))
        entries.append({'e': e, 'has_values': has_vals,
                        'old': json.dumps(e.old_value, indent=2, default=str) if e.old_value is not None else None,
                        'new': json.dumps(e.new_value, indent=2, default=str) if e.new_value is not None else None})
    return render(request, 'core/audit.html', {
        'entries': entries, 'page': page.number, 'pages': paginator.num_pages, 'total': paginator.count,
        'users': users, 'areas': [(a, AREA_LABELS.get(a, a)) for a in areas],
        'f': {'user': user_id, 'area': area, 'from': from_, 'to': to}, 'problem': problem,
        'filters_on': any([user_id, area, from_, to]), 'logging_on': Setting.get().audit_logging_enabled})


@super_admin_required
@require_POST
def audit_clear(request):
    from_, to = request.POST.get('from', ''), request.POST.get('to', '')
    if not from_ or not to:
        messages.error(request, 'Choose both a start date and an end date to clear audit entries')
        return redirect('core:audit')
    range_ = parse_range(from_, to)
    if range_.get('problem'):
        messages.error(request, range_['problem'])
        return redirect('core:audit')
    start, end = _day_bounds(range_)
    deleted = AuditLog.clear_range(start, end)
    log_audit(request, 'audit.clear_range', 'AuditLog', '', new_value={'from': start, 'to': end, 'deleted_count': deleted})
    messages.success(request, f"{deleted} entr{'y' if deleted == 1 else 'ies'} cleared. The cleanup is recorded in the audit log when logging is on.")
    return redirect('core:audit')


# ------------------------------------------------------------------ health + scheduled cleanup
@require_GET
def health(request):
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
        db = 'connected'
    except Exception:  # noqa: BLE001
        db = 'disconnected'
    # 503 when the database is unreachable so load balancers can tell "up" from "usable".
    return JsonResponse({
        'app': 'office-stock', 'status': 'ok' if db == 'connected' else 'degraded', 'database': db,
        'time': timezone.now().isoformat()}, status=200 if db == 'connected' else 503)


@csrf_exempt  # The scheduled caller authenticates with a non-cookie bearer token.
@require_POST
def stock_ledger_retention(request):
    """Called by the scheduler (Authorization: Bearer <CRON_SECRET>). Replaces ledger rows older than 30 days
    with opening balances."""
    from inventory.services.retention import prune_old_stock_movements
    secret = dj_settings.CRON_SECRET
    sent = request.META.get('HTTP_AUTHORIZATION', '')
    if not secret or not secrets.compare_digest(sent, f'Bearer {secret}'):
        return JsonResponse({'message': 'Scheduled cleanup authorization failed'}, status=401)
    result = prune_old_stock_movements()
    if result['deleted_count'] > 0:
        log_audit(request, 'stock.retention_cleanup', 'StockLedger', '', new_value={
            'cutoff': result['cutoff'], 'deleted_count': result['deleted_count'], 'opening_balance_count': result['opening_balance_count']})
    return JsonResponse({'cutoff': result['cutoff'].isoformat(), 'deletedCount': result['deleted_count'],
                         'openingBalanceCount': result['opening_balance_count'], 'skipped': result['skipped']})


# ------------------------------------------------------------------ error pages
def permission_denied(request, exception=None):
    message = str(exception) if exception and str(exception) else 'You do not have permission to open this page.'
    return render(request, '403.html', {'message': message}, status=403)


def not_found(request, exception=None):
    return render(request, '404.html', status=404)
