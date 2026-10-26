from django import forms

from catalog.models import Category, Item, Supplier

COMMON_UNITS = ['piece', 'ream', 'box', 'pack', 'bottle', 'cartridge', 'set', 'roll']


class CategoryForm(forms.Form):
    name = forms.CharField(min_length=2, max_length=80, error_messages={'required': 'Enter the category name', 'min_length': 'Enter the category name'})

    def __init__(self, *args, instance=None, **kw):
        super().__init__(*args, **kw)
        self.instance = instance

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = Category.objects.filter(name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('That name is already in use')
        return name


class ItemForm(forms.Form):
    name = forms.CharField(label='Item name', min_length=2, max_length=160,
                           error_messages={'required': 'Enter the item name', 'min_length': 'Enter the item name'},
                           widget=forms.TextInput(attrs={'placeholder': 'e.g. A4 Paper 80gsm', 'autofocus': True}))
    category = forms.ModelChoiceField(label='Category', queryset=Category.objects.none(), empty_label='Choose…',
                                      error_messages={'required': 'Choose a category', 'invalid_choice': 'Choose a category'})
    unit = forms.CharField(label='Unit', max_length=30, help_text='How you count it',
                           error_messages={'required': 'Enter the unit, for example ream or box'},
                           widget=forms.TextInput(attrs={'list': 'unit-options', 'placeholder': 'e.g. ream'}))
    code = forms.CharField(label='Item code', required=False, max_length=20,
                           widget=forms.TextInput(attrs={'placeholder': 'Automatic'}))
    min_stock = forms.IntegerField(label='Minimum stock', min_value=0, initial=0, help_text='Flagged for re-ordering at or below this',
                                   error_messages={'required': 'Enter a number', 'invalid': 'Use a whole number', 'min_value': 'Cannot be negative'},
                                   widget=forms.NumberInput(attrs={'min': 0, 'step': 1}))
    active = forms.BooleanField(label='Item is active (inactive items cannot be requested or purchased)', required=False, initial=True)

    def __init__(self, *args, instance=None, **kw):
        super().__init__(*args, **kw)
        self.instance = instance
        self.fields['category'].queryset = Category.objects.order_by('name')
        self.fields['code'].help_text = 'Fixed once the item has stock history' if instance else 'Leave blank to generate automatically'
        if instance is None:
            del self.fields['active']

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip().upper()
        if code:
            qs = Item.objects.filter(code=code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('That code is already in use')
        return code


class SupplierForm(forms.Form):
    name = forms.CharField(label='Supplier name', min_length=2, max_length=120,
                           error_messages={'required': 'Enter the supplier name', 'min_length': 'Enter the supplier name'},
                           widget=forms.TextInput(attrs={'placeholder': 'e.g. Lanka Stationers', 'autofocus': True}))
    contact = forms.CharField(label='Contact person (optional)', required=False, max_length=120)
    phone = forms.CharField(label='Phone (optional)', required=False, max_length=40)
    active = forms.BooleanField(label='Supplier is active (inactive suppliers cannot be used on new purchases)', required=False, initial=True)

    def __init__(self, *args, instance=None, **kw):
        super().__init__(*args, **kw)
        self.instance = instance
        if instance is None:
            del self.fields['active']

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = Supplier.objects.filter(name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('That name is already in use')
        return name
