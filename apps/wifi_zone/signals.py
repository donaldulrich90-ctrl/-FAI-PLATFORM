from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from apps.wifi_zone.models import Ticket, WiFiSimpleSubscriber
from apps.wifi_zone.router_control import (
    provision_wifi_zone_hotspot_for_ticket,
    remove_wifi_zone_hotspot_for_ticket,
    sync_wifi_simple_subscriber_access,
)

logger = logging.getLogger(__name__)


def _ticket_grants_access(t: Ticket) -> bool:
    """Accès Hotspot actif : utilisé et non expiré / retiré côté statut."""
    if t.status == Ticket.Status.EXPIRED:
        return False
    return t.status == Ticket.Status.USED or t.is_used


@receiver(pre_save, sender=Ticket)
def wifi_zone_ticket_cache_previous(sender, instance: Ticket, **kwargs) -> None:
    instance._wifi_zone_prev_access = None
    if instance.pk:
        try:
            old = Ticket.objects.only("status", "is_used").get(pk=instance.pk)
            instance._wifi_zone_prev_access = _ticket_grants_access(old)
        except Ticket.DoesNotExist:
            instance._wifi_zone_prev_access = False


@receiver(post_save, sender=Ticket)
def wifi_zone_ticket_sync_hotspot(
    sender,
    instance: Ticket,
    created,
    update_fields=None,
    **kwargs,
) -> None:
    """Utilisateur Hotspot : création quand le ticket est actif, suppression quand il est retiré / expiré."""
    if update_fields is not None:
        skip_only = {"hotspot_synced_at", "hotspot_sync_error", "updated_at"}
        if set(update_fields).issubset(skip_only):
            return

    now_access = _ticket_grants_access(instance)
    prev_access = getattr(instance, "_wifi_zone_prev_access", None)

    if now_access and prev_access is True:
        return
    if not now_access and prev_access is not True:
        return

    if now_access:
        try:
            ok, err_msg = provision_wifi_zone_hotspot_for_ticket(instance)
        except Exception:
            logger.exception("Hotspot Wi‑Fi Zone ticket pk=%s (provision)", instance.pk)
            Ticket.objects.filter(pk=instance.pk).update(
                hotspot_synced_at=None,
                hotspot_sync_error="Exception Python pendant le provisionnement.",
            )
            return

        if ok:
            Ticket.objects.filter(pk=instance.pk).update(
                hotspot_synced_at=timezone.now(),
                hotspot_sync_error="",
            )
        else:
            Ticket.objects.filter(pk=instance.pk).update(
                hotspot_synced_at=None,
                hotspot_sync_error=(err_msg or "Erreur inconnue.")[:512],
            )
            logger.warning("Échec provisionnement Hotspot ticket pk=%s : %s", instance.pk, err_msg)
        return

    try:
        ok, err_msg = remove_wifi_zone_hotspot_for_ticket(instance)
    except Exception:
        logger.exception("Hotspot Wi‑Fi Zone ticket pk=%s (retrait)", instance.pk)
        Ticket.objects.filter(pk=instance.pk).update(
            hotspot_sync_error="Exception Python pendant le retrait Hotspot.",
        )
        return

    if ok:
        Ticket.objects.filter(pk=instance.pk).update(
            hotspot_synced_at=None,
            hotspot_sync_error="",
        )
        logger.info("Utilisateur Hotspot retiré pour le ticket pk=%s", instance.pk)
    else:
        Ticket.objects.filter(pk=instance.pk).update(
            hotspot_sync_error=(err_msg or "Échec retrait Hotspot.")[:512],
        )
        logger.warning("Échec retrait Hotspot ticket pk=%s : %s", instance.pk, err_msg)


@receiver(post_save, sender=WiFiSimpleSubscriber)
def wifi_simple_subscriber_sync_router(
    sender,
    instance: WiFiSimpleSubscriber,
    created,
    update_fields=None,
    **kwargs,
):
    """Pousse blocage / déblocage sur le routeur (Mikrobatik, etc.) selon statut paiement."""
    if update_fields is not None:
        skip_only = {"last_billing_sync_at", "mac_blocked_on_network", "updated_at"}
        if set(update_fields).issubset(skip_only):
            return

    if not instance.mac_address or not instance.cpe_device_id:
        return

    device = instance.cpe_device
    if device is None:
        return

    device_id = device.pk
    now = timezone.now()
    should_allow = (
        instance.is_active
        and instance.is_payment_current
        and instance.expires_at > now
    )

    try:
        ok = sync_wifi_simple_subscriber_access(
            device,
            instance.mac_address,
            should_allow=should_allow,
        )
    except Exception:
        logger.exception(
            "Erreur sync routeur pour abonné pk=%s device=%s",
            instance.pk,
            device_id,
        )
        return
    if ok:
        WiFiSimpleSubscriber.objects.filter(pk=instance.pk).update(
            mac_blocked_on_network=not should_allow,
            last_billing_sync_at=timezone.now(),
        )
