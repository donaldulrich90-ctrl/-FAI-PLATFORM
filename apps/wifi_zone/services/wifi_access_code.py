"""
Génération de codes d'accès Wi-Fi Zone cryptographiquement sécurisés.

Utilise le module standard `secrets` (adapté aux jetons / mots de passe).
"""
from __future__ import annotations

import secrets
import string
from decimal import Decimal
from typing import TYPE_CHECKING

# Libellés courts pour les durées de ticket
_DURATION_SHORT: dict[str, str] = {
    "2h": "2h",
    "3h": "3h",
    "4h": "4h",
    "1d": "24h",
    "5j": "5j",
    "1w": "7j",
    "30j": "30j",
    "illimite": "illim.",
}

from django.db import transaction

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from apps.wifi_zone.models import Ticket, WifiTicketBatch


class WifiAccessCodeService:
    """Service centralisé pour créer des codes uniques et des lots de tickets."""

    DEFAULT_ALPHABET = string.ascii_uppercase + string.digits
    DEFAULT_CODE_LENGTH = 10   # longueur sans préfixe
    SUFFIX_LENGTH = 8           # longueur du suffixe quand un préfixe est fourni
    MAX_COLLISION_RETRIES = 64

    def __init__(
        self,
        *,
        alphabet: str | None = None,
        code_length: int | None = None,
    ) -> None:
        self.alphabet = alphabet or self.DEFAULT_ALPHABET
        self.code_length = code_length or self.DEFAULT_CODE_LENGTH

    def generate_single_code(self, prefix: str = "") -> str:
        """Génère un code aléatoire (unicité DB non vérifiée).
        Avec préfixe : PREFIX-XXXXXXXX (8 chars). Sans : 10 chars."""
        length = self.SUFFIX_LENGTH if prefix else self.code_length
        suffix = "".join(secrets.choice(self.alphabet) for _ in range(length))
        return f"{prefix}-{suffix}" if prefix else suffix

    def generate_unique_code(self, exclude: set[str] | None = None, prefix: str = "") -> str:
        """Génère un code absent de la table `Ticket` (et de `exclude`)."""
        from apps.wifi_zone.models import Ticket

        exclude = exclude or set()
        for _ in range(self.MAX_COLLISION_RETRIES):
            candidate = self.generate_single_code(prefix=prefix)
            if candidate in exclude:
                continue
            if not Ticket.objects.filter(code=candidate).exists():
                return candidate
            exclude.add(candidate)
        raise RuntimeError(
            "Impossible de générer un code unique après "
            f"{self.MAX_COLLISION_RETRIES} tentatives."
        )

    @transaction.atomic
    def create_revendeur_batch(
        self,
        *,
        site,
        duration: str,
        unit_price_xof,
        quantity: int,
        seller,
        profile: str,
        push_to_mikrotik: bool = True,
    ) -> tuple[list, list[str]]:
        """
        Génère un lot de tickets revendeur avec username=PREFIX+NUM, password aléatoire.
        Pousse vers MikroTik si push_to_mikrotik=True.
        Retourne (tickets_créés, erreurs_push).
        """
        from apps.wifi_zone.models import Ticket, WifiTicketBatch
        from apps.wifi_zone.router_control import (
            resolve_wifi_zone_mikrotik_for_site,
            duration_to_hotspot_limit_uptime,
        )
        from apps.core.services.routeros_client import RouterOSClient, RouterOSError
        from apps.monitoring.audit import log_router_action
        from django.conf import settings

        if quantity < 1 or quantity > 100:
            raise ValueError("La quantité doit être entre 1 et 100.")

        prefix = (getattr(seller, "ticket_prefix", "") or "").strip().upper()
        if not prefix:
            raise ValueError("Le revendeur doit avoir un préfixe de ticket configuré.")

        # Numéro de tirage = nombre de lots existants pour ce revendeur + cette durée + 1
        tirage = WifiTicketBatch.objects.filter(
            created_by=seller,
            duration=duration,
        ).count() + 1
        seller_name = (seller.get_full_name() or seller.username).upper()
        dur_short = _DURATION_SHORT.get(duration, duration)
        total_xof = int(Decimal(str(unit_price_xof)) * quantity)
        total_fmt = f"{total_xof:,}".replace(",", " ")  # espace fine insécable
        batch_label = f"{seller_name} — {dur_short} — {total_fmt} XOF — Tirage n°{tirage}"

        batch = WifiTicketBatch.objects.create(
            label=batch_label,
            site=site,
            duration=duration,
            unit_price_xof=unit_price_xof,
            quantity=quantity,
            created_by=seller,
        )

        tickets: list[Ticket] = []
        codes_reserved: set[str] = set()

        for _ in range(quantity):
            # Mikhmon style: PREFIX + 4 random digits, e.g. SOR1234
            for attempt in range(self.MAX_COLLISION_RETRIES):
                code = f"{prefix}{secrets.randbelow(10000):04d}"
                if code not in codes_reserved and not Ticket.objects.filter(code=code).exists():
                    break
            else:
                raise RuntimeError(
                    f"Impossible de générer un code unique pour le préfixe '{prefix}' "
                    f"après {self.MAX_COLLISION_RETRIES} tentatives (espace saturé)."
                )
            codes_reserved.add(code)

            ticket = Ticket(
                code=code,
                hotspot_password="",  # Mikhmon : username = password = code
                duration=duration,
                price_xof=unit_price_xof,
                site=site,
                batch=batch,
                status=Ticket.Status.AVAILABLE,
                is_used=False,
                sold_by=seller,
                commission_rate_percent=seller.default_commission_percent,
            )
            ticket.compute_commission_amounts()
            ticket.save()
            tickets.append(ticket)

        errors: list[str] = []
        if push_to_mikrotik:
            device = resolve_wifi_zone_mikrotik_for_site(site)
            if device is None:
                errors.append("Aucun MikroTik actif pour ce site — tickets créés en DB uniquement.")
            else:
                try:
                    limit_uptime = duration_to_hotspot_limit_uptime(duration)
                except ValueError as e:
                    errors.append(str(e))
                    limit_uptime = "3h"

                dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
                server = (getattr(settings, "MIKROTIK_HOTSPOT_SERVER", "") or "").strip()

                from django.utils import timezone as _tz
                from apps.wifi_zone.models import Ticket as _Ticket

                failed: list[str] = []
                try:
                    now_sync = _tz.now()
                    with RouterOSClient(device) as client:
                        for ticket in tickets:
                            # Mikhmon : username = password = code (idempotent)
                            ok, err = client.hotspot_user_upsert(
                                name=ticket.code,
                                password=ticket.code,
                                profile=profile,
                                limit_uptime=limit_uptime,
                                comment=f"faso-revendeur-{prefix}",
                                server=server,
                            )
                            if ok:
                                _Ticket.objects.filter(pk=ticket.pk).update(
                                    hotspot_synced_at=now_sync,
                                    hotspot_sync_error="",
                                )
                            else:
                                failed.append(f"{ticket.code}: {err}")
                                _Ticket.objects.filter(pk=ticket.pk).update(
                                    hotspot_synced_at=None,
                                    hotspot_sync_error=err[:512],
                                )
                    if failed:
                        errors.extend(failed[:5])
                    log_router_action(
                        device,
                        "hotspot_batch",
                        target=f"{prefix} x{quantity}",
                        command_sent=f"hotspot user upsert x{quantity} profile={profile}",
                        success=not failed,
                        error_message="; ".join(failed[:3]),
                        dry_run=dry_run,
                        performed_by=seller,
                    )
                except RouterOSError as exc:
                    conn_err = f"Connexion MikroTik impossible : {exc}"
                    errors.append(conn_err)
                    _Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(
                        hotspot_synced_at=None,
                        hotspot_sync_error=str(exc)[:512],
                    )

        return tickets, errors

    @transaction.atomic
    def create_ticket_batch(
        self,
        *,
        batch: WifiTicketBatch,
        count: int | None = None,
        seller: AbstractUser | None = None,
    ) -> list[Ticket]:
        """Crée des tickets liés au lot `batch` avec codes uniques.
        Si le vendeur est un revendeur avec ticket_prefix, les codes utilisent ce préfixe."""
        from apps.wifi_zone.models import Ticket

        n = count if count is not None else batch.quantity
        if n < 1 or n > 500:
            raise ValueError("Le nombre de tickets doit être entre 1 et 500.")

        prefix = ""
        if seller is not None and getattr(seller, "is_revendeur", False):
            prefix = (getattr(seller, "ticket_prefix", "") or "").strip().upper()

        created: list[Ticket] = []
        codes_reserved: set[str] = set()
        for _ in range(n):
            code = self.generate_unique_code(exclude=codes_reserved, prefix=prefix)
            codes_reserved.add(code)
            ticket = Ticket(
                code=code,
                duration=batch.duration,
                price_xof=batch.unit_price_xof,
                site=batch.site,
                batch=batch,
                status=Ticket.Status.AVAILABLE,
                is_used=False,
            )
            if seller is not None:
                ticket.sold_by = seller
                if getattr(seller, "is_revendeur", False):
                    ticket.commission_rate_percent = seller.default_commission_percent
            ticket.compute_commission_amounts()
            ticket.save()
            created.append(ticket)
        return created
