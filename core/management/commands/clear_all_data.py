"""Deletes ALL data except the Super Admin account(s). Development only (needs DJANGO_DEBUG=true).

    python manage.py clear_all_data          # asks you to type the database name
    python manage.py clear_all_data --yes    # no question (scripts)

Removed: every document, stock movement, audit entry, petty cash record, item, category, supplier, counter,
every non-Super-Admin user and every branch that has no Super Admin in it.
Kept: Super Admin accounts, the main office, role definitions and settings (company name, switches, low petty cash level).
"""
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.constants import BRANCH_TYPES, ROLES


class Command(BaseCommand):
    help = 'Delete all data except the Super Admin account(s), the main office, roles and settings (development only).'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Do not ask for confirmation.')

    def handle(self, *args, **options):
        from accounts.models import Branch, User
        from branchops.models import Dispatch, Request
        from catalog.models import Category, Item, Supplier
        from core.models import AuditLog, Counter
        from inventory.models import OfficeIssue, Purchase, StockLedger
        from pettycash.models import PettyCashEntry, PettyCashRequest

        if not settings.DEBUG:
            raise CommandError('Clearing data is disabled unless DJANGO_DEBUG is on (it is off in production).')
        if not User.objects.filter(role=ROLES.SUPER_ADMIN).exists():
            raise CommandError('There is no Super Admin account. Nothing was deleted, so you cannot lock yourself out.')

        db_name = str(connection.settings_dict['NAME'])
        short = db_name.replace('\\', '/').rsplit('/', 1)[-1]
        if not options['yes']:
            self.stdout.write(f'Database: {db_name}')
            self.stdout.write('This deletes EVERYTHING except Super Admin account(s), the main office, roles and settings.')
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise CommandError('Run this in an interactive terminal, or pass --yes.')
            if input(f'Type "{short}" to continue: ').strip() != short:
                raise CommandError('Database name did not match. No data was deleted.')

        keep_branches = set(User.objects.filter(role=ROLES.SUPER_ADMIN).values_list('branch_id', flat=True))
        keep_branches |= set(Branch.objects.filter(type=BRANCH_TYPES.MAIN).values_list('pk', flat=True))

        def report(label, n):
            self.stdout.write(f'{label}: deleted {n}')

        with transaction.atomic():
            # Documents first (dispatches point at requests). Append-only tables use the deliberate clean-up path.
            for model in (PettyCashEntry, StockLedger, AuditLog):
                report(model._meta.label, model.objects.all().unsafe_delete())
            for model in (PettyCashRequest, Dispatch, Request, Purchase, OfficeIssue, Item, Supplier, Category, Counter):
                report(model._meta.label, model.objects.all().delete()[0])
            report('accounts.User', User.objects.exclude(role=ROLES.SUPER_ADMIN).delete()[0])
            report('accounts.Branch', Branch.objects.exclude(pk__in=keep_branches).delete()[0])
        self.stdout.write(self.style.SUCCESS('Done. Only the Super Admin account(s), the main office, roles and settings remain.'))
