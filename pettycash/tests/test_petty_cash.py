"""Petty cash: pure rules, services and page checks."""
import unittest
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.constants import PETTY_CASH_STATUS, ROLES
from core.models import AuditLog, Setting
from core.rules import petty_cash_rules as rules
from core.tests.helpers import PASSWORD, fake_request, make_world
from core.errors import BadRequest, Conflict, Forbidden, NotFound
from pettycash import services
from pettycash.models import PettyCashEntry


class RuleTests(unittest.TestCase):
    def test_low_means_at_or_below_the_level(self):
        self.assertTrue(rules.is_low(D('2000'), D('2000')))
        self.assertTrue(rules.is_low(D('1999.99'), D('2000')))
        self.assertFalse(rules.is_low(D('2000.01'), D('2000')))

    def test_amounts_must_be_positive(self):
        self.assertIsNotNone(rules.amount_problem(D('0')))
        self.assertIsNotNone(rules.amount_problem(None))
        self.assertIsNone(rules.amount_problem(D('0.01')))

    def test_review_plan(self):
        s = PETTY_CASH_STATUS.SUBMITTED
        kw = dict(is_requester=False, is_super_admin=False)
        self.assertEqual(rules.review_plan(s, D('5000'), True, D('5000'), '', **kw), {'status': 'approved', 'amount': D('5000')})
        self.assertIn('reason', rules.review_plan(s, D('5000'), True, D('3000'), '', **kw)['problem'])
        self.assertEqual(rules.review_plan(s, D('5000'), True, D('3000'), 'Budget', **kw)['amount'], D('3000'))
        self.assertIn('more than', rules.review_plan(s, D('5000'), True, D('6000'), 'x', **kw)['problem'])
        self.assertIn('reason', rules.review_plan(s, D('5000'), False, None, ' ', **kw)['problem'])
        self.assertEqual(rules.review_plan(s, D('5000'), False, None, 'No budget', **kw)['status'], 'rejected')
        self.assertIn('already', rules.review_plan('approved', D('5000'), True, D('5000'), '', **kw)['problem'])

    def test_nobody_but_super_admin_reviews_their_own_request(self):
        s = PETTY_CASH_STATUS.SUBMITTED
        self.assertIn('own request', rules.review_plan(s, D('10'), True, D('10'), '', is_requester=True, is_super_admin=False)['problem'])
        self.assertEqual(rules.review_plan(s, D('10'), True, D('10'), '', is_requester=True, is_super_admin=True)['status'], 'approved')

    def test_expense_cannot_exceed_balance(self):
        self.assertIsNone(rules.expense_problem(D('500'), D('500')))
        self.assertIn('Only Rs. 500.00', rules.expense_problem(D('500'), D('500.01')))

    def test_only_an_open_expense_can_be_cancelled(self):
        self.assertIsNone(rules.cancel_expense_problem('expense', False))
        self.assertIsNotNone(rules.cancel_expense_problem('expense', True))
        self.assertIsNotNone(rules.cancel_expense_problem('top_up', False))


