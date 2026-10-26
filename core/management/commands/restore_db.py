import gzip
import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Safely restores an SQLite database from a compressed or uncompressed backup file.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Path to the backup file (.sqlite3 or .sqlite3.gz)',
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Skip confirmation prompt',
        )

    def handle(self, *args, **options):
        db_conf = settings.DATABASES['default']
        if 'sqlite3' not in db_conf['ENGINE']:
            raise CommandError('restore_db command currently supports SQLite databases.')

        target_path = Path(db_conf['NAME'])
        backup_path = Path(options['file'])

        if not backup_path.exists():
            raise CommandError(f'Backup file not found: {backup_path}')

        if not options['yes']:
            confirm = input(f'WARNING: This will overwrite the current database at {target_path}. Proceed? [y/N]: ')
            if confirm.strip().lower() not in ('y', 'yes'):
                self.stdout.write(self.style.NOTICE('Restore cancelled.'))
                return

        # Prepare uncompressed temporary source
        temp_restore = backup_path.parent / '_temp_restore.sqlite3'
        try:
            if backup_path.suffix == '.gz':
                self.stdout.write(f'Decompressing {backup_path.name}...')
                with gzip.open(backup_path, 'rb') as f_in, open(temp_restore, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                source_db = temp_restore
            else:
                source_db = backup_path

            self.stdout.write(f'Restoring to {target_path}...')
            target_path.parent.mkdir(parents=True, exist_ok=True)

            src_conn = sqlite3.connect(str(source_db))
            dst_conn = sqlite3.connect(str(target_path))
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

            self.stdout.write(self.style.SUCCESS(f'Database restored successfully from {backup_path.name}!'))
        finally:
            temp_restore.unlink(missing_ok=True)
