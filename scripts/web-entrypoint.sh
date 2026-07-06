#!/bin/sh
set -e

cd /app

echo "Migrations..."
python manage.py migrate --noinput

echo "Taches planifiees..."
python manage.py setup_schedules

if [ -n "${DJANGO_BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
  echo "Bootstrap admin..."
  python manage.py bootstrap_admin
fi

if [ "${DJANGO_DEBUG:-0}" = "1" ]; then
  echo "Mode developpement : runserver"
  exec python manage.py runserver 0.0.0.0:8000
fi

echo "Mode production : collectstatic + gunicorn + qcluster"
python manage.py collectstatic --noinput

WORKERS="${GUNICORN_WORKERS:-3}"

python manage.py qcluster &
QCLUSTER_PID=$!

gunicorn \
  --bind 0.0.0.0:8000 \
  --workers "${WORKERS}" \
  --timeout 120 \
  faso_isp_manager.wsgi:application

kill $QCLUSTER_PID