class ServiceTests(TestCase):
    def setUp(self):
        self.w = make_world()
        self.manager = User.objects.create_user(
            email='manager@example.test', password=PASSWORD, name='Manager', role=ROLES.STOCK_OFFICER, branch=self.w.main,
            permissions=['petty_cash.view', 'petty_cash.approve', 'petty_cash.configure', 'petty_cash.request'])
        self.kandy_user = User.objects.get(pk=self.w.branch_user.pk)
        self.kandy_user.permissions = ['petty_cash.request']
        self.kandy_user.save()

    def top_up(self, user, amount):
        req = services.create_request(fake_request(user), D(amount), 'Stationery')
        return services.review_request(fake_request(self.manager), req.pk, approve=True, amount=D(amount), note='')

    def test_approval_adds_cash_to_the_branch(self):
        self.assertEqual(services.get_balance(self.w.kandy.pk), 0)
        req = self.top_up(self.kandy_user, '5000')
        self.assertEqual(req.status, 'approved')
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('5000'))
        self.assertEqual(services.get_balance(self.w.main.pk), 0)
        self.assertTrue(req.number.startswith('PCR-'))
        self.assertTrue(AuditLog.objects.filter(action='petty_cash.review').exists())

    def test_main_office_can_request_and_another_manager_approves(self):
        req = services.create_request(fake_request(self.w.officer), D('3000'), '')
        services.review_request(fake_request(self.manager), req.pk, approve=True, amount=D('3000'), note='')
        self.assertEqual(services.get_balance(self.w.main.pk), D('3000'))

    def test_reduced_or_rejected_requests(self):
        req = services.create_request(fake_request(self.kandy_user), D('5000'), '')
        done = services.review_request(fake_request(self.manager), req.pk, approve=True, amount=D('2000'), note='Tight budget')
        self.assertEqual((done.status, done.amount_approved), ('approved', D('2000')))
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('2000'))
        req2 = services.create_request(fake_request(self.kandy_user), D('500'), '')
        done2 = services.review_request(fake_request(self.manager), req2.pk, approve=False, amount=None, note='Not needed')
        self.assertEqual(done2.status, 'rejected')
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('2000'))

    def test_a_request_is_reviewed_only_once(self):
        req = services.create_request(fake_request(self.kandy_user), D('100'), '')
        services.review_request(fake_request(self.manager), req.pk, approve=True, amount=D('100'), note='')
        with self.assertRaises(Conflict):
            services.review_request(fake_request(self.manager), req.pk, approve=True, amount=D('100'), note='')
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('100'))

    def test_manager_cannot_approve_their_own_request_but_super_admin_can(self):
        req = services.create_request(fake_request(self.manager), D('100'), '')
        with self.assertRaises(Conflict):
            services.review_request(fake_request(self.manager), req.pk, approve=True, amount=D('100'), note='')
        mine = services.create_request(fake_request(self.w.admin), D('100'), '')
        services.review_request(fake_request(self.w.admin), mine.pk, approve=True, amount=D('100'), note='')
        self.assertEqual(services.get_balance(self.w.main.pk), D('100'))

    def test_branch_users_cannot_approve(self):
        req = services.create_request(fake_request(self.kandy_user), D('100'), '')
        with self.assertRaises(Forbidden):
            services.review_request(fake_request(self.kandy_user), req.pk, approve=True, amount=D('100'), note='')

    def test_spending_reduces_the_balance_and_cannot_overspend(self):
        self.top_up(self.kandy_user, '1000')
        services.record_expense(fake_request(self.kandy_user), D('400'), 'Printer paper', None)
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('600'))
        with self.assertRaises(BadRequest):
            services.record_expense(fake_request(self.kandy_user), D('600.01'), 'Too much', None)
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('600'))

    def test_cancelling_an_expense_puts_the_money_back_once(self):
        self.top_up(self.kandy_user, '1000')
        e = services.record_expense(fake_request(self.kandy_user), D('400'), 'Pens', None)
        services.cancel_expense(fake_request(self.kandy_user), e.pk)
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('1000'))
        with self.assertRaises(Conflict):
            services.cancel_expense(fake_request(self.kandy_user), e.pk)
        self.assertEqual(PettyCashEntry.objects.filter(type='reversal').count(), 1)

    def test_entries_are_append_only(self):
        self.top_up(self.kandy_user, '100')
        e = PettyCashEntry.objects.first()
        with self.assertRaises(RuntimeError):
            e.delete()
        with self.assertRaises(RuntimeError):
            PettyCashEntry.objects.update(amount=1)

    def test_branch_user_sees_only_their_own_branch(self):
        req = services.create_request(fake_request(self.w.officer), D('100'), '')
        with self.assertRaises(NotFound):
            services.get_request(self.kandy_user, req.pk)
        self.assertEqual([s['branch'].pk for s in services.branch_summaries(self.kandy_user)], [self.w.kandy.pk])
        self.assertEqual({s['branch'].pk for s in services.branch_summaries(self.manager)}, {self.w.main.pk, self.w.kandy.pk})

    def test_default_low_level_is_2000_and_can_be_changed(self):
        self.assertEqual(services.get_low_level(), D('2000'))
        by_branch = {s['branch'].pk: s for s in services.branch_summaries(self.manager)}
        self.assertTrue(by_branch[self.w.kandy.pk]['low'])
        self.top_up(self.kandy_user, '2500')
        self.assertFalse({s['branch'].pk: s for s in services.branch_summaries(self.manager)}[self.w.kandy.pk]['low'])
        services.set_low_level(fake_request(self.manager), D('3000'))
        self.assertTrue({s['branch'].pk: s for s in services.branch_summaries(self.manager)}[self.w.kandy.pk]['low'])
        with self.assertRaises(BadRequest):
            services.set_low_level(fake_request(self.manager), D('-1'))


