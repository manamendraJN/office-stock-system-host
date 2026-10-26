from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Branch
from core.constants import PETTY_CASH_ENTRY, PETTY_CASH_STATUS
from core.errors import BadRequest, Conflict, Forbidden, NotFound
from core.models import Setting
from core.permissions import has_any, is_branch_side
from core.rules import petty_cash_rules as rules
from core.services.audit import log_audit
from core.services.sequence import next_number
from pettycash.models import PettyCashEntry, PettyCashRequest

ZERO = Decimal('0.00')


# ------------------------------------------------------------------ who sees what
def sees_all_branches(user):
    """Main-office users with a petty cash management feature see every branch; everyone else sees their own."""
    return not is_branch_side(user) and has_any(user, ['petty_cash.view', 'petty_cash.approve', 'petty_cash.configure'])


def scope_branch_id(user):
    """None means every branch."""
    return None if sees_all_branches(user) else user.branch_id


def can_see_branch(user, branch_id):
    scope = scope_branch_id(user)
    return scope is None or (branch_id is not None and branch_id == scope)


def get_low_level():
    return Setting.get().petty_cash_low_level


# ------------------------------------------------------------------ balances
def get_balance(branch_id):
    return PettyCashEntry.objects.filter(branch_id=branch_id).aggregate(n=Sum('amount'))['n'] or ZERO


def get_balances(branch_ids=None):
    qs = PettyCashEntry.objects.all()
    if branch_ids is not None:
        qs = qs.filter(branch_id__in=list(branch_ids))
    return {r['branch_id']: r['n'] for r in qs.values('branch_id').annotate(n=Sum('amount'))}


def branch_summaries(user):
    """[{'branch', 'balance', 'low', 'pending'}] for the branches this user may see (main office first)."""
    level = get_low_level()
    scope = scope_branch_id(user)
    branches = Branch.objects.all() if scope is None else Branch.objects.filter(pk=scope)
    balances = get_balances(None if scope is None else [scope])
    pending = {r['branch_id']: r['n'] for r in PettyCashRequest.objects.filter(status=PETTY_CASH_STATUS.SUBMITTED)
               .values('branch_id').annotate(n=Sum('amount_requested'))}
    out = []
    for b in branches.order_by('type', 'name'):
        bal = balances.get(b.pk, ZERO)
        if not b.active and bal == 0:
            continue
        out.append({'branch': b, 'balance': bal, 'low': rules.is_low(bal, level), 'pending': pending.get(b.pk, ZERO)})
    return out


# ------------------------------------------------------------------ requests
def get_request(user, pk, for_update=False):
    qs = PettyCashRequest.objects.select_related('branch', 'requested_by', 'reviewed_by')
    if for_update:
        qs = qs.select_for_update(of=('self',))
    obj = qs.filter(pk=pk).first()
    if obj is None or not can_see_branch(user, obj.branch_id):
        raise NotFound('Petty cash request not found')
    return obj


def create_request(request, amount, purpose):
    user = request.user
    if not user.branch_id:
        raise BadRequest('Your account is not assigned to a branch')
    problem = rules.amount_problem(amount)
    if problem:
        raise BadRequest(problem, {'amount': problem})
    with transaction.atomic():
        req = PettyCashRequest.objects.create(number=next_number('PCR', yearly=True), branch=user.branch, amount_requested=amount,
                                              purpose=purpose or '', requested_by=user)
    log_audit(request, 'petty_cash.create', 'PettyCashRequest', req.pk,
              new_value={'number': req.number, 'branch': user.branch_id, 'amount': amount, 'purpose': purpose})
    return req


def cancel_request(request, pk):
    """Only the branch that raised it can withdraw it, and only before it is reviewed."""
    user = request.user
    with transaction.atomic():
        req = get_request(user, pk, for_update=True)
        if req.branch_id != user.branch_id:
            raise Forbidden('Only the branch that raised this request can cancel it')
        problem = rules.cancel_request_problem(req.status)
        if problem:
            raise Conflict(problem)
        req.status = PETTY_CASH_STATUS.CANCELLED
        req.save(update_fields=['status', 'updated_at'])
    log_audit(request, 'petty_cash.cancel', 'PettyCashRequest', req.pk)
    return req


