"""`manage.py migrate`, then lock this app's tables away from Supabase's Data API (see core.supabase_lockdown)."""
from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connections

from core.supabase_lockdown import lockdown_data_api


class Command(MigrateCommand):
    def handle(self, *args, **options):
        result = super().handle(*args, **options)
        if getattr(settings, 'SUPABASE_LOCKDOWN_DATA_API', True):
            alias = options.get('database') or 'default'
            outcome = lockdown_data_api(connections[alias], app_role=getattr(settings, 'DB_APP_ROLE', '') or None)
            if outcome['tables'] and options.get('verbosity', 1) >= 1:
                self.stdout.write(self.style.SUCCESS(
                    f"Data API lockdown: {outcome['tables']} tables checked, row level security newly enabled on "
                    f"{outcome['rls_enabled']}, grants revoked from {', '.join(outcome['revoked_roles']) or 'no API roles (none exist here)'}."))
        return result
