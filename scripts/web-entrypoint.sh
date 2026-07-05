#!/bin/sh
set -e

cd /app

echo "Migrations…"
python manage.py migrate --noinput

echo "Tâches planifiées…"
python manage.py setup_schedules

if [ -n "${DJANGO_BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
  echo "Bootstrap admin (si DEBUG ou DJANGO_ALLOW_BOOTSTRAP_ADMIN)…"
  python manage.py bootstrap_admin
fi

if [ "${DJANGO_DEBUG:-0}" = "1" ]; then
  echo "Mode développement : runserver"
  exec python manage.py runserver 0.0.0.0:8000
fi

echo "Mode production : collectstatic + gunicorn"
python manage.py collectstatic --noinput

WORKERS="${GUNICORN_WORKERS:-3}"
exec gunicorn \
  --bind 0.0.0.0:8000 \
  --workers "${WORKERS}" \
  --timeout 120 \
  faso_isp_manager.wsgi:application