def review_request(request, pk, *, approve, amount, note):
    """The manager approves (the money is handed over, so the branch balance goes up) or rejects."""
    user = request.user
    if is_branch_side(user):
        raise Forbidden('Only main-office managers can approve petty cash')
    with transaction.atomic():
        req = get_request(user, pk, for_update=True)
        plan = rules.review_plan(req.status, req.amount_requested, approve, amount, note,
                                 is_requester=req.requested_by_id == user.pk, is_super_admin=user.role == 'super_admin')
        if plan.get('problem'):
            raise Conflict(plan['problem'])
        req.status = plan['status']
        req.amount_approved = plan['amount']
        req.review_note = (note or '').strip()[:200]
        req.reviewed_by = user
        req.reviewed_at = timezone.now()
        req.save()
        if plan['status'] == PETTY_CASH_STATUS.APPROVED:
            PettyCashEntry.objects.create(branch_id=req.branch_id, type=PETTY_CASH_ENTRY.TOP_UP, amount=plan['amount'],
                                          description=f'Petty cash {req.number}', entry_date=timezone.localdate(),
                                          request=req, created_by=user)
    log_audit(request, 'petty_cash.review', 'PettyCashRequest', req.pk,
              new_value={'status': req.status, 'amount_approved': req.amount_approved, 'note': req.review_note})
    return req


# ------------------------------------------------------------------ spending
def record_expense(request, amount, description, entry_date):
    """Money spent from the user's own branch cash, e.g. buying inventory items. It cannot take the balance below zero."""
    user = request.user
    if not user.branch_id:
        raise BadRequest('Your account is not assigned to a branch')
    with transaction.atomic():
        Branch.objects.select_for_update().filter(pk=user.branch_id).first()  # serialises spending per branch
        problem = rules.expense_problem(get_balance(user.branch_id), amount)
        if problem:
            raise BadRequest(problem, {'amount': problem})
        entry = PettyCashEntry.objects.create(branch_id=user.branch_id, type=PETTY_CASH_ENTRY.EXPENSE, amount=-Decimal(amount),
                                              description=description, entry_date=entry_date or timezone.localdate(), created_by=user)
    log_audit(request, 'petty_cash.expense', 'PettyCashEntry', entry.pk,
              new_value={'branch': user.branch_id, 'amount': amount, 'description': description})
    return entry


def cancel_expense(request, pk):
    """An expense entered by mistake is undone by a reversal entry that puts the money back."""
    user = request.user
    with transaction.atomic():
        entry = PettyCashEntry.objects.filter(pk=pk).first()
        if entry is None or not can_see_branch(user, entry.branch_id):
            raise NotFound('Petty cash entry not found')
        if entry.branch_id != user.branch_id and not has_any(user, ['petty_cash.approve']):
            raise Forbidden('Only the branch that spent the money, or a manager, can cancel this expense')
        Branch.objects.select_for_update().filter(pk=entry.branch_id).first()
        problem = rules.cancel_expense_problem(entry.type, PettyCashEntry.objects.filter(reversal_of=entry).exists())
        if problem:
            raise Conflict(problem)
        PettyCashEntry.objects.create(branch_id=entry.branch_id, type=PETTY_CASH_ENTRY.REVERSAL, amount=-entry.amount,
                                      description=f'Cancelled: {entry.description}'[:300], entry_date=timezone.localdate(),
                                      reversal_of=entry, created_by=user)
    log_audit(request, 'petty_cash.cancel_expense', 'PettyCashEntry', entry.pk)
    return entry


# ------------------------------------------------------------------ settings
def set_low_level(request, level):
    if level < 0:
        raise BadRequest('The low level cannot be negative', {'level': 'The low level cannot be negative'})
    settings = Setting.get()
    old = settings.petty_cash_low_level
    settings.petty_cash_low_level = level
    settings.save(update_fields=['petty_cash_low_level', 'updated_at'])
    log_audit(request, 'petty_cash.set_low_level', 'Setting', settings.pk, old_value={'level': old}, new_value={'level': level})
    return settings
