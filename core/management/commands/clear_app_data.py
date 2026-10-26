"""Clears catalog, stock, document, audit and counter data. Keeps users, roles, branches and settings.
Refused in production (DJANGO_DEBUG off), and needs an interactive terminal where you type the database name."""
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


class Command(BaseCommand):
    help = 'Remove operational, stock, audit, catalog and counter data (development use only).'

    def handle(self, *args, **options):
        from branchops.models import Dispatch, Request
        from catalog.models import Category, Item, Supplier
        from core.models import AuditLog, Counter
        from inventory.models import OfficeIssue, Purchase, StockLedger

        if not settings.DEBUG:
            raise CommandError('Data clearing is disabled unless DJANGO_DEBUG is on (it is off in production).')
        db_name = str(connection.settings_dict['NAME'])
        short = db_name.replace('\\', '/').rsplit('/', 1)[-1]
        self.stdout.write(f'Database: {db_name}')
        self.stdout.write('This removes operational, stock, audit, catalog, and counter data.')
        self.stdout.write('Users, their role assignments, role definitions, all branches (including main), and settings are preserved.')
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise CommandError('Run this command in an interactive terminal to confirm the database name.')
        answer = input(f'Type "{short}" to continue: ').strip()
        if answer != short:
            raise CommandError('Database name did not match. No data was deleted.')

        with transaction.atomic():
            # Documents that refer to catalog items go first. Dispatches point at requests, so they go before them.
            for model in (Dispatch, Request, Purchase, OfficeIssue):
                n = model.objects.all().delete()[0]
                self.stdout.write(f'{model._meta.label}: deleted {n}')
            # Append-only tables: this explicit clean-up is one of the deliberate exceptions.
            for model in (StockLedger, AuditLog):
                n = model.objects.all().unsafe_delete()
                self.stdout.write(f'{model._meta.label}: deleted {n}')
            for model in (Item, Supplier, Category, Counter):
                n = model.objects.all().delete()[0]
                self.stdout.write(f'{model._meta.label}: deleted {n}')
        self.stdout.write(self.style.SUCCESS('Cleanup complete. Users, roles, branches, and settings were preserved.'))
