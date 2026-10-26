from decimal import Decimal, InvalidOperation

from django import template
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.labels import MOVEMENT_TYPES, STATUS_LABELS, action_label, action_tone, area_of, AREA_LABELS

register = template.Library()

ICON_PATHS = {
    'home': 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10',
    'box': 'M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8',
    'cart': 'M3 4h2l2.4 11h10.2L20 7H6M9 20a1 1 0 100-2 1 1 0 000 2zm8 0a1 1 0 100-2 1 1 0 000 2z',
    'hand': 'M8 13V5a1.5 1.5 0 013 0v6m0-1V4a1.5 1.5 0 013 0v7m0-5a1.5 1.5 0 013 0v8a6 6 0 01-6 6h-1a6 6 0 01-5-3l-2-3a1.5 1.5 0 012.4-1.8L8 15',
    'inbox': 'M3 13l3-8h12l3 8M3 13v6h18v-6M3 13h5l1 3h6l1-3h5',
    'truck': 'M3 6h11v10H3zM14 9h4l3 3v4h-7M7 19a2 2 0 100-4 2 2 0 000 4zm10 0a2 2 0 100-4 2 2 0 000 4z',
    'list': 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
    'chart': 'M4 20V10M10 20V4M16 20v-8M22 20H2',
    'building': 'M4 21V5l8-2v18M12 8h8v13M8 9h.01M8 13h.01M8 17h.01M16 12h.01M16 16h.01M2 21h20',
    'users': 'M16 20v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 11a4 4 0 100-8 4 4 0 000 8zM21 20v-1a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8',
    'cog': 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3h0a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5h0a1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8v0a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z',
    'logout': 'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9',
    'menu': 'M4 6h16M4 12h16M4 18h16',
    'close': 'M6 6l12 12M18 6L6 18',
    'plus': 'M12 5v14M5 12h14',
    'shield': 'M12 3l8 3v6c0 4.5-3.2 8.3-8 9-4.8-.7-8-4.5-8-9V6l8-3zM9 12l2 2 4-4',
    'clock': 'M12 7v5l3 2M12 21a9 9 0 100-18 9 9 0 000 18z',
    'alert': 'M12 9v4M12 17h.01M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
    'wallet': 'M3 7a2 2 0 012-2h12v4M3 7v11a2 2 0 002 2h14a1 1 0 001-1v-3M3 7h15a2 2 0 012 2v3M21 12h-4a2 2 0 100 4h4v-4z',
    'store': 'M3 9l1.5-5h15L21 9M3 9h18M3 9a3 3 0 006 0 3 3 0 006 0 3 3 0 006 0M5 12v8h14v-8M10 20v-4h4v4',
}


@register.simple_tag
def icon(name, css='icon'):
    return format_html('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
                       'stroke-linejoin="round" class="{}" aria-hidden="true"><path d="{}"/></svg>', css, ICON_PATHS.get(name, ''))


@register.filter
def money(value):
    """Rs. 1,234.50"""
    try:
        d = Decimal(str(value if value not in (None, '') else 0))
    except InvalidOperation:
        d = Decimal(0)
    return f'Rs. {d:,.2f}'


@register.filter
def fdate(value):
    """05 Oct 2026"""
    return value.strftime('%d %b %Y') if value else ''


@register.filter
def ftime(value):
    """05 Oct, 14:30 (in the configured time zone)"""
    if not value:
        return ''
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d %b, %H:%M')


@register.filter
def fdatetime(value):
    if not value:
        return ''
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d %b %Y, %H:%M')


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def absval(value):
    try:
        return abs(value)
    except TypeError:
        return value


@register.filter
def plural(count, word):
    return f'{count} {word}' if count == 1 else f'{count} {word}s'


@register.simple_tag
def badge(text, tone='gray'):
    return format_html('<span class="badge badge-{}">{}</span>', tone, text)


@register.simple_tag
def status_badge(kind, status):
    info = STATUS_LABELS.get(kind, {}).get(status, {'tone': 'gray', 'label': status})
    return format_html('<span class="badge badge-{}">{}</span>', info['tone'], info['label'])


@register.simple_tag
def movement_badge(kind):
    info = MOVEMENT_TYPES.get(kind, {'label': kind, 'tone': 'gray'})
    return format_html('<span class="badge badge-{}">{}</span>', info['tone'], info['label'])


@register.filter
def action_name(code):
    return action_label(code)


@register.filter
def action_color(code):
    return action_tone(code)


@register.filter
def area_name(code):
    return AREA_LABELS.get(area_of(code), area_of(code))


@register.inclusion_tag('core/_field.html')
def field(bound, hint='', css=''):
    return {'f': bound, 'hint': hint, 'css': css}


@register.simple_tag(takes_context=True)
def qs(context, **overrides):
    """Current query string with some values replaced (used by pagination and filters)."""
    from urllib.parse import urlencode
    q = context['request'].GET.copy()
    for k, v in overrides.items():
        if v in (None, ''):
            q.pop(k, None)
        else:
            q[k] = v
    s = urlencode(q, doseq=True)
    return ('?' + s) if s else '?'


@register.inclusion_tag('core/_pagination.html', takes_context=True)
def pagination(context, page, pages, total=None, noun='entries'):
    return {'request': context['request'], 'page': page, 'pages': pages, 'total': total, 'noun': noun}


@register.filter
def money_or_dash(value):
    return '—' if value is None else money(value)


@register.filter
def signed(value):
    if value is None:
        return ''
    return f'+{value}' if value > 0 else f'−{abs(value)}' if value < 0 else '0'


_STATUS_TONES = {'In stock': 'green', 'Low stock': 'amber', 'Out of stock': 'red', 'Inactive': 'gray'}


@register.simple_tag
def report_cell(column, value):
    """One report cell, formatted by the column type (money, number, status, code)."""
    if value is None or value == '':
        return mark_safe('<span class="muted">–</span>')
    kind = column.get('type')
    if kind == 'money':
        return money(value)
    if kind == 'number':
        try:
            return f'{int(value):,}'
        except (TypeError, ValueError):
            return value
    if kind == 'status':
        return badge(value, _STATUS_TONES.get(value, 'gray'))
    if kind == 'code':
        return format_html('<span class="mono small muted">{}</span>', value)
    return value
