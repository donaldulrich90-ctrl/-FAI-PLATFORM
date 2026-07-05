"""
Synchronise l'état des tickets Wi-Fi Zone avec les MikroTik connectés.

Pour chaque équipement MikroTik actif :
  1. Récupère les utilisateurs hotspot actifs (sessions en cours)
  2. Récupère tous les utilisateurs hotspot provisionnés
  3. Met à jour hotspot_synced_at et le statut des tickets en DB

Utilisation :
    python manage.py sync_mikrotik_hotspot
    python manage.py sync_mikrotik_hotspot --site SITE_ID
    python manage.py sync_mikrotik_hotspot --dry-run
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronise les tickets Wi-Fi Zone avec les routeurs MikroTik."

    def add_arguments(self, parser):
        parser.add_argument(
            "--site",
            type=str,
            metavar="SITE_ID",
            help="Limiter à un site spécifique (site_id).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les actions sans modifier la base de données.",
        )

    def handle(self, *args, **options):
        from apps.core.models import NetworkDevice
        from apps.wifi_zone.models import Ticket
        from apps.wifi_zone.router_control import (
            fetch_mikrotik_hotspot_active_users,
            fetch_mikrotik_hotspot_all_users,
        )

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode DRY-RUN activé — aucune modification."))

        devices_qs = NetworkDevice.objects.filter(
            vendor=NetworkDevice.Vendor.MIKROTIK,
            is_active=True,
        ).select_related("site")

        if options["site"]:
            devices_qs = devices_qs.filter(site__site_id=options["site"])

        if not devices_qs.exists():
            self.stdout.write(self.style.WARNING("Aucun équipement MikroTik actif trouvé."))
            return

        now = timezone.now()
        total_synced = 0
        total_errors = 0

        for device in devices_qs:
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"\n[{device.site.site_id}] {device.name} — {device.management_host}"
                )
            )

            # 1. Utilisateurs actuellement connectés
            active_users = fetch_mikrotik_hotspot_active_users(device)
            self.stdout.write(f"  Sessions actives sur le routeur : {len(active_users)}")

            # 2. Tous les utilisateurs provisionnés
            all_users = fetch_mikrotik_hotspot_all_users(device)
            provisioned_codes = {u["name"] for u in all_users}
            self.stdout.write(f"  Vouchers provisionnés sur le routeur : {len(provisioned_codes)}")

            # 3. Tickets du site concerné
            site_tickets = Ticket.objects.filter(site=device.site).only(
                "pk", "code", "status", "is_used", "hotspot_synced_at", "hotspot_sync_error"
            )

            for ticket in site_tickets:
                code = ticket.code
                is_active = code in active_users
                is_provisioned = code in provisioned_codes

                if is_active and ticket.status != Ticket.Status.USED:
                    # Le code est actif sur le routeur mais pas marqué USED en DB
                    self.stdout.write(
                        f"  ✓ {code} — actif sur routeur → marquer USED"
                    )
                    if not dry_run:
                        Ticket.objects.filter(pk=ticket.pk).update(
                            status=Ticket.Status.USED,
                            is_used=True,
                            hotspot_synced_at=now,
                            hotspot_sync_error="",
                        )
                    total_synced += 1

                elif is_provisioned and not is_active and ticket.hotspot_synced_at is None:
                    # Provisionné mais pas de session active — mettre à jour synced_at
                    if not dry_run:
                        Ticket.objects.filter(pk=ticket.pk).update(
                            hotspot_synced_at=now,
                            hotspot_sync_error="",
                        )

                elif ticket.status == Ticket.Status.USED and not is_provisioned:
                    # Le ticket est USED en DB mais n'existe plus sur le routeur
                    self.stdout.write(
                        f"  ⚠ {code} — USED en DB mais absent du routeur (expiré ?)"
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSync terminé : {total_synced} tickets mis à jour, {total_errors} erreurs."
            )
        )
