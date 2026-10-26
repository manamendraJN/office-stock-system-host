"""Creates the main office, the first Super Admin, starter categories, settings and default roles.
Safe to run more than once.   Usage: python manage.py seed
Set SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD (environment or .env) to choose the first login."""
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Branch, User
from accounts.roles import ensure_default_roles
from catalog.models import Category
from core.constants import BRANCH_TYPES, ROLES
from core.models import Setting

STARTER_CATEGORIES = ['Paper', 'Pens and Pencils', 'Printer Ink and Toner', 'Stationery', 'Equipment']


class Command(BaseCommand):
    help = 'Create the main office, first Super Admin, starter categories, settings and default roles (idempotent).'

    def handle(self, *args, **options):
        email = (os.environ.get('SEED_ADMIN_EMAIL') or 'admin@example.com').strip().lower()
        password = os.environ.get('SEED_ADMIN_PASSWORD')
        name = os.environ.get('SEED_ADMIN_NAME') or 'Super Admin'

        with transaction.atomic():
            settings_row = Setting.get()
            company = os.environ.get('SEED_COMPANY_NAME')
            if company and settings_row.company_name == 'Our Company':
                settings_row.company_name = company
                settings_row.save(update_fields=['company_name', 'updated_at'])

            main = Branch.objects.filter(type=BRANCH_TYPES.MAIN).first()
            if main is None:
                main = Branch.objects.create(code='NUG', name='Main Office - Nugegoda', type=BRANCH_TYPES.MAIN)
                self.stdout.write(f'Created main office: {main.name}')

            if not User.objects.filter(email=email).exists():
                if not password:
                    raise CommandError('Set SEED_ADMIN_PASSWORD (at least 12 characters) to choose the first Super Admin password, then run the seed again.')
                if len(password) < 12:
                    raise CommandError('SEED_ADMIN_PASSWORD must be at least 12 characters.')
                try:
                    validate_password(password, user=User(name=name, email=email))
                except ValidationError as exc:
                    raise CommandError('SEED_ADMIN_PASSWORD does not meet the password policy: '
                                       + '; '.join(exc.messages)) from None
                User.objects.create_user(email=email, password=password, name=name, role=ROLES.SUPER_ADMIN, branch=main)
                self.stdout.write(f'Created Super Admin: {email}')
            else:
                self.stdout.write(f'Super Admin already exists: {email}')

            for cat in STARTER_CATEGORIES:
                Category.objects.get_or_create(name=cat)
            ensure_default_roles()
        self.stdout.write(self.style.SUCCESS('Seed complete. Change the admin password after first sign-in if it was ever shared.'))
