"""Tâches planifiées django-q2 pour l'app wifi_zone."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

logger = logging.getLogger(__name__)


def sync_mikrotik_hotspot():
    from django.core.management import call_command

    logger.info("Synchronisation hotspot MikroTik…")
    call_command("sync_mikrotik_hotspot")
    logger.info("Synchronisation hotspot MikroTik terminée.")


def auto_kick_expired_subscribers():
    """
    Tâche horaire : détecte les abonnés expirés (statut actif/nouveau), tente
    le kick airOS via SSH, met le statut à 'suspendu' et envoie le WhatsApp.
    """
    from apps.core.models import NetworkDevice
    from apps.monitoring.services.ubiquiti_ssh_monitor import kick_station
    from apps.notifications.whatsapp import WhatsAppService, msg_suspension
    from apps.wifi_zone.models import WiFiSimpleSubscriber
    from django.utils import timezone

    now = timezone.now()
    expired = list(
        WiFiSimpleSubscriber.objects.filter(
            expires_at__lt=now,
            status__in=["actif", "nouveau"],
            is_active=True,
        ).select_related("cpe_device__parent_mikrotik", "plan", "site")
    )

    if not expired:
        logger.info("auto_kick_expired_subscribers : aucun abonné expiré.")
        return

    svc = WhatsAppService()
    kicked = 0

    for sub in expired:
        # Kick airOS : tente via les antennes Ubiquiti associées au MikroTik du CPE
        if sub.mac_address and sub.cpe_device:
            dev = sub.cpe_device
            if dev.vendor == "ubiquiti" and dev.ssh_forward_port:
                antennas = [dev]
            else:
                antennas = list(
                    NetworkDevice.objects.filter(
                        parent_mikrotik=dev,
                        vendor="ubiquiti",
                        is_active=True,
                        ssh_forward_port__isnull=False,
                    )
                )
            for ant in antennas:
                result = kick_station(ant, sub.mac_address)
                if result["ok"]:
                    kicked += 1
                    break
                logger.warning(
                    "auto_kick %s sur %s : %s",
                    sub.mac_address, ant, result.get("error"),
                )

        sub.status = WiFiSimpleSubscriber.Status.SUSPENDU
        sub.save(update_fields=["status", "updated_at"])

        expires_str = sub.expires_at.strftime("%d/%m/%Y")
        prix = f"{int(sub.plan.price_xof)} XOF" if sub.plan else "—"
        msg = msg_suspension(sub.full_name, expires_str, prix)
        tenant_id = sub.site.tenant_id if sub.site else None
        ok, err = svc.send(sub.effective_whatsapp_phone, msg, tenant_id=tenant_id)
        if not ok:
            logger.warning("WhatsApp suspension %s : %s", sub, err)

    logger.info(
        "auto_kick_expired_subscribers : %d expirés traités, %d kicks réussis.",
        len(expired), kicked,
    )


def check_payment_alerts():
    """
    Tâche quotidienne (8h) : envoie les rappels de paiement WhatsApp J-2 et J-1.
    """
    from apps.notifications.whatsapp import WhatsAppService, msg_rappel_j1, msg_rappel_j2
    from apps.wifi_zone.models import WiFiSimpleSubscriber
    from django.utils import timezone

    today = timezone.now().date()

    j1_start = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    j1_end   = timezone.make_aware(datetime.combine(today + timedelta(days=2), time.min))
    j2_start = timezone.make_aware(datetime.combine(today + timedelta(days=2), time.min))
    j2_end   = timezone.make_aware(datetime.combine(today + timedelta(days=3), time.min))

    svc = WhatsAppService()
    sent_j1 = sent_j2 = 0

    for sub in WiFiSimpleSubscriber.objects.filter(
        expires_at__gte=j1_start,
        expires_at__lt=j1_end,
        status="actif",
        is_active=True,
    ).select_related("plan", "site"):
        prix = f"{int(sub.plan.price_xof)} XOF" if sub.plan else "—"
        msg = msg_rappel_j1(sub.full_name, sub.expires_at.strftime("%d/%m/%Y"), prix)
        tenant_id = sub.site.tenant_id if sub.site else None
        svc.send(sub.effective_whatsapp_phone, msg, tenant_id=tenant_id)
        sent_j1 += 1

    for sub in WiFiSimpleSubscriber.objects.filter(
        expires_at__gte=j2_start,
        expires_at__lt=j2_end,
        status="actif",
        is_active=True,
    ).select_related("plan", "site"):
        prix = f"{int(sub.plan.price_xof)} XOF" if sub.plan else "—"
        plan_name = sub.plan.name if sub.plan else "—"
        msg = msg_rappel_j2(sub.full_name, sub.expires_at.strftime("%d/%m/%Y"), plan_name, prix)
        tenant_id = sub.site.tenant_id if sub.site else None
        svc.send(sub.effective_whatsapp_phone, msg, tenant_id=tenant_id)
        sent_j2 += 1

    logger.info(
        "check_payment_alerts : J-1=%d envoyés, J-2=%d envoyés.", sent_j1, sent_j2
    )
