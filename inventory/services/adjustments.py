from django.db import transaction

from accounts.models import Branch
from core.constants import LEDGER_TYPES
from core.errors import BadRequest
from core.errors import Conflict
from core.permissions import is_branch_side
from core.rules.stock_rules import adjustment_problem, negative_stock_problem, signed_quantity
from core.services.audit import log_audit
from inventory.models import StockLedger
from inventory.services.stock import get_balance, get_main_branch, lock_items


def resolve_branch(user, requested_id=None):
    """A branch-side user always works with their own branch. Main-office users may pick any branch
    (the main office by default)."""
    if is_branch_side(user):
        return Branch.objects.filter(pk=user.branch_id).first()
    if requested_id:
        try:
            branch = Branch.objects.filter(pk=int(requested_id)).first()
        except (TypeError, ValueError):
            branch = None
        if not branch:
            raise BadRequest('Choose a valid branch')
        return branch
    return get_main_branch()


def create_adjustment(request, *, branch, item, direction, quantity, reason, note=''):
    """A correction (count difference, damaged, expired, found). One ledger row, never an edit of a balance.
    Removing stock is checked and posted in one transaction, with the item locked, so a correction and an
    issue at the same moment cannot take the stock below zero."""
    problem = adjustment_problem(direction, reason, note)
    if problem:
        raise BadRequest(problem)
    if not branch:
        raise BadRequest('No main office exists. Run the seed command first')
    change = signed_quantity(direction, quantity)
    with transaction.atomic():
        lock_items([item.pk])
        current = get_balance(branch.pk, item.pk)
        too_much = negative_stock_problem(current, change, item.name)
        if too_much:
            raise Conflict(too_much)
        StockLedger.objects.create(item=item, branch=branch, quantity_change=change, type=LEDGER_TYPES.ADJUSTMENT,
                                   reason=reason, note=note or '', created_by=request.user)
    log_audit(request, 'stock.adjust', 'Item', item.pk,
              new_value={'branch': branch.pk, 'change': change, 'reason': reason, 'note': note})
    return current + change
