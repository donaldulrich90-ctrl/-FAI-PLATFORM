"""Tâches planifiées django-q2 pour l'app finance."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_daily_revendeur_reports():
    from django.core.management import call_command

    logger.info("Génération rapports revendeurs quotidiens…")
    call_command("generate_daily_revendeur_reports")
    logger.info("Génération rapports revendeurs terminée.")


def send_expiry_reminders_j7() -> int:
    """Envoie rappel WhatsApp J-7 à tous les abonnés expirant dans 7 jours."""
    from apps.notifications.whatsapp import WhatsAppService, msg_rappel_j7
    from apps.wifi_zone.models import WiFiSimpleSubscriber

    now = timezone.now()
    qs = WiFiSimpleSubscriber.objects.filter(
        status=WiFiSimpleSubscriber.Status.ACTIF,
        expires_at__gte=now + timedelta(days=6, hours=23),
        expires_at__lte=now + timedelta(days=7, hours=1),
    ).select_related("plan", "site")

    svc = WhatsAppService()
    sent = 0
    for sub in qs:
        plan_name = sub.plan.name if sub.plan else "—"
        prix = str(sub.plan.price_xof) if sub.plan else "—"
        expires = sub.expires_at.strftime("%d/%m/%Y")
        ok, _ = svc.send(
            sub.effective_whatsapp_phone,
            msg_rappel_j7(sub.full_name, expires, plan_name, prix),
            tenant_id=getattr(sub.site, "tenant_id", None),
        )
        if ok:
            sent += 1
    logger.info("Rappels J-7 envoyés : %s", sent)
    return sent


def send_expiry_reminders_j1() -> int:
    """Envoie rappel urgent WhatsApp J-1 à tous les abonnés expirant demain."""
    from apps.notifications.whatsapp import WhatsAppService, msg_rappel_j1
    from apps.wifi_zone.models import WiFiSimpleSubscriber

    now = timezone.now()
    qs = WiFiSimpleSubscriber.objects.filter(
        status=WiFiSimpleSubscriber.Status.ACTIF,
        expires_at__gte=now + timedelta(hours=23),
        expires_at__lte=now + timedelta(hours=25),
    ).select_related("plan", "site")

    svc = WhatsAppService()
    sent = 0
    for sub in qs:
        prix = str(sub.plan.price_xof) if sub.plan else "—"
        expires = sub.expires_at.strftime("%d/%m/%Y")
        ok, _ = svc.send(
            sub.effective_whatsapp_phone,
            msg_rappel_j1(sub.full_name, expires, prix),
            tenant_id=getattr(sub.site, "tenant_id", None),
        )
        if ok:
            sent += 1
    logger.info("Rappels J-1 envoyés : %s", sent)
    return sent


def auto_suspend_expired_subscribers() -> int:
    """Suspend automatiquement les abonnés expirés (Jour J)."""
    from apps.notifications.whatsapp import WhatsAppService, msg_suspension
    from apps.wifi_zone.models import WiFiSimpleSubscriber
    from apps.wifi_zone.router_control import suspend_subscriber

    now = timezone.now()
    qs = WiFiSimpleSubscriber.objects.filter(
        status=WiFiSimpleSubscriber.Status.ACTIF,
        expires_at__lt=now,
    ).select_related("plan", "site", "cpe_device")

    svc = WhatsAppService()
    suspended = 0
    for sub in qs:
        ok, _ = suspend_subscriber(sub)
        if ok:
            prix = str(sub.plan.price_xof) if sub.plan else "—"
            expires = sub.expires_at.strftime("%d/%m/%Y")
            svc.send(
                sub.effective_whatsapp_phone,
                msg_suspension(sub.full_name, expires, prix),
                tenant_id=getattr(sub.site, "tenant_id", None),
            )
            suspended += 1
    logger.info("Abonnés suspendus automatiquement : %s", suspended)
    return suspended


def register_schedules() -> None:
    """
    Enregistre les tâches planifiées django-q2. Appeler une fois :
        from apps.finance.tasks import register_schedules; register_schedules()
    """
    from django_q.models import Schedule

    for func, name, cron in [
        ("apps.finance.tasks.send_expiry_reminders_j7", "Rappels WhatsApp J-7", "0 9 * * *"),
        ("apps.finance.tasks.send_expiry_reminders_j1", "Rappels WhatsApp J-1", "0 9 * * *"),
        ("apps.finance.tasks.auto_suspend_expired_subscribers", "Suspension auto abonnés expirés", "0 1 * * *"),
        ("apps.finance.tasks.generate_daily_revendeur_reports", "Rapports journaliers revendeurs", "0 23 * * *"),
    ]:
        Schedule.objects.get_or_create(func=func, defaults={
            "name": name,
            "schedule_type": Schedule.CRON,
            "cron": cron,
        })
    logger.info("Tâches planifiées enregistrées.")
