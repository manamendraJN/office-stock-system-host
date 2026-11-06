from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Branch, User
from core.models import Setting
from core.permissions import has_any, is_branch_side
from vouchers.models import ExpenseCategory, Voucher, VoucherSchedule


def eligible_approvers(branch):
    users = User.objects.filter(active=True, branch__type='main').select_related('branch')
    if branch and branch.type == 'branch':
        users = users.filter(branch__type='main')
    return [user for user in users if not is_branch_side(user) and has_any(user, ['vouchers.approve'])]


def eligible_recommenders(branch):
    users = User.objects.filter(active=True, branch__type='main').select_related('branch')
    if branch and branch.type == 'branch':
        users = users.filter(branch__type='main')
    return [user for user in users if not is_branch_side(user) and has_any(user, ['vouchers.recommend'])]


class VoucherForm(forms.ModelForm):
    recommender = forms.ModelChoiceField(queryset=User.objects.none(), required=False,
                                         empty_label='Choose an authorized recommender')
    approver = forms.ModelChoiceField(queryset=User.objects.none(), required=False,
                                      empty_label='Choose an authorized manager')

    class Meta:
        model = Voucher
        fields = ('amount', 'date', 'cash', 'method_of_payment', 'to', 'account_details', 'cheque_number',
                  'receipt_attached', 'being', 'payee', 'category', 'branch', 'recommender', 'approver')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
            'being': forms.TextInput(attrs={'placeholder': 'Purpose of payment'}),
        }

    def __init__(self, *args, user, instance=None, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        self.user = user
        self.fields['category'].queryset = ExpenseCategory.objects.filter(is_active=True)
        if instance and instance.pk:
            self.fields['category'].queryset |= ExpenseCategory.objects.filter(pk=instance.category_id)
        self.fields['date'].label = 'Payment date'
        if is_branch_side(user):
            branches = Branch.objects.filter(pk=user.branch_id, active=True)
            if instance and instance.pk:
                branches |= Branch.objects.filter(pk=instance.branch_id)
            self.fields['branch'].widget = forms.HiddenInput()
            self.fields['branch'].initial = user.branch_id
        else:
            branches = Branch.objects.filter(active=True)
            if instance and instance.pk:
                branches |= Branch.objects.filter(pk=instance.branch_id)
            self.fields['branch'].empty_label = 'Choose a branch'
        self.fields['branch'].queryset = branches.order_by('type', 'name')
        self.fields['recommender'].label = 'Recommender'
        self.fields['approver'].label = 'Approver'
        self.fields['recommender'].queryset = User.objects.filter(
            pk__in=[u.pk for u in eligible_recommenders(user.branch)]
        ).exclude(pk=user.pk).order_by('name')
        self.fields['approver'].queryset = User.objects.filter(
            pk__in=[u.pk for u in eligible_approvers(user.branch)]
        ).exclude(pk=user.pk).order_by('name')
        if instance and instance.pk:
            self.initial['branch'] = instance.branch_id
            self.initial['recommender'] = instance.recommender_id
            self.initial['approver'] = instance.approver_id
        elif is_branch_side(user):
            self.initial['branch'] = user.branch_id
        elif not self.is_bound and user.branch.active:
            self.initial['branch'] = user.branch_id
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        for name in ('cash', 'receipt_attached'):
            self.fields[name].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        data = super().clean()
        if data.get('method_of_payment') == Voucher.PaymentMethod.CHEQUE and not data.get('cheque_number'):
            self.add_error('cheque_number', 'Enter the cheque number for cheque payments.')
        if data.get('cash') and data.get('method_of_payment') != Voucher.PaymentMethod.CASH:
            self.add_error('cash', 'Select Cash as the payment method when this is a cash voucher.')
        if is_branch_side(self.user) and data.get('branch') and data['branch'].pk != self.user.branch_id:
            self.add_error('branch', 'Branch-side users can only create vouchers for their own branch.')
        if data.get('recommender') and data.get('recommender') == data.get('approver'):
            self.add_error('approver', 'The recommender and approver must be different users.')
        return data


class VoucherScheduleForm(forms.ModelForm):
    recommender = forms.ModelChoiceField(queryset=User.objects.none(), required=False,
                                         empty_label='Choose an authorized recommender')
    approver = forms.ModelChoiceField(queryset=User.objects.none(), required=False,
                                      empty_label='Choose an authorized manager')

    class Meta:
        model = VoucherSchedule
        fields = ('title', 'category', 'amount', 'frequency', 'next_run', 'cash', 'method_of_payment',
                  'to', 'account_details', 'cheque_number', 'being', 'payee', 'branch', 'recommender',
                  'approver', 'is_active')
        widgets = {'next_run': forms.DateInput(attrs={'type': 'date'}),
                   'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'})}

    def __init__(self, *args, user, instance=None, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        self.user = user
        min_next_run = (timezone.localdate() + timezone.timedelta(days=1)).isoformat()
        self.fields['next_run'].widget.attrs['min'] = min_next_run
        self.fields['category'].queryset = ExpenseCategory.objects.filter(is_active=True)
        if instance and instance.pk:
            self.fields['category'].queryset |= ExpenseCategory.objects.filter(pk=instance.category_id)
        self.fields['next_run'].label = 'Payment date of next occurrence'
        if is_branch_side(user):
            branches = Branch.objects.filter(pk=user.branch_id, active=True)
            if instance and instance.pk:
                branches |= Branch.objects.filter(pk=instance.branch_id)
            self.fields['branch'].widget = forms.HiddenInput()
            self.fields['branch'].initial = user.branch_id
        else:
            branches = Branch.objects.filter(active=True)
            if instance and instance.pk:
                branches |= Branch.objects.filter(pk=instance.branch_id)
            self.fields['branch'].empty_label = 'Choose a branch'
        self.fields['branch'].queryset = branches.order_by('type', 'name')
        self.fields['recommender'].label = 'Recommender'
        self.fields['approver'].label = 'Approver'
        self.fields['recommender'].queryset = User.objects.filter(
            pk__in=[u.pk for u in eligible_recommenders(user.branch)]
        ).exclude(pk=user.pk).order_by('name')
        self.fields['approver'].queryset = User.objects.filter(
            pk__in=[u.pk for u in eligible_approvers(user.branch)]
        ).exclude(pk=user.pk).order_by('name')
        if instance and instance.pk:
            self.initial.update(branch=instance.branch_id, recommender=instance.recommender_id,
                                approver=instance.approver_id)
        elif is_branch_side(user):
            self.initial['branch'] = user.branch_id
        elif not self.is_bound and user.branch.active:
            self.initial['branch'] = user.branch_id
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        for name in ('cash', 'is_active'):
            self.fields[name].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        data = super().clean()
        if data.get('method_of_payment') == Voucher.PaymentMethod.CHEQUE and not data.get('cheque_number'):
            self.add_error('cheque_number', 'Enter the cheque number for cheque payments.')
        if data.get('cash') and data.get('method_of_payment') != Voucher.PaymentMethod.CASH:
            self.add_error('cash', 'Select Cash as the payment method when this is a cash voucher.')
        if is_branch_side(self.user) and data.get('branch') and data['branch'].pk != self.user.branch_id:
            self.add_error('branch', 'Branch-side users can only schedule vouchers for their own branch.')
        can_self_approve = (Setting.get().payment_voucher_self_approval_enabled
                            and has_any(self.user, ['vouchers.self_approve']))
        if not data.get('approver') and not can_self_approve:
            self.add_error('approver', 'Choose an authorized manager for this schedule.')
        if data.get('recommender') and data.get('recommender') == data.get('approver'):
            self.add_error('approver', 'The recommender and approver must be different users.')
        if data.get('recommender') and not data.get('approver'):
            self.add_error('approver', 'A recommender must be paired with an authorized manager.')
        next_run = data.get('next_run')
        if next_run and next_run <= timezone.localdate():
            self.add_error('next_run', 'Choose a date after today for the next payment occurrence.')
        return data


class RejectVoucherForm(forms.Form):
    reason = forms.CharField(max_length=500, label='Reason for rejection',
                             widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}))

    def clean_reason(self):
        reason = self.cleaned_data['reason'].strip()
        if not reason:
            raise ValidationError('Enter a reason before rejecting a voucher.')
        return reason


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ('name', 'description', 'monthly_budget_limit', 'is_active')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'monthly_budget_limit': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['is_active'].widget.attrs['class'] = 'form-check-input'
