"""Tâches planifiées django-q2 pour l'app finance."""
import logging

logger = logging.getLogger(__name__)


def generate_daily_revendeur_reports():
    from django.core.management import call_command

    logger.info("Génération rapports revendeurs quotidiens…")
    call_command("generate_daily_revendeur_reports")
    logger.info("Génération rapports revendeurs terminée.")
