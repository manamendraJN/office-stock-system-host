import gzip
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Safely creates a compressed timestamped backup of the database and rotates old backups.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dest',
            type=str,
            default='',
            help='Directory to store the backup (default: <BASE_DIR>/backups or DB_BACKUP_DIR)',
        )
        parser.add_argument(
            '--keep-days',
            type=int,
            default=30,
            help='Days to retain backups before automatic rotation (default: 30 days)',
        )

    def handle(self, *args, **options):
        db_conf = settings.DATABASES['default']
        engine = db_conf['ENGINE']

        dest_dir = Path(options['dest'] or getattr(settings, 'DB_BACKUP_DIR', settings.BASE_DIR / 'backups'))
        dest_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')

        if 'sqlite3' in engine:
            db_path = Path(db_conf['NAME'])
            if not db_path.exists():
                raise CommandError(f'SQLite database not found at {db_path}')

            temp_dest = dest_dir / f'db_backup_{timestamp}.sqlite3'
            final_gz = dest_dir / f'db_backup_{timestamp}.sqlite3.gz'

            self.stdout.write(f'Backing up SQLite database: {db_path}...')
            # Use SQLite safe online backup API to prevent corruption during active writes
            src_conn = sqlite3.connect(str(db_path))
            dst_conn = sqlite3.connect(str(temp_dest))
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

            # Compress with gzip
            self.stdout.write(f'Compressing to {final_gz.name}...')
            with open(temp_dest, 'rb') as f_in, gzip.open(final_gz, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

            # Remove uncompressed temp
            temp_dest.unlink(missing_ok=True)
            size_kb = final_gz.stat().st_size / 1024
            self.stdout.write(self.style.SUCCESS(f'Backup created successfully: {final_gz} ({size_kb:.1f} KB)'))

        elif 'postgresql' in engine:
            final_gz = dest_dir / f'db_backup_{timestamp}.sql.gz'
            self.stdout.write(f'Backing up PostgreSQL database: {db_conf.get("NAME")}...')

            env = os.environ.copy()
            if db_conf.get('PASSWORD'):
                env['PGPASSWORD'] = db_conf['PASSWORD']

            pg_dump_cmd = [
                'pg_dump',
                '-h', db_conf.get('HOST', 'localhost'),
                '-p', str(db_conf.get('PORT', 5432)),
                '-U', db_conf.get('USER', 'postgres'),
                '-d', db_conf.get('NAME', 'postgres'),
            ]

            p1 = subprocess.Popen(pg_dump_cmd, stdout=subprocess.PIPE, env=env)
            with gzip.open(final_gz, 'wb') as f_out:
                shutil.copyfileobj(p1.stdout, f_out)
            p1.wait()

            if p1.returncode != 0:
                final_gz.unlink(missing_ok=True)
                raise CommandError(f'pg_dump failed with exit code {p1.returncode}')

            size_kb = final_gz.stat().st_size / 1024
            self.stdout.write(self.style.SUCCESS(f'Postgres backup created: {final_gz} ({size_kb:.1f} KB)'))
        else:
            raise CommandError(f'Unsupported database engine: {engine}')

        # Rotation of old backups
        keep_days = options['keep_days']
        if keep_days > 0:
            cutoff = now - timedelta(days=keep_days)
            removed = 0
            for backup_file in dest_dir.glob('db_backup_*.gz'):
                file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
                if file_mtime < cutoff:
                    backup_file.unlink(missing_ok=True)
                    removed += 1
            if removed > 0:
                self.stdout.write(self.style.NOTICE(f'Rotated {removed} old backup(s) older than {keep_days} days.'))
