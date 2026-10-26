"""Runs the 30-day stock movement retention job (same job the scheduled /maintenance/ URL runs)."""
from django.core.management.base import BaseCommand

from inventory.services.retention import prune_old_stock_movements


class Command(BaseCommand):
    help = 'Replace stock movements older than 30 days with opening balances.'

    def handle(self, *args, **options):
        r = prune_old_stock_movements()
        if r.get('skipped'):
            self.stdout.write('Another cleanup is already running. Nothing done.')
            return
        self.stdout.write(self.style.SUCCESS(
            f"Removed {r['deleted_count']} old movements, wrote {r['opening_balance_count']} opening balances (cutoff {r['cutoff']:%Y-%m-%d %H:%M})."))
