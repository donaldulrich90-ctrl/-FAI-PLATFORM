"""
Génération de codes d'accès Wi-Fi Zone cryptographiquement sécurisés.

Utilise le module standard `secrets` (adapté aux jetons / mots de passe).
"""
from __future__ import annotations

import secrets
import string
from decimal import Decimal
from typing import TYPE_CHECKING

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

        if quantity < 1 or quantity > 200:
            raise ValueError("La quantité doit être entre 1 et 200.")

        prefix = (getattr(seller, "ticket_prefix", "") or "").strip().upper()
        if not prefix:
            raise ValueError("Le revendeur doit avoir un préfixe de ticket configuré.")

        existing_count = Ticket.objects.filter(code__startswith=prefix).count()
        start_num = existing_count + 1

        batch = WifiTicketBatch.objects.create(
            label=f"Lot revendeur {prefix} — {quantity} tickets",
            site=site,
            duration=duration,
            unit_price_xof=unit_price_xof,
            quantity=quantity,
            created_by=seller,
        )

        tickets: list[Ticket] = []
        passwords: dict[str, str] = {}

        for i in range(quantity):
            num = start_num + i
            code = f"{prefix}{num:04d}"
            for attempt in range(10):
                if not Ticket.objects.filter(code=code).exists():
                    break
                num += 1
                code = f"{prefix}{num:04d}"

            pwd = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            passwords[code] = pwd

            ticket = Ticket(
                code=code,
                hotspot_password=pwd,
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

                failed: list[str] = []
                try:
                    with RouterOSClient(device) as client:
                        for ticket in tickets:
                            ok, err = client.hotspot_user_add(
                                name=ticket.code,
                                password=passwords[ticket.code],
                                profile=profile,
                                limit_uptime=limit_uptime,
                                comment=f"faso-revendeur-{prefix}",
                                server=server,
                            )
                            if not ok:
                                failed.append(f"{ticket.code}: {err}")
                    if failed:
                        errors.extend(failed[:5])
                    log_router_action(
                        device,
                        "hotspot_batch",
                        target=f"{prefix} x{quantity}",
                        command_sent=f"hotspot user add x{quantity} profile={profile}",
                        success=not failed,
                        error_message="; ".join(failed[:3]),
                        dry_run=dry_run,
                        performed_by=seller,
                    )
                except RouterOSError as exc:
                    errors.append(f"Connexion MikroTik impossible : {exc}")

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
