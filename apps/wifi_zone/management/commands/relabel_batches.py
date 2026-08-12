"""
Commande de gestion : relabel_batches

Met à jour le label de tous les WifiTicketBatch existants selon le nouveau
format :
    SELLER_NAME — DURATION_SHORT — TOTAL XOF — Tirage n°N

Usage :
    python manage.py relabel_batches
    python manage.py relabel_batches --dry-run   # aperçu sans sauvegarder
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.wifi_zone.models import WifiTicketBatch

_DURATION_SHORT: dict[str, str] = {
    "3h": "3h",
    "1d": "24h",
    "5j": "5j",
    "1w": "7j",
    "30j": "30j",
    "illimite": "illim.",
}


def _fmt_xof(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def _build_label(seller_name: str, duration: str, quantity: int, unit_price_xof: Decimal, tirage: int) -> str:
    dur_short = _DURATION_SHORT.get(duration, duration)
    total = int(Decimal(str(unit_price_xof)) * quantity)
    return f"{seller_name} — {dur_short} — {_fmt_xof(total)} XOF — Tirage n°{tirage}"


class Command(BaseCommand):
    help = "Renomme tous les lots de tickets selon le format : REVENDEUR — DURÉE — TOTAL XOF — Tirage n°N"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les changements sans les sauvegarder.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]

        # Récupère tous les lots triés par date de création (ordre chronologique)
        # pour que le numéro de tirage corresponde à l'ordre réel de génération.
        batches = list(
            WifiTicketBatch.objects.select_related("created_by")
            .order_by("created_at")
        )

        # Compteurs par (seller_pk, duration) → tirage courant
        counters: dict[tuple, int] = defaultdict(int)
        updated = 0

        for batch in batches:
            if batch.created_by_id is None:
                self.stdout.write(
                    self.style.WARNING(f"  Lot #{batch.pk} sans revendeur — ignoré.")
                )
                continue

            key = (batch.created_by_id, batch.duration)
            counters[key] += 1
            tirage = counters[key]

            seller_name = (
                batch.created_by.get_full_name() or batch.created_by.username
            ).upper()

            new_label = _build_label(
                seller_name=seller_name,
                duration=batch.duration,
                quantity=batch.quantity,
                unit_price_xof=batch.unit_price_xof,
                tirage=tirage,
            )

            if batch.label == new_label:
                continue  # déjà à jour

            action = "DRY-RUN" if dry_run else "MIS À JOUR"
            self.stdout.write(
                f"  [{action}] Lot #{batch.pk} : {batch.label!r}\n"
                f"            → {new_label!r}"
            )

            if not dry_run:
                batch.label = new_label
                batch.save(update_fields=["label"])
            updated += 1

        suffix = " (dry-run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{updated} lot(s) {'à mettre à jour' if dry_run else 'mis à jour'}{suffix}."
            )
        )
