#!/bin/sh
set -e

cd /app

echo "Migrations…"
python manage.py migrate --noinput

echo "Tâches planifiées…"
python manage.py setup_schedules

echo "Démarrage du worker django-q2 (qcluster)…"
exec python manage.py qcluster
