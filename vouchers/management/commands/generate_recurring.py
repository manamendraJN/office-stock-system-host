from django.core.management.base import BaseCommand, CommandError

from core.errors import ServiceError
from vouchers.services import generate_due_schedules


class Command(BaseCommand):
    help = 'Generate payment vouchers for due recurring schedules.'

    def handle(self, *args, **options):
        try:
            generated, errors = generate_due_schedules()
        except ServiceError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(f'Generated {generated} payment voucher(s).')
        for error in errors:
            self.stderr.write(self.style.WARNING(error))
