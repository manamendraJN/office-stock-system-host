#!/bin/sh
# Start-up sequence for the cloud container. Fails loudly (set -e) rather than serving a half-prepared database.
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  # Cache table first, so the migrate step below also locks it away from Supabase's Data API.
  [ "${DJANGO_CACHE_BACKEND:-locmem}" = "database" ] && python manage.py createcachetable
  python manage.py migrate --noinput
fi

# Creates the first Super Admin only when SEED_ADMIN_PASSWORD is set (idempotent); remove that variable afterwards.
if [ -n "${SEED_ADMIN_PASSWORD:-}" ]; then
  python manage.py seed
fi

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" --threads "${WEB_THREADS:-4}" \
  --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 \
  --access-logfile - --error-logfile -
