"""Tâches planifiées django-q2 pour l'app wifi_zone."""
import logging

logger = logging.getLogger(__name__)


def sync_mikrotik_hotspot():
    from django.core.management import call_command

    logger.info("Synchronisation hotspot MikroTik…")
    call_command("sync_mikrotik_hotspot")
    logger.info("Synchronisation hotspot MikroTik terminée.")
