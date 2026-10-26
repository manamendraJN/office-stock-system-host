from django import forms

from accounts.models import Branch
from core.forms import DateInput


class RequestForm(forms.Form):
    notes = forms.CharField(label='Notes (optional)', required=False, max_length=300,
                            error_messages={'max_length': 'Use 300 characters or fewer'},
                            widget=forms.Textarea(attrs={'rows': 2, 'maxlength': 300}))


class DirectDispatchForm(forms.Form):
    destination = forms.ModelChoiceField(
        label='Send to', queryset=Branch.objects.none(), empty_label='Choose a branch…',
        error_messages={'required': 'Choose a branch to send to', 'invalid_choice': 'Choose a branch to send to'})
    dispatch_date = forms.DateField(label='Date sent', required=False, widget=DateInput(),
                                    error_messages={'invalid': 'Enter a real date'})

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.fields['destination'].queryset = Branch.objects.filter(active=True, type='branch').order_by('name')


class CloseDispatchForm(forms.Form):
    resolution = forms.ChoiceField(
        label='What happens to them?',
        choices=[('', 'Choose…'), ('write_off', 'Write them off (lost or damaged)'),
                 ('return_to_main', 'They came back to the main office')],
        help_text='Written-off items are removed from the system. Returned items go back into main office stock.',
        error_messages={'required': 'Choose what happens to them', 'invalid_choice': 'Choose what happens to them'})
    note = forms.CharField(label='Note (optional)', required=False, max_length=200,
                           error_messages={'max_length': 'Use 200 characters or fewer'})
