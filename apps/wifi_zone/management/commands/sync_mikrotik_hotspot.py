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
            fetch_mikrotik_hotspot_active_details,
            fetch_mikrotik_hotspot_all_users,
        )
        from apps.wifi_zone.services.ticket_activation import (
            maybe_expire_ticket,
            record_ticket_activation,
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
            active_details = fetch_mikrotik_hotspot_active_details(device)
            active_by_user = {
                row.get("user", ""): row for row in active_details if row.get("user")
            }
            active_users = set(active_by_user)
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
                        f"  ✓ {code} — actif sur routeur → activation (USED)"
                    )
                    if not dry_run:
                        ticket_now = timezone.now()
                        session = active_by_user.get(code, {})
                        mac_address = session.get("mac-address") or None
                        client_ip = session.get("address") or None
                        tracking = {}
                        if mac_address:
                            tracking["mac_address"] = mac_address
                        if client_ip:
                            tracking["client_ip"] = client_ip
                        Ticket.objects.filter(pk=ticket.pk).update(
                            status=Ticket.Status.USED,
                            is_used=True,
                            hotspot_synced_at=ticket_now,
                            hotspot_sync_error="",
                            **tracking,
                        )
                        # Estampille used_at / first_used_at si pas déjà renseignés
                        Ticket.objects.filter(pk=ticket.pk, used_at__isnull=True).update(
                            used_at=ticket_now,
                        )
                        Ticket.objects.filter(
                            pk=ticket.pk, first_used_at__isnull=True
                        ).update(first_used_at=ticket_now)
                        # Recette + archive-preuve (idempotent) sur l'objet complet
                        full_ticket = Ticket.objects.get(pk=ticket.pk)
                        record_ticket_activation(
                            full_ticket,
                            activated_at=ticket_now,
                            mac_address=mac_address,
                            client_ip=client_ip,
                        )
                    total_synced += 1

                elif is_active and ticket.status == Ticket.Status.USED:
                    # Une activation plus ancienne peut ne pas encore avoir sa MAC.
                    # Rejouer l'archive est sans danger et crédite la fidélité une seule fois.
                    if not dry_run:
                        session = active_by_user.get(code, {})
                        mac_address = session.get("mac-address") or None
                        client_ip = session.get("address") or None
                        if mac_address:
                            tracking = {"mac_address": mac_address}
                            if client_ip:
                                tracking["client_ip"] = client_ip
                            Ticket.objects.filter(pk=ticket.pk).update(**tracking)
                            full_ticket = Ticket.objects.get(pk=ticket.pk)
                            record_ticket_activation(
                                full_ticket,
                                mac_address=mac_address,
                                client_ip=client_ip,
                            )

                elif is_provisioned and not is_active and ticket.hotspot_synced_at is None:
                    # Provisionné mais pas de session active — mettre à jour synced_at
                    if not dry_run:
                        Ticket.objects.filter(pk=ticket.pk).update(
                            hotspot_synced_at=now,
                            hotspot_sync_error="",
                        )

                elif ticket.status == Ticket.Status.USED and not is_provisioned:
                    # USED en DB mais absent du routeur : expirer si la validité
                    # calendaire est écoulée (sinon on laisse tel quel).
                    if not dry_run:
                        full_ticket = Ticket.objects.get(pk=ticket.pk)
                        if maybe_expire_ticket(full_ticket):
                            self.stdout.write(
                                f"  ⌛ {code} — validité écoulée → marqué Expiré"
                            )
                        else:
                            self.stdout.write(
                                f"  ⚠ {code} — USED en DB mais absent du routeur"
                            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSync terminé : {total_synced} tickets mis à jour, {total_errors} erreurs."
            )
        )
