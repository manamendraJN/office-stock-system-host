#!/usr/bin/env bash
# ==============================================================================
# Automated Database Backup Script for Office Stock System
# Can be run manually or via cron: 0 2 * * * /path/to/scripts/backup.sh
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Starting Database Backup ==="

# Execute backup_db command inside the running web container
docker compose exec -T web python manage.py backup_db --dest /srv/app/backups --keep-days 30

echo "=== Backup completed successfully. Files stored in: $PROJECT_ROOT/backups ==="
