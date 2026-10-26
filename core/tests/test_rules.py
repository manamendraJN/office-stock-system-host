"""Business-rule tests. Ported from the original server/test/*.test.js (the "pure rules" parts).

These use plain unittest and need neither a database nor Django, e.g.:
    python -m unittest core.tests.test_rules
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

from core import permissions as perm
from core.constants import ROLES
from core.labels import action_tone, action_label
from core.rules import (admin_rules, issue_rules, purchase_rules, report_rules, request_rules,
                        role_rules, stock_rules)


class RoleRuleTests(unittest.TestCase):
    def test_role_keys_come_from_the_name_and_never_clash(self):
        self.assertEqual(role_rules.slugify('  Front   Desk Clerk! '), 'front_desk_clerk')
        self.assertEqual(role_rules.slugify('!!!'), 'role')
        self.assertEqual(role_rules.unique_key('Front Desk', []), 'front_desk')
        self.assertEqual(role_rules.unique_key('Front Desk', ['front_desk']), 'front_desk_2')
        self.assertEqual(role_rules.unique_key('Front Desk', ['front_desk', 'front_desk_2']), 'front_desk_3')
        self.assertEqual(role_rules.unique_key('Super Admin', []), 'super_admin_2')

    def test_role_names_compare_ignoring_case_and_spacing(self):
        self.assertTrue(role_rules.name_taken('  stock   OFFICER', ['Stock Officer']))
        self.assertFalse(role_rules.name_taken('Auditor', ['Stock Officer']))
        self.assertTrue(role_rules.name_taken('super admin', []))

    def test_role_delete_and_side_lock(self):
        self.assertIsNone(role_rules.role_delete_problem(key='clerk', user_count=0))
        self.assertRegex(role_rules.role_delete_problem(key='clerk', user_count=1), r'1 user has this role')
        self.assertRegex(role_rules.role_delete_problem(key='clerk', user_count=3), r'3 users have this role')
        self.assertIsNone(role_rules.role_edit_problem(key='clerk', change_side='branch', current_side='main', user_count=0))
        self.assertRegex(role_rules.role_edit_problem(key='clerk', change_side='branch', current_side='main', user_count=2),
                         'side cannot be changed')
        self.assertIsNone(role_rules.role_edit_problem(key='clerk', change_side='main', current_side='main', user_count=2))
        self.assertIsNone(role_rules.role_edit_problem(key='clerk', user_count=2))

    def test_super_admin_is_built_in(self):
        self.assertRegex(role_rules.role_delete_problem(key='super_admin', built_in=True), 'built in')
        self.assertRegex(role_rules.role_edit_problem(key='super_admin', built_in=True), 'built in')


class PermissionRuleTests(unittest.TestCase):
    def test_ticks_unknown_dropped_dependencies_added_order_stable(self):
        self.assertEqual(perm.normalize_permissions(['purchases.receive', 'nonsense', 'purchases.receive']),
                         ['purchases.view', 'purchases.receive'])
        self.assertEqual(perm.normalize_permissions(['items.manage']), ['items.view', 'items.manage'])
        self.assertEqual(perm.normalize_permissions([]), [])

    def test_effective_permissions(self):
        role_def = {'permissions': ['items.view']}
        self.assertEqual(perm.effective_permissions(NS(role='super_admin', permissions=[]), role_def), list(perm.ALL_PERMISSIONS))
        self.assertEqual(perm.effective_permissions(NS(role='x', permissions=['stock.view']), role_def), ['stock.view'])
        self.assertEqual(perm.effective_permissions(NS(role='x', permissions=None), role_def), ['items.view'])
        self.assertEqual(perm.effective_permissions(NS(role='x', permissions=[]), role_def), [], 'empty list = no features')
        u = NS(role='x', permissions=['stock.view'], role_def=role_def)
        self.assertTrue(perm.has_any(u, ['items.view', 'stock.view']))
        self.assertFalse(perm.has_any(NS(role='x', permissions=[], role_def=role_def), ['items.view']))

    def test_resolve_permissions(self):
        officer = {'key': 'stock_officer', 'permissions': ['items.view', 'stock.view']}
        self.assertEqual(perm.resolve_permissions(officer), ['items.view', 'stock.view'])
        self.assertEqual(perm.resolve_permissions(officer, requested=['items.manage']), ['items.view', 'items.manage'])
        self.assertEqual(perm.resolve_permissions(officer, requested=[]), [], 'ticking nothing is respected')
        self.assertEqual(perm.resolve_permissions(officer, current=['reports.view']), ['reports.view'])
        self.assertEqual(perm.resolve_permissions(officer, current=['reports.view'], role_changed=True), ['items.view', 'stock.view'])
        self.assertIsNone(perm.resolve_permissions({'key': 'super_admin', 'permissions': []}))

    def test_branch_scope(self):
        main_user = NS(role='x', permissions=None, role_def={'side': 'main'}, branch_id=1)
        branch_user = NS(role='x', permissions=None, role_def={'side': 'branch'}, branch_id=7)
        self.assertTrue(perm.can_access_branch(main_user, 99))
        self.assertTrue(perm.can_access_branch(main_user, None))
        self.assertTrue(perm.can_access_branch(branch_user, 7))
        self.assertTrue(perm.can_access_branch(branch_user, '7'))
        self.assertFalse(perm.can_access_branch(branch_user, 8))
        self.assertFalse(perm.can_access_branch(branch_user, None))
        self.assertFalse(perm.is_branch_side(NS(role_def=None)), 'a vanished role is treated as main side')

    def test_default_roles(self):
        self.assertEqual([r['name'] for r in perm.DEFAULT_ROLES], ['Stock Officer', 'Viewer / Approver', 'Branch User'])
        for r in perm.DEFAULT_ROLES:
            for p in r['permissions']:
                self.assertIn(p, perm.ALL_PERMISSIONS)

    def test_navigation_follows_permissions(self):
        user = NS(role='x')
        labels = [n['label'] for n in perm.visible_nav(user, ['items.view', 'requests.create'], False)]
        self.assertEqual(labels, ['Dashboard', 'Items'])
        labels = [n['label'] for n in perm.visible_nav(user, ['items.view', 'requests.create'], True)]
        self.assertEqual(labels, ['Dashboard', 'Items', 'Requests'])
        admin = NS(role=ROLES.SUPER_ADMIN)
        labels = [n['label'] for n in perm.visible_nav(admin, list(perm.ALL_PERMISSIONS), False)]
        self.assertIn('Audit Log', labels)
        self.assertNotIn('Requests', labels)


class AdminRuleTests(unittest.TestCase):
    def test_last_admin(self):
        self.assertRegex(admin_rules.last_admin_problem(role='super_admin', active=True, change_active=False, other_active_admins=0),
                         'only active Super Admin')
        self.assertRegex(admin_rules.last_admin_problem(role='super_admin', active=True, change_role='viewer', other_active_admins=0),
                         'only active Super Admin')
        self.assertIsNone(admin_rules.last_admin_problem(role='super_admin', active=True, change_active=False, other_active_admins=1))
        self.assertIsNone(admin_rules.last_admin_problem(role='super_admin', active=True, other_active_admins=0))
        self.assertIsNone(admin_rules.last_admin_problem(role='viewer', active=True, change_active=False, other_active_admins=0))

    def test_main_office_protected_and_unique(self):
        self.assertRegex(admin_rules.main_branch_problem(branch_type='main', change_active=False), 'cannot be deactivated')
        self.assertRegex(admin_rules.main_branch_problem(branch_type='main', change_type='branch'), 'into a branch')
        self.assertIsNone(admin_rules.main_branch_problem(branch_type='main'))
        self.assertIsNone(admin_rules.main_branch_problem(branch_type='branch', change_active=False))
        self.assertRegex(admin_rules.second_main_branch_problem(wants_type='main', existing_main_id='a', branch_id='b'), 'already exists')
        self.assertIsNone(admin_rules.second_main_branch_problem(wants_type='main', existing_main_id='a', branch_id='a'))
        self.assertIsNone(admin_rules.second_main_branch_problem(wants_type='branch', existing_main_id='a', branch_id='b'))

    def test_branch_module_off(self):
        self.assertRegex(admin_rules.branch_module_off_problem(currently_on=True, wants_on=False, open_requests=2, open_dispatches=1),
                         '2 open requests and 1 dispatch not yet closed')
        self.assertIsNone(admin_rules.branch_module_off_problem(currently_on=True, wants_on=False, open_requests=0, open_dispatches=0))
        self.assertIsNone(admin_rules.branch_module_off_problem(currently_on=False, wants_on=False, open_requests=5, open_dispatches=5))
        self.assertIsNone(admin_rules.branch_module_off_problem(currently_on=True, wants_on=True, open_requests=5, open_dispatches=5))

    def test_user_audit_action(self):
        self.assertEqual(admin_rules.user_audit_action(password='x', was_active=True), 'user.reset_password')
        self.assertEqual(admin_rules.user_audit_action(password=None, was_active=True, change_active=False), 'user.disable')
        self.assertEqual(admin_rules.user_audit_action(password=None, was_active=False, change_active=True), 'user.enable')
        self.assertEqual(admin_rules.user_audit_action(password=None, was_active=True, change_active=True), 'user.update')
        self.assertEqual(admin_rules.user_audit_action(password=None, was_active=True), 'user.update')


def pline(id, item, ordered, received=0, cost='10.00'):
    return NS(id=id, item_id=item, quantity_ordered=ordered, quantity_received=received, unit_cost=Decimal(cost))


class PurchaseRuleTests(unittest.TestCase):
    def test_total_and_status(self):
        lines = [pline(1, 1, 10, 0, '100'), pline(2, 2, 3, 0, '33.333')]
        self.assertEqual(purchase_rules.purchase_total(lines), Decimal('1100.00'))
        self.assertEqual(purchase_rules.status_from_lines(lines), 'ordered')
        lines[0].quantity_received = 10
        self.assertEqual(purchase_rules.status_from_lines(lines), 'partly_received')
        lines[1].quantity_received = 3
        self.assertEqual(purchase_rules.status_from_lines(lines), 'received')

    def test_locking(self):
        lines = [pline(1, 1, 10)]
        self.assertIsNone(purchase_rules.locked_problem('ordered', lines, 'edited'))
        self.assertEqual(purchase_rules.locked_problem('cancelled', lines, 'edited'), 'This purchase was cancelled')
        lines[0].quantity_received = 1
        self.assertRegex(purchase_rules.locked_problem('partly_received', lines, 'cancelled'), 'can no longer be cancelled')

    def test_duplicates(self):
        self.assertIsNone(purchase_rules.duplicate_item_problem([1, 2, 3]))
        self.assertRegex(purchase_rules.duplicate_item_problem([1, 2, 1]), 'listed twice')

    def test_receipt_plan(self):
        lines = [pline(1, 1, 10, 4), pline(2, 2, 5, 0)]
        plan = purchase_rules.receipt_plan('partly_received', lines, [{'line_id': 1, 'quantity': 6}, {'line_id': 2, 'quantity': 0}])
        self.assertEqual([(l.id, q) for l, q in plan['postings']], [(1, 6)])
        self.assertRegex(purchase_rules.receipt_plan('partly_received', lines, [{'line_id': 1, 'quantity': 7}])['problem'], 'Only 6 still to receive')
        self.assertRegex(purchase_rules.receipt_plan('partly_received', lines, [{'line_id': 1, 'quantity': 0}])['problem'], 'at least one')
        self.assertRegex(purchase_rules.receipt_plan('partly_received', lines, [{'line_id': 9, 'quantity': 1}])['problem'], 'does not belong')
        self.assertRegex(purchase_rules.receipt_plan('partly_received', lines, [{'line_id': 1, 'quantity': 1}, {'line_id': 1, 'quantity': 1}])['problem'], 'twice')
        self.assertRegex(purchase_rules.receipt_plan('received', lines, [])['problem'], 'fully received')
        self.assertRegex(purchase_rules.receipt_plan('cancelled', lines, [])['problem'], 'cancelled')


class IssueAndStockRuleTests(unittest.TestCase):
    def test_shortage(self):
        names = {1: 'Pen', 2: 'Paper'}
        self.assertIsNone(issue_rules.shortage_problem([{'item': 1, 'quantity': 5}], {1: 5}, names))
        msg = issue_rules.shortage_problem([{'item': 1, 'quantity': 6}, {'item': 2, 'quantity': 1}], {1: 5}, names)
        self.assertEqual(msg, 'Not enough stock for: Pen (5 in stock, you entered 6); Paper (0 in stock, you entered 1)')
        self.assertIn('(0 in stock', issue_rules.shortage_problem([{'item': 1, 'quantity': 1}], {1: -3}, names))

    def test_cancel(self):
        self.assertIsNone(issue_rules.cancel_problem('issued'))
        self.assertRegex(issue_rules.cancel_problem('cancelled'), 'already cancelled')

    def test_adjustments(self):
        self.assertRegex(stock_rules.adjustment_problem('remove', 'found', ''), 'only be added')
        self.assertRegex(stock_rules.adjustment_problem('add', 'damaged', ''), 'only be removed')
        self.assertRegex(stock_rules.adjustment_problem('add', 'expired', ''), 'only be removed')
        self.assertRegex(stock_rules.adjustment_problem('add', 'other', ''), 'explain')
        self.assertIsNone(stock_rules.adjustment_problem('add', 'other', 'recount'))
        self.assertIsNone(stock_rules.adjustment_problem('remove', 'count_difference', ''))
        self.assertEqual(stock_rules.signed_quantity('remove', 4), -4)
        self.assertEqual(stock_rules.signed_quantity('add', 4), 4)

    def test_never_below_zero(self):
        self.assertIsNone(stock_rules.negative_stock_problem(5, -5, 'Pen'))
        self.assertEqual(stock_rules.negative_stock_problem(3, -5, 'Pen'), 'Only 3 of "Pen" in stock, so 5 cannot be removed')
        self.assertIn('Only 0 of', stock_rules.negative_stock_problem(-2, -1, 'Pen'))


def rline(id, item, requested, approved=0, dispatched=0):
    return NS(id=id, item_id=item, quantity_requested=requested, quantity_approved=approved, quantity_dispatched=dispatched)


A, B = 11, 22


class RequestRuleTests(unittest.TestCase):
    def test_review_outcomes(self):
        lines = [rline(1, A, 10), rline(2, B, 5)]
        p = request_rules.review_plan('submitted', lines, [{'line_id': 1, 'quantity_approved': 10}, {'line_id': 2, 'quantity_approved': 5}])
        self.assertEqual(p['status'], 'approved')
        p = request_rules.review_plan('submitted', lines, [{'line_id': 1, 'quantity_approved': 6, 'reason': 'Low stock'}, {'line_id': 2, 'quantity_approved': 5}])
        self.assertEqual(p['status'], 'partly_approved')
        p = request_rules.review_plan('submitted', lines, [{'line_id': 1, 'quantity_approved': 0, 'reason': 'No'}, {'line_id': 2, 'quantity_approved': 0, 'reason': 'No'}])
        self.assertEqual(p['status'], 'rejected')

    def test_review_enforces_reasons_limits_completeness(self):
        lines = [rline(1, A, 10), rline(2, B, 5)]
        full = [{'line_id': 1, 'quantity_approved': 10}, {'line_id': 2, 'quantity_approved': 5}]
        self.assertRegex(request_rules.review_plan('submitted', lines, [{'line_id': 1, 'quantity_approved': 4}, full[1]])['problem'], 'reason')
        self.assertRegex(request_rules.review_plan('submitted', lines, [{'line_id': 1, 'quantity_approved': 11}, full[1]])['problem'], 'more than the 10')
        self.assertRegex(request_rules.review_plan('submitted', lines, [full[0]])['problem'], 'every item')
        self.assertRegex(request_rules.review_plan('submitted', lines, [full[0], full[0]])['problem'], 'twice')
        self.assertRegex(request_rules.review_plan('submitted', lines, [full[0], {'line_id': 99, 'quantity_approved': 1}])['problem'], 'does not belong')
        self.assertRegex(request_rules.review_plan('approved', lines, full)['problem'], 'already been reviewed')

    def test_request_completes_when_everything_approved_is_sent(self):
        self.assertEqual(request_rules.status_after_dispatch('approved', [rline(1, A, 10, 10, 6)]), 'approved')
        self.assertEqual(request_rules.status_after_dispatch('partly_approved', [rline(1, A, 10, 6, 6), rline(2, B, 5, 0, 0)]), 'completed')
        self.assertFalse(request_rules.can_dispatch('submitted', [rline(1, A, 10, 10, 0)]))
        self.assertFalse(request_rules.can_dispatch('approved', [rline(1, A, 10, 10, 10)]))
        self.assertIsNone(request_rules.cancel_request_problem('submitted'))
        self.assertTrue(request_rules.cancel_request_problem('approved'))

    def test_dispatch_plan(self):
        lines = [rline(1, A, 10, 10, 4)]
        names = {A: 'Pen'}

        def plan(qty, stock, item=A, **kw):
            return request_rules.dispatch_plan(request_status='approved', request_lines=lines, has_request=True,
                                               requested=[{'item': item, 'quantity': qty}], balances={A: stock}, names=names, **kw)
        self.assertEqual(plan(6, 50)['postings'], [{'item': A, 'quantity': 6}])
        self.assertRegex(plan(7, 50)['problem'], r'Only 6 of "Pen" still to send')
        self.assertRegex(plan(6, 2)['problem'], 'Not enough stock')
        self.assertRegex(plan(0, 50)['problem'], 'at least one')
        self.assertRegex(plan(1, 50, item=B)['problem'], 'not on this request')
        direct = request_rules.dispatch_plan(requested=[{'item': A, 'quantity': 40}], balances={A: 50}, names=names)
        self.assertEqual(len(direct['postings']), 1, 'a direct dispatch has no request limit, only the stock check')

    def test_receipt_and_close(self):
        d = [NS(item_id=A, quantity_sent=10), NS(item_id=B, quantity_sent=5)]
        p = request_rules.receipt_plan('in_transit', d, [{'item': A, 'received': 10, 'damaged': 0}, {'item': B, 'received': 5, 'damaged': 0}])
        self.assertEqual(p['status'], 'received')
        p = request_rules.receipt_plan('in_transit', d, [{'item': A, 'received': 7, 'damaged': 1}, {'item': B, 'received': 5, 'damaged': 0}])
        self.assertEqual(p['status'], 'received_with_differences')
        self.assertEqual(p['lines'][0]['short'], 2)
        self.assertRegex(request_rules.receipt_plan('in_transit', d, [{'item': A, 'received': 10, 'damaged': 1}, {'item': B, 'received': 5, 'damaged': 0}])['problem'],
                         'more than the 10 sent')
        self.assertRegex(request_rules.receipt_plan('in_transit', d, [{'item': A, 'received': 10, 'damaged': 0}])['problem'], 'every item')
        self.assertRegex(request_rules.receipt_plan('received', d, [])['problem'], 'already been received')
        lines = [NS(item_id=A, quantity_damaged=1, quantity_short=2), NS(item_id=B, quantity_damaged=0, quantity_short=0)]
        self.assertEqual(len(request_rules.close_plan('received_with_differences', lines)['leftovers']), 1)
        self.assertTrue(request_rules.close_plan('received', [])['problem'])


PEN = {'id': 1, 'code': 'PEN', 'name': 'Pen', 'unit': 'box', 'min_stock': 5, 'active': True, 'last_unit_cost': Decimal('100'), 'category': 'Stationery'}
A4 = {'id': 2, 'code': 'A4', 'name': 'A4 paper', 'unit': 'ream', 'min_stock': 10, 'active': True, 'last_unit_cost': Decimal('1500'), 'category': 'Paper'}
OLD = {'id': 3, 'code': 'OLD', 'name': 'Old stapler', 'unit': 'piece', 'min_stock': 0, 'active': False, 'last_unit_cost': None, 'category': 'Equipment'}
SUP = {'id': 1, 'name': 'Ceylon Stationers'}


def item_ref(i):
    return {k: i[k] for k in ('id', 'code', 'name', 'unit')}


class ReportRuleTests(unittest.TestCase):
    def test_date_range(self):
        self.assertEqual(report_rules.parse_range(), {'from': None, 'to': None})
        r = report_rules.parse_range('2026-10-01', '2026-10-31')
        self.assertEqual((r['from'], r['to']), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertRegex(report_rules.parse_range('2026-02-31')['problem'], 'from')
        self.assertRegex(report_rules.parse_range(None, 'yesterday')['problem'], 'to')
        self.assertRegex(report_rules.parse_range('2026-10-05', '2026-10-01')['problem'], 'after')
        self.assertTrue(report_rules.parse_range('2026-10-05', '2026-10-05')['from'])

    def test_month_ranges(self):
        self.assertEqual(report_rules.month_range(date(2026, 10, 14)), (date(2026, 10, 1), date(2026, 11, 1)))
        self.assertEqual(report_rules.month_range(date(2026, 12, 31)), (date(2026, 12, 1), date(2027, 1, 1)))
        q = report_rules.quick_ranges(date(2026, 1, 15))
        self.assertEqual(q['last_month'], ('2025-12-01', '2025-12-31'))
        self.assertEqual(q['year'], ('2026-01-01', '2026-01-15'))
        self.assertEqual(q['all'], ('', ''))

    def test_stock_report(self):
        balances = {1: 3, 2: 40, 3: 0}
        r = report_rules.balance_report([PEN, A4, OLD], balances)
        self.assertEqual([x['code'] for x in r['rows']], ['A4', 'PEN'])  # sorted by name; inactive+empty hidden
        self.assertEqual(next(x for x in r['rows'] if x['code'] == 'PEN')['status'], 'Low stock')
        self.assertEqual(next(x for x in r['rows'] if x['code'] == 'A4')['value'], Decimal('60000.00'))
        self.assertEqual(r['totals']['value'], Decimal('60300.00'))
        with_old = report_rules.balance_report([OLD], {3: 2})
        self.assertEqual(with_old['rows'][0]['status'], 'Inactive')
        self.assertIsNone(with_old['rows'][0]['value'])  # no cost known: no invented value
        self.assertEqual(len(report_rules.balance_report([PEN, A4], balances, low_only=True)['rows']), 1)
        self.assertEqual(report_rules.balance_report([PEN], {1: -4})['rows'][0]['value'], Decimal('0.00'))

    def _purchases(self):
        pen, a4 = item_ref(PEN), item_ref(A4)
        return [
            {'id': 1, 'status': 'received', 'supplier': SUP, 'lines': [{'item': pen, 'quantity_ordered': 10, 'quantity_received': 10, 'unit_cost': Decimal(100)}]},
            {'id': 2, 'status': 'partly_received', 'supplier': SUP, 'lines': [
                {'item': pen, 'quantity_ordered': 10, 'quantity_received': 4, 'unit_cost': Decimal(120)},
                {'item': a4, 'quantity_ordered': 2, 'quantity_received': 0, 'unit_cost': Decimal(1500)}]},
            {'id': 3, 'status': 'cancelled', 'supplier': SUP, 'lines': [{'item': a4, 'quantity_ordered': 99, 'quantity_received': 0, 'unit_cost': Decimal(1500)}]},
        ]

    def test_purchase_report(self):
        by_sup = report_rules.purchase_report(self._purchases())
        self.assertEqual(len(by_sup['rows']), 1)
        row = by_sup['rows'][0]
        self.assertEqual(row['purchases'], 2)
        self.assertEqual(row['ordered_value'], Decimal(1000 + 1200 + 3000))
        self.assertEqual(row['received_value'], Decimal(1000 + 480))
        self.assertEqual(row['outstanding_value'], Decimal(5200 - 1480))
        by_item = report_rules.purchase_report(self._purchases(), by='item')
        self.assertEqual([r['code'] for r in by_item['rows']], ['A4', 'PEN'])  # biggest spend first
        self.assertEqual(next(r for r in by_item['rows'] if r['code'] == 'PEN')['quantity_received'], 14)
        self.assertEqual(by_item['totals']['ordered_value'], Decimal(5200))
        self.assertEqual(report_rules.spent_total(self._purchases()), Decimal('5200.00'))

    def test_usage_report(self):
        pen, a4 = item_ref(PEN), item_ref(A4)
        issues = [
            {'id': 1, 'status': 'issued', 'department': 'Accounts', 'lines': [{'item': pen, 'quantity': 3}, {'item': a4, 'quantity': 1}]},
            {'id': 2, 'status': 'issued', 'department': ' accounts ', 'lines': [{'item': pen, 'quantity': 2}]},
            {'id': 3, 'status': 'issued', 'department': '', 'lines': [{'item': pen, 'quantity': 1}]},
            {'id': 4, 'status': 'cancelled', 'department': 'Accounts', 'lines': [{'item': pen, 'quantity': 50}]},
        ]
        by_item = report_rules.usage_report(issues)
        self.assertEqual(by_item['rows'][0]['code'], 'PEN')
        self.assertEqual(by_item['rows'][0]['quantity'], 6)
        self.assertEqual(by_item['rows'][0]['issues'], 3)
        self.assertEqual(by_item['totals'], {}, 'different units are never added together')
        by_dept = report_rules.usage_report(issues, by='department')
        self.assertEqual(next(r for r in by_dept['rows'] if r['department'] == 'Accounts')['quantity'], 4)
        self.assertEqual(next(r for r in by_dept['rows'] if r['department'] == 'No department')['quantity'], 1)

    def test_dispatch_report(self):
        pen = item_ref(PEN)

        def d(id, dest, lines):
            return {'id': id, 'destination': dest, 'lines': lines}
        galle, kandy = {'id': 5, 'name': 'Galle'}, {'id': 6, 'name': 'Kandy'}
        r = report_rules.dispatch_report([
            d(1, galle, [{'item': pen, 'quantity_sent': 10, 'quantity_received': 8, 'quantity_damaged': 1, 'quantity_short': 1}]),
            d(2, galle, [{'item': pen, 'quantity_sent': 5, 'quantity_received': 0}]),
            d(3, kandy, [{'item': pen, 'quantity_sent': 2, 'quantity_received': 2}]),
        ])
        self.assertEqual(len(r['rows']), 2)
        self.assertEqual(r['rows'][0], {'branch': 'Galle', 'code': 'PEN', 'name': 'Pen', 'unit': 'box',
                                        'dispatches': 2, 'sent': 15, 'received': 8, 'damaged': 1, 'short': 1})
        self.assertEqual(r['rows'][1]['branch'], 'Kandy')

    def test_low_stock_list(self):
        r = report_rules.low_stock_items([A4, PEN, OLD], {1: 0, 2: 9})
        self.assertEqual(r['count'], 2)
        self.assertEqual(r['out_of_stock'], 1)
        self.assertEqual([i['code'] for i in r['items']], ['A4', 'PEN'] if (10 - 9) > (5 - 0) else ['PEN', 'A4'])
        self.assertEqual(len(report_rules.low_stock_items([A4, PEN], {1: 0, 2: 0}, limit=1)['items']), 1)


class LabelTests(unittest.TestCase):
    def test_audit_tones_and_labels(self):
        self.assertEqual(action_tone('item.delete'), 'red')
        self.assertEqual(action_tone('purchase.cancel'), 'red')
        self.assertEqual(action_tone('purchase.receive'), 'green')
        self.assertEqual(action_tone('auth.login'), 'amber')
        self.assertEqual(action_tone('user.reset_password'), 'amber')
        self.assertEqual(action_tone('stock.adjust'), 'blue')
        self.assertEqual(action_label('item.create'), 'Added an item')
        self.assertEqual(action_label('unknown.code'), 'unknown.code')


if __name__ == '__main__':
    unittest.main()
