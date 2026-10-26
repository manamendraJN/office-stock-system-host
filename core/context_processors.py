from django.urls import NoReverseMatch, reverse

from core.models import Setting
from core.permissions import ALL_PERMISSIONS, side_of, visible_nav


def app(request):
    ctx = {}
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return ctx
    settings = Setting.get()
    ctx['app_settings'] = settings
    perms = getattr(request, 'perms', [])
    nav = []
    path = request.path
    for n in visible_nav(user, perms, settings.branch_module_enabled):
        try:
            url = reverse(n['url'])
        except NoReverseMatch:
            continue
        active = path == url if n.get('exact') else path.startswith(n['match'])
        nav.append({**n, 'href': url, 'active': active})
    ctx.update({
        'nav': nav,
        # perm.items_manage in templates
        'perm': {p.replace('.', '_'): (p in perms) for p in ALL_PERMISSIONS},
        'is_branch_side': side_of(user) == 'branch',
        'is_super_admin': user.role == 'super_admin',
    })
    return ctx
