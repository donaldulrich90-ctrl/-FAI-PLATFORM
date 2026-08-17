"""Reprise historique des activations de tickets Wi-Fi Zone.

Crée rétroactivement, pour chaque ticket DÉJÀ consommé (statut Utilisé ou
Expiré) qui n'a pas encore d'archive :
  • l'écriture de caisse (recette = net FAI)  → preuve comptable
  • la fiche d'archive TicketConsommation      → preuve détaillée

À lancer UNE FOIS après la migration, pour garder la continuité des recettes
(les tickets consommés avant la mise en place de l'enregistrement automatique).
Idempotent : les tickets déjà archivés sont ignorés.

Utilisation :
    python manage.py backfill_ticket_activations
    python manage.py backfill_ticket_activations --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Crée rétroactivement recettes + archives pour les tickets déjà activés."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les tickets concernés sans rien créer.",
        )

    def handle(self, *args, **options):
        from apps.wifi_zone.models import Ticket
        from apps.wifi_zone.services.ticket_activation import record_ticket_activation

        dry = options["dry_run"]

        qs = (
            Ticket.objects.filter(
                status__in=[Ticket.Status.USED, Ticket.Status.EXPIRED],
                consommation__isnull=True,
            )
            .select_related("site")
            .order_by("used_at", "created_at")
        )

        total = qs.count()
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"{total} ticket(s) consommé(s) sans archive"
                + (" — DRY-RUN (aucune écriture)" if dry else "")
            )
        )

        done = 0
        for ticket in qs.iterator():
            activated_at = ticket.first_used_at or ticket.used_at or ticket.created_at
            if dry:
                self.stdout.write(
                    f"  • {ticket.code} ({ticket.duration}) — activé {activated_at} "
                    f"— net {ticket.net_to_isp_xof} XOF"
                )
                continue

            archive = record_ticket_activation(ticket, activated_at=activated_at)

            # Marquer la date d'expiration effective pour les tickets déjà expirés.
            if (
                archive is not None
                and ticket.status == Ticket.Status.EXPIRED
                and archive.expired_at is None
            ):
                archive.expired_at = archive.expires_at or timezone.now()
                archive.save(update_fields=["expired_at"])
            done += 1

        if not dry:
            self.stdout.write(
                self.style.SUCCESS(f"\nTerminé : {done} archive(s) créée(s).")
            )
