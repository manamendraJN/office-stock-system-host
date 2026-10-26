from decimal import Decimal

from django import forms

from core.forms import DateInput

_AMOUNT = dict(max_digits=12, decimal_places=2, min_value=Decimal('0.01'), max_value=Decimal('99999999.99'))
_MSG = {'required': 'Enter an amount', 'invalid': 'Enter an amount such as 2500 or 2500.50',
        'min_value': 'Enter an amount above zero', 'max_digits': 'That amount is too large',
        'max_value': 'That amount is too large', 'max_decimal_places': 'Use at most 2 decimal places'}


def _amount(label, **kw):
    return forms.DecimalField(label=label, error_messages=_MSG, **_AMOUNT, **kw,
                              widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'inputmode': 'decimal'}))


class RequestForm(forms.Form):
    amount = _amount('Amount needed (Rs.)')
    purpose = forms.CharField(label='What is it for? (optional)', required=False, max_length=300,
                              error_messages={'max_length': 'Use 300 characters or fewer'},
                              widget=forms.Textarea(attrs={'rows': 2, 'maxlength': 300}))


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=[('approve', 'Approve and give the money'), ('reject', 'Reject')], widget=forms.RadioSelect,
                                 initial='approve', error_messages={'required': 'Choose approve or reject', 'invalid_choice': 'Choose approve or reject'})
    amount = _amount('Amount to give (Rs.)', required=False)
    note = forms.CharField(label='Reason (needed if you give less than asked, or reject)', required=False, max_length=200,
                           error_messages={'max_length': 'Use 200 characters or fewer'})

    def clean(self):
        data = super().clean()
        if data.get('decision') == 'approve' and data.get('amount') is None and 'amount' not in self.errors:
            self.add_error('amount', 'Enter the amount to give')
        return data


class ExpenseForm(forms.Form):
    amount = _amount('Amount spent (Rs.)')
    description = forms.CharField(label='What was bought?', max_length=300,
                                  error_messages={'required': 'Say what the money was spent on', 'max_length': 'Use 300 characters or fewer'})
    entry_date = forms.DateField(label='Date', required=False, widget=DateInput(), error_messages={'invalid': 'Enter a real date'})


class LowLevelForm(forms.Form):
    level = forms.DecimalField(label='Low petty cash level (Rs.)', max_digits=12, decimal_places=2, min_value=Decimal('0'),
                               help_text='A branch is flagged as low when its petty cash is at or below this amount',
                               error_messages={'required': 'Enter an amount', 'invalid': 'Enter an amount such as 2000',
                                               'min_value': 'The level cannot be negative', 'max_digits': 'That amount is too large',
                                               'max_decimal_places': 'Use at most 2 decimal places'},
                               widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'inputmode': 'decimal'}))
