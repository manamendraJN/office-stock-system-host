from django import forms

from catalog.models import Item, Supplier
from core.constants import ADJUSTMENT_REASONS
from core.forms import DateInput
from core.labels import REASON_LABELS


class PurchaseHeaderForm(forms.Form):
    supplier = forms.ModelChoiceField(label='Supplier', queryset=Supplier.objects.none(), empty_label='Choose…',
                                      error_messages={'required': 'Choose a supplier', 'invalid_choice': 'Choose a supplier'})
    purchase_date = forms.DateField(label='Purchase date', widget=DateInput(),
                                    error_messages={'required': 'Enter the purchase date', 'invalid': 'Enter the purchase date'})
    invoice_ref = forms.CharField(label='Invoice / bill number (optional)', required=False, max_length=80)
    notes = forms.CharField(label='Notes (optional)', required=False, max_length=500,
                            widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, current_supplier_id=None, **kw):
        super().__init__(*args, **kw)
        from django.db.models import Q
        q = Q(active=True)
        if current_supplier_id:
            q |= Q(pk=current_supplier_id)
        self.fields['supplier'].queryset = Supplier.objects.filter(q).order_by('name')


class IssueHeaderForm(forms.Form):
    recipient = forms.CharField(label='Given to', min_length=2, max_length=120,
                                error_messages={'required': 'Enter who the items are for', 'min_length': 'Enter who the items are for'},
                                widget=forms.TextInput(attrs={'autofocus': True}))
    department = forms.CharField(label='Department (optional)', required=False, max_length=120)
    issue_date = forms.DateField(label='Date', widget=DateInput(),
                                 error_messages={'required': 'Enter the date', 'invalid': 'Enter the date'})
    purpose = forms.CharField(label='Purpose (optional)', required=False, max_length=300)


class CancelIssueForm(forms.Form):
    reason = forms.CharField(label='Reason (optional)', required=False, max_length=200,
                             help_text='The items go back into stock. The issue stays on record as cancelled.',
                             error_messages={'max_length': 'Use 200 characters or fewer'})


class CorrectionForm(forms.Form):
    item = forms.ModelChoiceField(label='Item', queryset=Item.objects.none(), empty_label='Choose item…',
                                  error_messages={'required': 'Choose an item', 'invalid_choice': 'That item no longer exists'})
    direction = forms.ChoiceField(label='What changed', choices=[('add', 'Add stock'), ('remove', 'Remove stock')],
                                  widget=forms.RadioSelect, error_messages={'required': 'Choose add or remove', 'invalid_choice': 'Choose add or remove'})
    quantity = forms.IntegerField(label='Quantity', min_value=1, error_messages={
        'required': 'Enter a quantity', 'invalid': 'Use a whole number', 'min_value': 'At least 1'},
        widget=forms.NumberInput(attrs={'min': 1, 'step': 1, 'inputmode': 'numeric'}))
    reason = forms.ChoiceField(label='Reason', choices=[('', 'Choose…')] + [(r, REASON_LABELS[r]) for r in ADJUSTMENT_REASONS],
                               error_messages={'required': 'Choose a reason', 'invalid_choice': 'Choose a reason'})
    note = forms.CharField(label='Note (optional)', required=False, max_length=200,
                           error_messages={'max_length': 'Use 200 characters or fewer'})
    branch = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, item_queryset=None, **kw):
        super().__init__(*args, **kw)
        if item_queryset is not None:
            self.fields['item'].queryset = item_queryset
