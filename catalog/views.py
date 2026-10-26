from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog import services
from catalog.forms import COMMON_UNITS, CategoryForm, ItemForm, SupplierForm
from catalog.models import Category, Item, Supplier
from core.decorators import permission_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.permissions import has_any, is_branch_side
from core.services.audit import log_audit
from inventory.services.stock import get_balances, get_main_branch

ITEM_READ = ('items.view', 'requests.create', 'requests.review', 'dispatches.manage', 'purchases.manage', 'issues.manage')


# ------------------------------------------------------------------ items
@permission_required(*ITEM_READ)
def item_list(request):
    user = request.user
    g = request.GET
    search, category, status, low_only = g.get('q', '').strip(), g.get('category', ''), g.get('status', 'active'), g.get('low') == '1'
    can_edit = has_any(user, ['items.manage'])
    qs = Item.objects.select_related('category')
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
    if category.isdigit():
        qs = qs.filter(category_id=int(category))
    # Branch-side users without edit rights only ever see active items; everyone else can filter.
    if (is_branch_side(user) and not can_edit) or status == 'active':
        qs = qs.filter(active=True)
    elif status == 'inactive':
        qs = qs.filter(active=False)
    items = list(qs.order_by('name'))
    if is_branch_side(user):
        branch_id = user.branch_id
    else:
        main = get_main_branch()
        branch_id = main.pk if main else None
    balances = get_balances(branch_id, [i.pk for i in items])
    rows = []
    for i in items:
        stock = balances.get(i.pk, 0)
        low = i.active and stock <= i.min_stock
        if low_only and not low:
            continue
        rows.append({'i': i, 'stock': stock, 'low': low})
    filters_on = bool(search or category or low_only or status != 'active')
    return render(request, 'catalog/item_list.html', {
        'rows': rows, 'categories': Category.objects.order_by('name'), 'can_edit': can_edit, 'filters_on': filters_on,
        'f': {'q': search, 'category': category, 'status': status, 'low': low_only},
        'show_status': (not is_branch_side(user)) or can_edit, 'branch_side': is_branch_side(user)})


def _item_form(request, item=None):
    initial = ({'name': item.name, 'category': item.category_id, 'unit': item.unit, 'code': item.code,
                'min_stock': item.min_stock, 'active': item.active} if item else None)
    form = ItemForm(request.POST or None, instance=item, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            if item is None:
                services.create_item(request, form.cleaned_data)
                messages.success(request, 'Item added')
            else:
                services.update_item(request, item, form.cleaned_data)
                messages.success(request, 'Item updated')
            return redirect('catalog:item_list')
        except ServiceError as exc:
            apply_service_error(form, exc)
    return render(request, 'catalog/item_form.html', {'form': form, 'item': item, 'units': COMMON_UNITS})


@permission_required('items.manage')
def item_create(request):
    return _item_form(request)


@permission_required('items.manage')
def item_edit(request, pk):
    return _item_form(request, get_object_or_404(Item, pk=pk))


@permission_required('items.manage')
@require_POST
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    outcome = services.delete_item(request, item)
    messages.success(request, 'Item deleted' if outcome == 'deleted'
                     else 'This item has history, so it was deactivated instead of deleted')
    return redirect('catalog:item_list')


# ------------------------------------------------------------------ categories
@permission_required('items.manage')
def category_list(request):
    add_form = CategoryForm(request.POST or None, prefix='new') if request.POST.get('do') == 'add' else CategoryForm(prefix='new')
    if request.method == 'POST' and request.POST.get('do') == 'add' and add_form.is_valid():
        cat = Category.objects.create(name=add_form.cleaned_data['name'])
        log_audit(request, 'category.create', 'Category', cat.pk, new_value={'name': cat.name})
        messages.success(request, 'Category added')
        return redirect('catalog:category_list')
    cats = Category.objects.annotate(item_count=Count('items')).order_by('name')
    return render(request, 'catalog/category_list.html', {'categories': cats, 'add_form': add_form})


@permission_required('items.manage')
@require_POST
def category_rename(request, pk):
    cat = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST, instance=cat)
    if form.is_valid():
        old = {'name': cat.name}
        cat.name = form.cleaned_data['name']
        cat.save()
        log_audit(request, 'category.update', 'Category', cat.pk, old_value=old, new_value={'name': cat.name})
        messages.success(request, 'Category renamed')
    else:
        messages.error(request, '; '.join(e for errs in form.errors.values() for e in errs))
    return redirect('catalog:category_list')


@permission_required('items.manage')
@require_POST
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk)
    try:
        services.delete_category(request, cat)
        messages.success(request, 'Category deleted')
    except ServiceError as exc:
        messages.error(request, exc.message)
    return redirect('catalog:category_list')


# ------------------------------------------------------------------ suppliers
@permission_required('suppliers.view', 'purchases.view')
def supplier_list(request):
    suppliers = Supplier.objects.annotate(purchase_count=Count('purchases')).order_by('name')
    return render(request, 'catalog/supplier_list.html', {'suppliers': suppliers, 'can_edit': has_any(request.user, ['suppliers.manage'])})


def _supplier_form(request, supplier=None):
    initial = ({'name': supplier.name, 'contact': supplier.contact, 'phone': supplier.phone, 'active': supplier.active} if supplier else None)
    form = SupplierForm(request.POST or None, instance=supplier, initial=initial)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        if supplier is None:
            s = Supplier.objects.create(name=cd['name'], contact=cd['contact'], phone=cd['phone'])
            log_audit(request, 'supplier.create', 'Supplier', s.pk, new_value={'name': s.name, 'contact': s.contact, 'phone': s.phone})
            messages.success(request, 'Supplier added')
        else:
            old = {'name': supplier.name, 'contact': supplier.contact, 'phone': supplier.phone, 'active': supplier.active}
            supplier.name, supplier.contact, supplier.phone, supplier.active = cd['name'], cd['contact'], cd['phone'], cd['active']
            supplier.save()
            log_audit(request, 'supplier.update', 'Supplier', supplier.pk, old_value=old,
                      new_value={'name': supplier.name, 'contact': supplier.contact, 'phone': supplier.phone, 'active': supplier.active})
            messages.success(request, 'Supplier updated')
        return redirect('catalog:supplier_list')
    return render(request, 'catalog/supplier_form.html', {'form': form, 'supplier': supplier})


@permission_required('suppliers.manage')
def supplier_create(request):
    return _supplier_form(request)


@permission_required('suppliers.manage')
def supplier_edit(request, pk):
    return _supplier_form(request, get_object_or_404(Supplier, pk=pk))


@permission_required('suppliers.manage')
@require_POST
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    outcome = services.delete_supplier(request, supplier)
    messages.success(request, 'Supplier deleted' if outcome == 'deleted'
                     else 'This supplier has purchases, so it was deactivated instead of deleted')
    return redirect('catalog:supplier_list')
