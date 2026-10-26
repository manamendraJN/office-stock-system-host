from django import forms
from django.contrib.auth.password_validation import validate_password

from accounts.models import Branch
from core.forms import DateInput  # noqa: F401  (re-exported for convenience)


class LoginForm(forms.Form):
    email = forms.EmailField(label='Email', error_messages={'required': 'Enter a valid email', 'invalid': 'Enter a valid email'},
                             widget=forms.EmailInput(attrs={'autocomplete': 'username', 'autofocus': True}))
    password = forms.CharField(label='Password', error_messages={'required': 'Enter your password'},
                               widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(label='Current password', error_messages={'required': 'Enter your current password'},
                                       widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'autofocus': True}))
    new_password = forms.CharField(label='New password', min_length=12, help_text='At least 12 characters',
                                   error_messages={'required': 'Use at least 12 characters', 'min_length': 'Use at least 12 characters'},
                                   widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    confirm = forms.CharField(label='Confirm new password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        password = self.cleaned_data['new_password']
        validate_password(password, user=self.user)
        return password

    def clean(self):
        data = super().clean()
        new, cur, confirm = data.get('new_password'), data.get('current_password'), data.get('confirm')
        if new and cur and new == cur:
            self.add_error('new_password', 'Choose a password different from the current one')
        elif new and confirm != new:
            self.add_error('confirm', 'The two new passwords do not match')
        return data


class ResetPasswordForm(forms.Form):
    password = forms.CharField(label='New temporary password', min_length=12,
                               help_text='At least 12 characters. Tell the user privately; they can change it after signing in',
                               error_messages={'required': 'Use at least 12 characters', 'min_length': 'Use at least 12 characters'},
                               widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'autofocus': True}))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password, user=self.user)
        return password


class UserForm(forms.Form):
    name = forms.CharField(label='Full name', min_length=2, max_length=120, error_messages={'required': 'Enter the full name', 'min_length': 'Enter the full name'})
    email = forms.EmailField(label='Email (used to sign in)', error_messages={'required': 'Enter a valid email', 'invalid': 'Enter a valid email'})
    role = forms.CharField(label='Role', error_messages={'required': 'Choose a role'})
    branch = forms.ModelChoiceField(label='Branch', queryset=Branch.objects.none(), empty_label='Choose…',
                                    error_messages={'required': 'Choose a branch', 'invalid_choice': 'Choose a valid branch'})
    password = forms.CharField(label='Temporary password', min_length=12, required=False,
                               help_text='At least 12 characters. The user can change it after signing in',
                               widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                               error_messages={'min_length': 'Use at least 12 characters'})

    def __init__(self, *args, editing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing = editing
        qs = Branch.objects.filter(active=True)
        if editing is not None:
            # An inactive branch the user already belongs to stays selectable, so editing other details still works.
            qs = Branch.objects.filter(active=True) | Branch.objects.filter(pk=editing.branch_id)
        self.fields['branch'].queryset = qs.order_by('type', 'name').distinct()
        if editing is None:
            self.fields['password'].required = True
            self.fields['password'].error_messages['required'] = 'Use at least 8 characters'
        else:
            del self.fields['password']  # passwords are changed with "Reset password"

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        from accounts.models import User
        qs = User.objects.filter(email=email)
        if self.editing is not None:
            qs = qs.exclude(pk=self.editing.pk)
        if qs.exists():
            raise forms.ValidationError('That email is already in use')
        return email

    def clean_password(self):
        password = self.cleaned_data['password']
        if password:
            from accounts.models import User
            candidate = User(name=self.cleaned_data.get('name', ''), email=self.cleaned_data.get('email', ''))
            validate_password(password, user=candidate)
        return password


class RoleForm(forms.Form):
    name = forms.CharField(label='Role name', min_length=2, max_length=40,
                           error_messages={'required': 'Enter a role name', 'min_length': 'Enter a role name',
                                           'max_length': 'Use 40 characters or fewer'})
    description = forms.CharField(label='Description (optional)', required=False, max_length=200,
                                  help_text='Shown when choosing a role for a user',
                                  error_messages={'max_length': 'Use 200 characters or fewer'})
    side = forms.ChoiceField(label='Works at', choices=[('', 'Choose…'), ('main', 'Main office'), ('branch', 'Branch')],
                             error_messages={'required': 'Choose where this role works', 'invalid_choice': 'Choose where this role works'})


class BranchForm(forms.Form):
    name = forms.CharField(label='Branch name', min_length=2, max_length=120, error_messages={'required': 'Enter the branch name', 'min_length': 'Enter the branch name'},
                           widget=forms.TextInput(attrs={'placeholder': 'e.g. Kandy Branch', 'autofocus': True}))
    code = forms.CharField(label='Short code', min_length=2, max_length=10, help_text='2 to 10 letters',
                           error_messages={'required': 'Enter a short code', 'min_length': 'Enter a short code', 'max_length': 'Use 10 characters or fewer'},
                           widget=forms.TextInput(attrs={'placeholder': 'KDY', 'style': 'text-transform:uppercase'}))
    address = forms.CharField(label='Address (optional)', required=False, max_length=250)
    phone = forms.CharField(label='Phone (optional)', required=False, max_length=40)
    active = forms.BooleanField(label='Branch is active (inactive branches cannot send new requests)', required=False, initial=True)

    def clean_code(self):
        return self.cleaned_data['code'].strip().upper()


class SettingsCompanyForm(forms.Form):
    company_name = forms.CharField(label='Company name', max_length=120, error_messages={'required': 'Enter the company name'})
