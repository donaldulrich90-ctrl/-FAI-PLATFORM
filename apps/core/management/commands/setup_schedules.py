"""
Enregistre les tâches planifiées django-q2 en base de données.
Idempotent : peut être relancé sans dupliquer les tâches.

Utilisation :
    python manage.py setup_schedules
    python manage.py setup_schedules --list
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


SCHEDULES = [
    {
        "name": "Rapports revendeurs quotidiens",
        "func": "apps.finance.tasks.generate_daily_revendeur_reports",
        "schedule_type": "C",  # CRON
        "cron": "0 1 * * *",  # 01h00 chaque nuit (Africa/Ouagadougou)
        "repeats": -1,
    },
    {
        "name": "Synchronisation santé PtP (Zabbix)",
        "func": "apps.monitoring.tasks.sync_ptp_health",
        "schedule_type": "C",
        "cron": "*/10 * * * *",  # toutes les 10 minutes
        "repeats": -1,
    },
    {
        "name": "Synchronisation hotspot MikroTik",
        "func": "apps.wifi_zone.tasks.sync_mikrotik_hotspot",
        "schedule_type": "C",
        "cron": "*/30 * * * *",  # toutes les 30 minutes
        "repeats": -1,
    },
    {
        "name": "Vérification abonnements revendeurs",
        "func": "apps.accounts.tasks.check_revendeur_subscriptions",
        "schedule_type": "C",
        "cron": "0 8 * * *",  # 08h00 chaque matin
        "repeats": -1,
    },
    {
        "name": "Rappels paiement abonnés domicile",
        "func": "apps.wifi_zone.tasks.check_payment_alerts",
        "schedule_type": "C",
        "cron": "0 8 * * *",  # 08h00 chaque matin
        "repeats": -1,
    },
    {
        "name": "Suspension automatique abonnés expirés",
        "func": "apps.wifi_zone.tasks.auto_kick_expired_subscribers",
        "schedule_type": "C",
        "cron": "0 * * * *",  # toutes les heures
        "repeats": -1,
    },
    {
        "name": "Surveillance fréquences Ubiquiti",
        "func": "apps.monitoring.tasks.monitor_frequencies",
        "schedule_type": "C",
        "cron": "*/5 * * * *",  # toutes les 5 minutes
        "repeats": -1,
    },
]


class Command(BaseCommand):
    help = "Enregistre (ou met à jour) les tâches planifiées django-q2 en base de données."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Affiche les tâches planifiées existantes sans rien modifier.",
        )

    def handle(self, *args, **options):
        from django_q.models import Schedule

        if options["list"]:
            existing = Schedule.objects.all().order_by("name")
            if not existing.exists():
                self.stdout.write(self.style.WARNING("Aucune tâche planifiée enregistrée."))
                return
            self.stdout.write(self.style.MIGRATE_HEADING(f"{existing.count()} tâche(s) planifiée(s) :"))
            for s in existing:
                next_run = s.next_run.strftime("%Y-%m-%d %H:%M") if s.next_run else "—"
                self.stdout.write(f"  • {s.name}  [{s.cron or s.schedule_type}]  prochaine : {next_run}")
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Configuration des tâches planifiées django-q2…"))
        created_count = 0
        updated_count = 0

        for item in SCHEDULES:
            name = item["name"]
            defaults = {k: v for k, v in item.items() if k != "name"}
            _, created = Schedule.objects.update_or_create(name=name, defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(f"  {self.style.SUCCESS('créée')}   {name}")
            else:
                updated_count += 1
                self.stdout.write(f"  {self.style.WARNING('màj')}      {name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTerminé : {created_count} créées, {updated_count} mises à jour."
            )
        )
