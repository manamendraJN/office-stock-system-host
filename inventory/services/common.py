"""Shared helpers for the document services (purchases, issues, requests, dispatches)."""
from catalog.models import Item
from core.errors import BadRequest, NotFound
from core.permissions import can_access_branch, is_branch_side


def user_stock_branch_id(user, main):
    """The branch a user's own documents belong to: their branch (branch-side roles) or the main office."""
    if is_branch_side(user):
        return user.branch_id
    return main.pk if main else None


def assert_visible(user, record, branch_id, what):
    """A branch-side user only reaches their own branch's records; to them others do not exist."""
    if record is None or not can_access_branch(user, branch_id):
        raise NotFound(f'{what} not found')


def usable_items(item_ids, verb):
    """Every item must exist and be active. Returns {item_id: Item}."""
    ids = list(item_ids)
    items = {i.pk: i for i in Item.objects.filter(pk__in=ids)}
    if len(items) != len(set(ids)):
        raise BadRequest('One of the items no longer exists')
    for i in items.values():
        if not i.active:
            raise BadRequest(f'"{i.name}" is inactive and cannot be {verb}')
    return items
