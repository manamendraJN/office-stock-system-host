from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.models import Branch
from core.csvutil import to_csv
from core.decorators import permission_required
from core.models import Setting
from core.permissions import is_branch_side
from core.rules.report_rules import month_range, parse_range, quick_ranges
from inventory.services.stock import get_main_branch
from reports import services


def _int(value):
    return int(value) if str(value or '').isdigit() else None


@permission_required('reports.view')
def index(request):
    user = request.user
    g = request.GET
    branch_side = is_branch_side(user)
    module_on = Setting.get().branch_module_enabled
    tabs = {k: v for k, v in services.REPORTS.items() if module_on or not v.get('needs_branch_module')}
    rtype = g.get('type') if g.get('type') in tabs else 'balances'
    meta = tabs[rtype]
    today = timezone.localdate()

    # First visit: this month. Explicit empty boxes (the "All time" shortcut) mean no limit.
    if 'from' in g or 'to' in g:
        f, t = g.get('from', ''), g.get('to', '')
    else:
        f, t = month_range(today)[0].isoformat(), today.isoformat()
    rng = parse_range(f, t) if meta['dated'] else {'from': None, 'to': None}
    problem = rng.get('problem')
    own_branch = user.branch_id if branch_side else None
    opts = services.filter_options(own_branch)

    result, scope, error = None, '', problem
    if not problem:
        if rtype == 'balances':
            branch = user.branch if branch_side else (Branch.objects.filter(pk=_int(g.get('branch')), active=True).first()
                                                       if _int(g.get('branch')) else get_main_branch())
            if not branch:
                error = 'No main office exists. Run the seed command first' if not g.get('branch') else 'Choose a valid branch'
            else:
                result, scope = services.stock_report(branch, low_only=g.get('low') == '1'), branch.name
        elif rtype == 'purchases':
            result = services.purchases_report(rng, branch_id=own_branch, supplier_id=None if branch_side else _int(g.get('supplier')),
                                               by=g.get('by', 'supplier'))
            scope = user.branch.name if branch_side else 'All purchases'
        elif rtype == 'usage':
            result = services.usage_report_data(rng, branch_id=own_branch, department=g.get('department', ''), by=g.get('by', 'item'))
            scope = user.branch.name if branch_side else 'All issues'
        else:
            dest = own_branch if branch_side else _int(g.get('destination'))
            result = services.dispatches_report(rng, destination_id=dest)
            scope = user.branch.name if branch_side else 'All branches'

    if result is not None and g.get('format') == 'csv':
        resp = HttpResponse(to_csv(result['columns'], result['rows'], result['totals']), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="{rtype}-report-{today.isoformat()}.csv"'
        return resp

    if meta['dated']:
        period = (f'{rng["from"].strftime("%d %b %Y") if rng.get("from") else "The start"} to '
                  f'{rng["to"].strftime("%d %b %Y") if rng.get("to") else "today"}') if (f or t) else 'All time'
    else:
        period = 'Right now'
    columns = result['columns'] if result else []
    rows = [{'cells': [{'col': c, 'value': r.get(c['key'])} for c in columns]} for r in result['rows']] if result else []
    totals = result['totals'] if result else {}
    ranges = quick_ranges(today)
    ctx = {
        'tabs': tabs, 'rtype': rtype, 'meta': meta, 'f': {'from': f, 'to': t, 'branch': g.get('branch', ''), 'low': g.get('low') == '1',
               'supplier': g.get('supplier', ''), 'by': g.get('by', ''), 'department': g.get('department', ''),
               'destination': g.get('destination', '')},
        'opts': opts, 'error': error, 'result': result, 'columns': columns, 'rows': rows, 'totals': totals,
        'total_cells': [{'col': c, 'first': i == 0, 'has': c['key'] in totals, 'value': totals.get(c['key'])} for i, c in enumerate(columns)],
        'scope': scope, 'period': period, 'quick': [('This month', *ranges['month']), ('Last month', *ranges['last_month']),
                                                    ('This year', *ranges['year']), ('All time', *ranges['all'])],
        'branch_side': branch_side, 'printed': timezone.localtime().strftime('%d/%m/%Y %H:%M'),
        'other_branches': [b for b in opts['branches'] if b.type != 'main'],
    }
    return render(request, 'reports/index.html', ctx)
