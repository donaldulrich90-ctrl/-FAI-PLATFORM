"""Orchestration de l'achat de tickets Wi-Fi Zone en ligne (Mobile Money).

Chaîne complète :
    1. Le portail captif d'une zone POST/GET vers /wifi/acheter/ (avec site_code).
    2. On résout le Site, on relit le prix OFFICIEL (WifiZoneTarif) — jamais le
       prix envoyé par le client — et on crée une WifiPurchase (PENDING).
    3. On ouvre le guichet CinetPay (AWAITING) et on redirige le client.
    4. À la confirmation (webhook notify OU page de retour), on VÉRIFIE le statut
       auprès de CinetPay, puis on finalise : création du ticket, provisioning
       sur le MikroTik de la zone, crédit fidélité. Opération IDEMPOTENTE.

La recette comptable et l'expiration calendaire ne démarrent qu'à la première
connexion du client (comme pour un ticket revendeur vendu) : ce module ne crée
donc pas d'écriture de caisse, il délivre seulement le ticket prêt à l'emploi.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def resolve_site_by_code(site_code: str):
    """Retrouve un Site par son site_id (insensible à la casse), sinon par son nom."""
    from apps.core.models import Site

    code = (site_code or "").strip()
    if not code:
        return None
    site = Site.objects.filter(site_id__iexact=code).first()
    if site is not None:
        return site
    return Site.objects.filter(name__iexact=code).first()


def resolve_price(site, duration) -> "Decimal | None":
    """Prix officiel (XOF) pour ce site + durée, via la grille WifiZoneTarif."""
    from apps.wifi_zone.models import WifiZoneTarif

    return WifiZoneTarif.resolve_price(site, duration)


def create_pending_purchase(
    *,
    site,
    duration: str,
    amount,
    provider: str = "unknown",
    phone: str = "",
    mac_address: str = "",
    client_ip: str | None = None,
    login_url: str = "",
    destination_url: str = "",
):
    """Crée une transaction PENDING (avant tout appel externe)."""
    from apps.wifi_zone.models import WifiPurchase

    valid_providers = set(WifiPurchase.Provider.values)
    if provider not in valid_providers:
        provider = WifiPurchase.Provider.UNKNOWN

    return WifiPurchase.objects.create(
        site=site,
        duration=duration,
        amount_xof=Decimal(amount),
        provider=provider,
        phone=(phone or "")[:32],
        mac_address=(mac_address or "")[:17],
        client_ip=client_ip or None,
        login_url=(login_url or "")[:512],
        destination_url=(destination_url or "")[:512],
        status=WifiPurchase.Status.PENDING,
    )


def start_checkout(purchase, *, notify_url: str, return_url: str) -> str:
    """Ouvre le guichet CinetPay et passe la transaction en AWAITING.

    Renvoie l'URL du guichet. Lève CinetPayError si l'initialisation échoue.
    """
    from apps.wifi_zone.models import WifiPurchase
    from apps.wifi_zone.services.payments import cinetpay

    channels = "CREDIT_CARD" if purchase.provider == WifiPurchase.Provider.CARD else "ALL"
    duration_label = dict(purchase._meta.get_field("duration").choices).get(
        purchase.duration, purchase.duration
    )
    result = cinetpay.initiate_payment(
        transaction_id=purchase.reference,
        amount=purchase.amount_xof,
        description=f"Ticket WiFi Zone {duration_label} ({purchase.site.site_id})",
        notify_url=notify_url,
        return_url=return_url,
        customer_phone=purchase.phone,
        channels=channels,
        metadata=f"site={purchase.site.site_id};dur={purchase.duration}",
    )
    purchase.payment_token = result["payment_token"][:128]
    purchase.payment_url = result["payment_url"][:512]
    purchase.status = WifiPurchase.Status.AWAITING
    purchase.raw_init = str(result.get("raw", ""))[:5000]
    purchase.save(update_fields=["payment_token", "payment_url", "status", "raw_init", "updated_at"])
    return purchase.payment_url


def _provision_purchase_ticket(purchase):
    """Crée (si besoin) le ticket de la transaction et le pousse sur le MikroTik.

    Idempotent : si le ticket existe déjà, on ne le recrée pas ; on retente
    seulement le provisioning tant qu'il n'a pas réussi.
    """
    from apps.wifi_zone.models import Ticket
    from apps.wifi_zone.router_control import (
        normalize_mac,
        provision_wifi_zone_hotspot_for_ticket,
    )
    from apps.wifi_zone.services.loyalty import record_confirmed_purchase

    ticket = purchase.ticket
    created = False
    if ticket is None:
        mac = normalize_mac(purchase.mac_address) if purchase.mac_address else ""
        ticket = Ticket.objects.create(
            duration=purchase.duration,
            price_xof=purchase.amount_xof,
            site=purchase.site,
            sold_by=None,               # vente en ligne directe (pas de revendeur → 0 commission)
            sold_at=timezone.now(),
            status=Ticket.Status.AVAILABLE,
            is_used=False,
            hotspot_password="",
            mac_address=mac or None,
        )
        purchase.ticket = ticket
        purchase.save(update_fields=["ticket", "updated_at"])
        created = True

    # Provisioning MikroTik du site (retenté tant que non synchronisé).
    if ticket.hotspot_synced_at is None:
        ok, err = provision_wifi_zone_hotspot_for_ticket(ticket)
        if ok:
            Ticket.objects.filter(pk=ticket.pk).update(
                hotspot_synced_at=timezone.now(), hotspot_sync_error=""
            )
            ticket.hotspot_synced_at = timezone.now()
        else:
            Ticket.objects.filter(pk=ticket.pk).update(
                hotspot_sync_error=(err or "Échec provisionnement.")[:512]
            )
            logger.error(
                "Achat %s : provisioning MikroTik échoué ticket=%s : %s",
                purchase.reference, ticket.pk, err,
            )

    # Crédit fidélité (Mobile Money confirmé) — idempotent par ticket source.
    if created and purchase.mac_address:
        try:
            from apps.wifi_zone.models import LoyaltyPurchaseEvent
            with transaction.atomic():
                record_confirmed_purchase(
                    ticket,
                    mac_address=purchase.mac_address,
                    payment_method=LoyaltyPurchaseEvent.PaymentMethod.MOBILE_MONEY,
                )
        except Exception:
            logger.exception("Fidélité non créditée pour l'achat %s", purchase.reference)

    return ticket


def finalize_successful_purchase(purchase, *, payment_method: str = "", operator_id: str = ""):
    """Marque la transaction payée et délivre le ticket. Idempotent et verrouillé."""
    from apps.wifi_zone.models import WifiPurchase
    from apps.wifi_zone.services.payments import cinetpay

    with transaction.atomic():
        purchase = WifiPurchase.objects.select_for_update().get(pk=purchase.pk)
        if purchase.status == WifiPurchase.Status.SUCCESS and purchase.ticket_id:
            # Déjà finalisée : on retente juste le provisioning si nécessaire.
            _provision_purchase_ticket(purchase)
            return purchase

        if payment_method:
            mapped = cinetpay.map_payment_method(payment_method)
            if mapped != "unknown":
                purchase.provider = mapped
        if operator_id:
            purchase.operator_id = operator_id[:128]
        purchase.status = WifiPurchase.Status.SUCCESS
        purchase.paid_at = purchase.paid_at or timezone.now()
        purchase.error_message = ""
        purchase.save(update_fields=["provider", "operator_id", "status", "paid_at", "error_message", "updated_at"])
        _provision_purchase_ticket(purchase)

    return purchase


def mark_failed(purchase, *, status: str = "failed", reason: str = ""):
    """Marque une transaction comme non aboutie (échec, annulation, expiration)."""
    from apps.wifi_zone.models import WifiPurchase

    valid = {
        WifiPurchase.Status.FAILED,
        WifiPurchase.Status.CANCELLED,
        WifiPurchase.Status.EXPIRED,
    }
    new_status = status if status in valid else WifiPurchase.Status.FAILED
    with transaction.atomic():
        purchase = WifiPurchase.objects.select_for_update().get(pk=purchase.pk)
        if purchase.status == WifiPurchase.Status.SUCCESS:
            return purchase  # ne jamais dégrader une transaction déjà payée
        purchase.status = new_status
        purchase.error_message = (reason or "")[:512]
        purchase.save(update_fields=["status", "error_message", "updated_at"])
    return purchase


def refresh_from_cinetpay(purchase):
    """Interroge CinetPay et applique le résultat (finalise / échec). Renvoie le statut."""
    from apps.wifi_zone.models import WifiPurchase
    from apps.wifi_zone.services.payments import cinetpay

    if purchase.status == WifiPurchase.Status.SUCCESS:
        return purchase.status

    result = cinetpay.check_payment(purchase.reference)
    WifiPurchase.objects.filter(pk=purchase.pk).update(raw_notify=str(result.get("raw", ""))[:5000])

    if result["status"] == "ACCEPTED":
        finalize_successful_purchase(
            purchase,
            payment_method=result.get("payment_method", ""),
            operator_id=result.get("operator_id", ""),
        )
        return WifiPurchase.Status.SUCCESS
    if result["status"] == "REFUSED":
        mark_failed(purchase, status=WifiPurchase.Status.FAILED, reason="Paiement refusé par l'opérateur.")
        return WifiPurchase.Status.FAILED
    return purchase.status  # PENDING / UNKNOWN → on laisse en attente
