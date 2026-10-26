from django import forms

from core.errors import ServiceError


def apply_service_error(form, exc):
    """Attaches a ServiceError to the form: field errors where the field exists, otherwise a general error."""
    placed = False
    for name, msg in (exc.field_errors or {}).items():
        if name in form.fields:
            form.add_error(name, msg)
            placed = True
    if not placed:
        form.add_error(None, exc.message)
    return form


class DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kw):
        kw.setdefault('format', '%Y-%m-%d')
        super().__init__(**kw)


class TrimmedCharField(forms.CharField):
    """Whitespace-trimmed text (Django's CharField already strips; kept for clarity of intent)."""
