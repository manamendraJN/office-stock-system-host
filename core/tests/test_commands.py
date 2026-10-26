"""The sample-data and clear-all commands."""
from io import StringIO
import os
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import Branch, User
from branchops.models import Dispatch, Request
from catalog.models import Item, Supplier
from core.constants import ROLES
from core.models import AuditLog, Setting
from accounts.roles import ensure_default_roles
from core.tests.helpers import PASSWORD
from types import SimpleNamespace
from inventory.models import OfficeIssue, Purchase, StockLedger
from pettycash.models import PettyCashRequest
from pettycash.services import get_balance


def minimal_world():
    """What `manage.py seed` leaves behind: default roles, the main office and one Super Admin."""
    ensure_default_roles()
    main = Branch.objects.create(code='NUG', name='Main Office', type='main')
    admin = User.objects.create_user(email='admin@example.test', password=PASSWORD, name='Admin', role=ROLES.SUPER_ADMIN, branch=main)
    return SimpleNamespace(main=main, admin=admin)


def run(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


@override_settings(DEBUG=True)
class SampleDataCommandTests(TestCase):
    def setUp(self):
        self.w = minimal_world()


    def test_loads_five_of_each_and_refuses_a_second_run(self):
        run('seed_sample_data')
        self.assertEqual(Branch.objects.exclude(type='main').count(), 5)
        self.assertEqual(User.objects.exclude(pk=self.w.admin.pk).count(), 5)
        for model in (Item, Supplier, Purchase, Request, Dispatch, OfficeIssue, PettyCashRequest):
            self.assertEqual(model.objects.count(), 5, model.__name__)
        self.assertFalse(StockLedger.objects.filter(quantity_change=0).exists())
        with self.assertRaises(CommandError):
            run('seed_sample_data')

    def test_petty_cash_balances_are_consistent(self):
        run('seed_sample_data')
        kandy = Branch.objects.get(code='KDY')
        self.assertEqual(int(get_balance(kandy.pk)), 1500)  # 4000 received, 2500 spent
        self.assertEqual(int(get_balance(self.w.main.pk)), 3500)

    @override_settings(DEBUG=False)
    def test_refused_in_production(self):
        with self.assertRaises(CommandError):
            run('seed_sample_data')
        with self.assertRaises(CommandError):
            run('clear_all_data', '--yes')


@override_settings(DEBUG=True)
class ClearAllDataCommandTests(TestCase):
    def setUp(self):
        self.w = minimal_world()
        run('seed_sample_data')

    def test_keeps_only_super_admin_main_office_roles_and_settings(self):
        run('clear_all_data', '--yes')
        self.assertEqual(list(User.objects.values_list('pk', flat=True)), [self.w.admin.pk])
        self.assertEqual(list(Branch.objects.values_list('pk', flat=True)), [self.w.main.pk])
        for model in (Item, Supplier, Purchase, Request, Dispatch, OfficeIssue, PettyCashRequest, StockLedger, AuditLog):
            self.assertEqual(model.objects.count(), 0, model.__name__)
        self.assertTrue(Setting.objects.exists())
        from accounts.models import Role
        self.assertTrue(Role.objects.exists())

    def test_can_load_again_after_clearing(self):
        run('clear_all_data', '--yes')
        run('seed_sample_data')
        self.assertEqual(Item.objects.count(), 5)

    def test_refuses_when_there_is_no_super_admin(self):
        User.objects.filter(role=ROLES.SUPER_ADMIN).update(role=ROLES.VIEWER)
        with self.assertRaises(CommandError):
            run('clear_all_data', '--yes')
        self.assertTrue(Item.objects.exists())


class SeedPasswordPolicyTests(TestCase):
    def test_seed_refuses_a_weak_initial_admin_password(self):
        values = {
            'SEED_ADMIN_NAME': 'Initial Admin',
            'SEED_ADMIN_EMAIL': 'initial-admin@example.test',
            'SEED_ADMIN_PASSWORD': '123456789012',
        }
        with patch.dict(os.environ, values):
            with self.assertRaises(CommandError):
                call_command('seed', stdout=StringIO())
