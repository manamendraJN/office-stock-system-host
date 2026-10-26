"""Catalog rules that need the database: item history checks and the audit-aware create/update/delete."""
from django.db import transaction

from core.errors import Conflict
from core.services.audit import log_audit
from core.services.sequence import next_number


def item_has_history(item):
    from branchops.models import DispatchLine, RequestLine
    from inventory.models import OfficeIssueLine, PurchaseLine, StockLedger
    return (StockLedger.objects.filter(item=item).exists()
            or PurchaseLine.objects.filter(item=item).exists()
            or RequestLine.objects.filter(item=item).exists()
            or DispatchLine.objects.filter(item=item).exists()
            or OfficeIssueLine.objects.filter(item=item).exists())


def item_snapshot(i):
    return {'code': i.code, 'name': i.name, 'category': i.category_id, 'unit': i.unit, 'min_stock': i.min_stock,
            'last_unit_cost': i.last_unit_cost, 'active': i.active}


def create_item(request, data):
    """data: code (may be blank), name, category, unit, min_stock."""
    from catalog.models import Item
    code = (data.get('code') or '').strip().upper() or next_number('ITM')
    item = Item.objects.create(code=code, name=data['name'], category=data['category'], unit=data['unit'],
                               min_stock=data['min_stock'])
    log_audit(request, 'item.create', 'Item', item.pk, new_value=item_snapshot(item))
    return item


def update_item(request, item, data):
    """data: code (blank keeps the current one), name, category, unit, min_stock, active."""
    old = item_snapshot(item)
    code = (data.get('code') or '').strip().upper()
    # The code identifies the item on every past document, so it can only change if the item has no history.
    if code and code != item.code:
        if item_has_history(item):
            raise Conflict('This item has stock history, so its code can no longer be changed',
                           {'code': 'Code is locked once an item has history'})
        item.code = code
    item.name, item.category, item.unit, item.min_stock = data['name'], data['category'], data['unit'], data['min_stock']
    if 'active' in data:
        item.active = data['active']
    item.save()
    log_audit(request, 'item.update', 'Item', item.pk, old_value=old, new_value=item_snapshot(item))
    return item


def delete_item(request, item):
    """Returns 'deleted' or 'deactivated'. An item with history is deactivated, never deleted."""
    with transaction.atomic():
        if item_has_history(item):
            item.active = False
            item.save(update_fields=['active', 'updated_at'])
            outcome = 'deactivated'
        else:
            snap = item_snapshot(item)
            pk = item.pk
            item.delete()
            outcome = 'deleted'
    if outcome == 'deactivated':
        log_audit(request, 'item.deactivate', 'Item', item.pk)
    else:
        log_audit(request, 'item.delete', 'Item', pk, old_value=snap)
    return outcome


def delete_category(request, category):
    in_use = category.items.count()
    if in_use:
        raise Conflict(f"This category has {in_use} item{'' if in_use == 1 else 's'}. Move or remove them first")
    snap = {'name': category.name}
    pk = category.pk
    category.delete()
    log_audit(request, 'category.delete', 'Category', pk, old_value=snap)


def delete_supplier(request, supplier):
    from inventory.models import Purchase
    if Purchase.objects.filter(supplier=supplier).exists():
        supplier.active = False
        supplier.save(update_fields=['active', 'updated_at'])
        log_audit(request, 'supplier.deactivate', 'Supplier', supplier.pk)
        return 'deactivated'
    snap = {'name': supplier.name, 'contact': supplier.contact, 'phone': supplier.phone}
    pk = supplier.pk
    supplier.delete()
    log_audit(request, 'supplier.delete', 'Supplier', pk, old_value=snap)
    return 'deleted'