class PageTests(TestCase):
    def setUp(self):
        self.w = make_world()
        self.manager = User.objects.create_user(
            email='manager@example.test', password=PASSWORD, name='Manager', role=ROLES.STOCK_OFFICER, branch=self.w.main,
            permissions=['petty_cash.view', 'petty_cash.approve', 'petty_cash.configure'])
        self.kandy_user = self.w.branch_user
        self.kandy_user.permissions = ['petty_cash.request']
        self.kandy_user.save()

    def login(self, email):
        self.client.post(reverse('accounts:login'), {'email': email, 'password': PASSWORD})

    def test_pages_need_sign_in_and_the_right_feature(self):
        self.assertEqual(self.client.get(reverse('pettycash:overview')).status_code, 302)
        self.login('officer@example.test')   # default Stock Officer: can request, cannot approve or configure
        self.assertEqual(self.client.get(reverse('pettycash:overview')).status_code, 200)
        self.assertEqual(self.client.get(reverse('pettycash:settings')).status_code, 403)

    def test_full_flow_through_the_pages(self):
        self.login('kandy@example.test')
        self.assertEqual(self.client.get(reverse('pettycash:request_create')).status_code, 200)
        r = self.client.post(reverse('pettycash:request_create'), {'amount': '4500', 'purpose': 'Cleaning items'})
        self.assertEqual(r.status_code, 302)
        from pettycash.models import PettyCashRequest
        req = PettyCashRequest.objects.get()
        self.assertEqual(self.client.get(reverse('pettycash:request_review', args=[req.pk])).status_code, 403)
        self.client.post(reverse('accounts:logout'))

        self.login('manager@example.test')
        self.assertEqual(self.client.get(reverse('pettycash:overview')).status_code, 200)
        self.assertEqual(self.client.get(reverse('pettycash:request_detail', args=[req.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('pettycash:request_review', args=[req.pk])).status_code, 200)
        r = self.client.post(reverse('pettycash:request_review', args=[req.pk]), {'decision': 'approve', 'amount': '4500', 'note': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('4500'))
        self.assertEqual(self.client.get(reverse('pettycash:ledger')).status_code, 200)
        self.assertEqual(self.client.get(reverse('pettycash:request_list')).status_code, 200)
        r = self.client.post(reverse('pettycash:settings'), {'level': '2500'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Setting.get().petty_cash_low_level, D('2500'))
        self.client.post(reverse('accounts:logout'))

        self.login('kandy@example.test')
        self.assertEqual(self.client.get(reverse('pettycash:overview')).status_code, 200)
        r = self.client.post(reverse('pettycash:expense_create'), {'amount': '500', 'description': 'Mops', 'entry_date': '2026-01-05'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(services.get_balance(self.w.kandy.pk), D('4000'))
        self.assertEqual(self.client.get(reverse('pettycash:ledger')).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_bad_amounts_show_errors(self):
        self.login('kandy@example.test')
        r = self.client.post(reverse('pettycash:request_create'), {'amount': '-5'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Enter an amount above zero')
        r = self.client.post(reverse('pettycash:expense_create'), {'amount': '10', 'description': 'x'})
        self.assertContains(r, 'Only Rs. 0.00 is available')

    def test_manager_dashboard_and_settings_page(self):
        self.login('manager@example.test')
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('pettycash:settings')).status_code, 200)
