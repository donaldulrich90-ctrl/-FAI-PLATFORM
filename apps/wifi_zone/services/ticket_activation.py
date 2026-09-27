"""Activation et expiration des tickets Wi-Fi Zone.

Règles métier :
  • Un ticket ne « pèse » dans les recettes qu'au moment où un client l'ACTIVE
    (première connexion), pas à sa fabrication ni à sa vente.
  • À l'activation on crée, de façon idempotente :
      1. une écriture de caisse (recette = net FAI)      → preuve comptable
      2. une fiche d'archive TicketConsommation           → preuve détaillée
  • La validité est calendaire : le ticket expire `activated_at + durée`,
    quel que soit le temps de connexion réellement consommé.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def _record_loyalty_safely(ticket, mac_address: str) -> None:
    """Crédite la fidélité sans compromettre l'archive comptable en cas d'erreur."""
    if not mac_address:
        return
    try:
        from apps.wifi_zone.models import LoyaltyPurchaseEvent
        from apps.wifi_zone.services.loyalty import record_confirmed_purchase

        method = (
            LoyaltyPurchaseEvent.PaymentMethod.CASH
            if ticket.sold_by_id
            else LoyaltyPurchaseEvent.PaymentMethod.UNKNOWN
        )
        with transaction.atomic():
            record_confirmed_purchase(
                ticket,
                mac_address=mac_address,
                payment_method=method,
            )
    except Exception:
        logger.exception("Fidélité non créditée pour le ticket=%s", ticket.pk)


def _entry_date_for(activated_at):
    """Date comptable (locale) pour une activation."""
    if activated_at is None:
        return timezone.localdate()
    if timezone.is_aware(activated_at):
        return timezone.localdate(activated_at)
    return activated_at.date()


@transaction.atomic
def record_ticket_activation(
    ticket,
    *,
    activated_at=None,
    mac_address: str | None = None,
    client_ip: str | None = None,
):
    """Enregistre l'activation d'un ticket (recette + archive-preuve).

    Idempotent : si le ticket a déjà une archive, ne fait rien et la renvoie.
    Renvoie l'objet TicketConsommation.
    """
    from apps.finance.models import CashJournalEntry
    from apps.wifi_zone.models import TicketConsommation, compute_ticket_expiry

    existing = TicketConsommation.objects.filter(ticket=ticket).first()
    if existing is not None:
        resolved_mac = (mac_address or existing.mac_address or "").strip()
        tracking_updates = {}
        if resolved_mac and not existing.mac_address:
            tracking_updates["mac_address"] = resolved_mac
            existing.mac_address = resolved_mac
        if client_ip and not existing.client_ip:
            tracking_updates["client_ip"] = client_ip
            existing.client_ip = client_ip
        if tracking_updates:
            TicketConsommation.objects.filter(pk=existing.pk).update(**tracking_updates)
        _record_loyalty_safely(ticket, resolved_mac)
        return existing

    activated_at = activated_at or ticket.first_used_at or ticket.used_at or timezone.now()
    site = ticket.site
    tenant_id = getattr(site, "tenant_id", None)
    expires_at = compute_ticket_expiry(activated_at, ticket.duration)
    mac = (mac_address or ticket.mac_address or "").strip()
    ip = client_ip or ticket.client_ip

    # 1) Écriture de caisse = recette (net FAI après commission revendeur).
    cash = None
    amount = ticket.net_to_isp_xof if ticket.net_to_isp_xof is not None else ticket.price_xof
    try:
        cash = CashJournalEntry(
            entry_type=CashJournalEntry.EntryType.INCOME,
            amount_xof=amount or 0,
            description=f"Activation ticket {ticket.code} ({ticket.get_duration_display()})",
            category="Ticket Wi-Fi Zone",
            entry_date=_entry_date_for(activated_at),
            site=site,
            created_by=ticket.sold_by,
        )
        cash.save()
    except Exception:
        logger.exception(
            "record_ticket_activation : échec écriture de caisse ticket=%s", ticket.pk
        )
        cash = None

    # 2) Archive-preuve détaillée.
    archive = TicketConsommation.objects.create(
        ticket=ticket,
        tenant_id=tenant_id,
        site=site,
        code=ticket.code,
        duration=ticket.duration,
        price_xof=ticket.price_xof or 0,
        commission_amount_xof=ticket.commission_amount_xof or 0,
        net_to_isp_xof=ticket.net_to_isp_xof or 0,
        sold_by=ticket.sold_by,
        mac_address=mac,
        client_ip=ip,
        activated_at=activated_at,
        expires_at=expires_at,
        cash_entry=cash,
    )
    logger.info(
        "Ticket %s activé : recette=%s XOF, expire=%s",
        ticket.code, amount, expires_at,
    )
    _record_loyalty_safely(ticket, mac)
    return archive


def maybe_expire_ticket(ticket, *, now=None) -> bool:
    """Passe le ticket à « Expiré » si sa validité calendaire est écoulée.

    S'appuie sur l'archive (date d'activation + expiration calculée).
    Renvoie True si le ticket vient d'être expiré. Idempotent.
    """
    from apps.wifi_zone.models import Ticket, TicketConsommation

    now = now or timezone.now()
    cons = TicketConsommation.objects.filter(ticket=ticket).first()
    if cons is None or cons.expires_at is None or cons.expires_at >= now:
        return False

    changed = False
    if ticket.status != Ticket.Status.EXPIRED:
        ticket.status = Ticket.Status.EXPIRED
        # save() (et non update()) pour déclencher le retrait du hotspot via signal.
        ticket.save(update_fields=["status", "is_used", "updated_at"])
        changed = True

    if cons.expired_at is None:
        cons.expired_at = now
        cons.save(update_fields=["expired_at"])

    return changed


def expire_due_tickets(now=None) -> int:
    """Expire tous les tickets activés dont la validité calendaire est écoulée.

    Renvoie le nombre de tickets nouvellement expirés.
    """
    from apps.wifi_zone.models import Ticket, TicketConsommation

    now = now or timezone.now()
    due = (
        TicketConsommation.objects.filter(
            expires_at__isnull=False,
            expires_at__lt=now,
            expired_at__isnull=True,
            ticket__isnull=False,
        )
        .select_related("ticket")
    )

    expired = 0
    for cons in due:
        ticket = cons.ticket
        if ticket is None:
            cons.expired_at = now
            cons.save(update_fields=["expired_at"])
            continue
        try:
            if maybe_expire_ticket(ticket, now=now):
                expired += 1
        except Exception:
            logger.exception("expire_due_tickets : échec sur ticket=%s", ticket.pk)
    return expired
