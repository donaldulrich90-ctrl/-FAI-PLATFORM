"""Programme de fidélité Wi-Fi, indexé par MAC et forfait exact."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

LOYALTY_THRESHOLD = 5


def _provision_bonus_ticket(ticket_id: int) -> None:
    """Provisionne le bonus après validation de la transaction DB."""
    from apps.wifi_zone.models import Ticket
    from apps.wifi_zone.router_control import provision_wifi_zone_hotspot_for_ticket

    try:
        ticket = Ticket.objects.select_related("site").get(pk=ticket_id)
        ok, error = provision_wifi_zone_hotspot_for_ticket(ticket)
        if ok:
            Ticket.objects.filter(pk=ticket_id).update(
                hotspot_synced_at=timezone.now(), hotspot_sync_error=""
            )
        else:
            Ticket.objects.filter(pk=ticket_id).update(
                hotspot_synced_at=None,
                hotspot_sync_error=(error or "Échec provisionnement du bonus.")[:512],
            )
    except Exception:
        logger.exception("Provisionnement du ticket bonus pk=%s", ticket_id)


@transaction.atomic
def record_confirmed_purchase(
    ticket,
    *,
    mac_address: str,
    payment_method: str = "unknown",
):
    """Compte un ticket payé une seule fois et crée le bonus au cinquième.

    La clé du compteur est (site, MAC, durée, prix). Deux prix ou deux durées
    différents ne sont donc jamais additionnés. Les tickets gratuits ne
    progressent pas dans le programme.
    """
    from apps.wifi_zone.models import LoyaltyProgress, LoyaltyPurchaseEvent, Ticket
    from apps.wifi_zone.router_control import normalize_mac
    from apps.wifi_zone.services.wifi_access_code import WifiAccessCodeService

    if ticket.pk is None:
        raise ValueError("Le ticket doit être enregistré avant le calcul du bonus.")
    if Decimal(ticket.price_xof or 0) <= 0:
        return None

    mac = normalize_mac(mac_address)
    existing = (
        LoyaltyPurchaseEvent.objects.select_related("progress", "bonus_ticket")
        .filter(source_ticket=ticket)
        .first()
    )
    if existing is not None:
        return existing

    progress, _ = LoyaltyProgress.objects.select_for_update().get_or_create(
        tenant_id=getattr(ticket.site, "tenant_id", None),
        site=ticket.site,
        mac_address=mac,
        duration=ticket.duration,
        plan_price_xof=ticket.price_xof,
        defaults={"paid_count": 0, "bonus_count": 0},
    )

    # Une notification concurrente peut avoir créé l'événement pendant
    # l'attente du verrou sur le compteur. Recontrôler avant d'incrémenter.
    existing = (
        LoyaltyPurchaseEvent.objects.select_related("progress", "bonus_ticket")
        .filter(source_ticket=ticket)
        .first()
    )
    if existing is not None:
        return existing

    next_count = progress.paid_count + 1
    bonus_ticket = None
    if next_count >= LOYALTY_THRESHOLD:
        next_count = 0
        progress.bonus_count += 1
        code = WifiAccessCodeService().generate_unique_code(prefix="BONUS")
        bonus_ticket = Ticket.objects.create(
            code=code,
            hotspot_password="",
            duration=ticket.duration,
            price_xof=Decimal("0"),
            site=ticket.site,
            sold_by=ticket.sold_by,
            sold_at=timezone.now(),
            status=Ticket.Status.AVAILABLE,
            is_used=False,
            mac_address=mac,
        )

    progress.paid_count = next_count
    progress.save(update_fields=["paid_count", "bonus_count", "updated_at"])

    event = LoyaltyPurchaseEvent.objects.create(
        progress=progress,
        source_ticket=ticket,
        payment_method=payment_method,
        bonus_ticket=bonus_ticket,
    )

    if bonus_ticket is not None:
        transaction.on_commit(lambda ticket_id=bonus_ticket.pk: _provision_bonus_ticket(ticket_id))

    return event
