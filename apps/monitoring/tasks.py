"""Tâches planifiées django-q2 pour l'app monitoring."""
import logging

logger = logging.getLogger(__name__)


def sync_ptp_health():
    from django.core.management import call_command

    logger.info("Synchronisation santé PtP depuis Zabbix…")
    call_command("sync_ptp_health")
    logger.info("Synchronisation santé PtP terminée.")
