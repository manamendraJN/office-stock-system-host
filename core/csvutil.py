"""CSV output for reports. Opens correctly in Excel (UTF-8 BOM). Text that starts with = + - @ (or a tab/CR)
is prefixed with an apostrophe so a spreadsheet never runs it as a formula."""
import csv
import io
from decimal import Decimal

_DANGEROUS = ('=', '+', '-', '@', '\t', '\r')


def _cell(value, kind=None):
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = str(value)
    if kind != 'number' and text.startswith(_DANGEROUS):
        text = "'" + text
    return text


def to_csv(columns, rows, totals=None):
    totals = totals or {}
    out = io.StringIO(newline='')
    w = csv.writer(out, lineterminator='\r\n')
    w.writerow([_cell(c['label']) for c in columns])
    for r in rows:
        w.writerow([_cell(r.get(c['key']), c.get('type')) for c in columns])
    if totals:
        w.writerow(['Total' if i == 0 else (_cell(totals[c['key']], 'number') if c['key'] in totals else '')
                    for i, c in enumerate(columns)])
    return '﻿' + out.getvalue()
