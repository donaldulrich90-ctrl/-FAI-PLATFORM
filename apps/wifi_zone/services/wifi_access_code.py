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
