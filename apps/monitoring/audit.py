"""
Audit logging des actions envoyées aux routeurs réseau.
Écrit dans RouterAuditLog de façon non-bloquante (les erreurs d'écriture sont loguées mais ne propagent pas).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice

logger = logging.getLogger(__name__)


def log_router_action(
    device: NetworkDevice,
    action: str,
    *,
    target: str = "",
    command_sent: str = "",
    success: bool = True,
    error_message: str = "",
    dry_run: bool = False,
    performed_by=None,
    ip_address: str | None = None,
) -> None:
    """
    Crée une entrée RouterAuditLog.
    Silencieux en cas d'erreur (ne doit jamais bloquer l'opération principale).

    Args:
        device: l'équipement réseau ciblé
        action: constante RouterAuditLog.Action (mac_block, hotspot_provision, etc.)
        target: MAC, code ticket, ou autre identifiant de la cible
        command_sent: commande RouterOS ou paramètres API envoyés
        success: True si l'opération a réussi
        error_message: message d'erreur si success=False
        dry_run: True si l'opération était en mode test
        performed_by: instance User ou None (tâches planifiées)
        ip_address: IP du client HTTP ou None
    """
    try:
        from apps.monitoring.models import RouterAuditLog

        tenant = None
        try:
            tenant = device.site.tenant
        except Exception:
            pass

        RouterAuditLog.objects.create(
            tenant=tenant,
            device=device,
            performed_by=performed_by,
            action=action,
            target=target,
            command_sent=command_sent,
            success=success,
            error_message=error_message,
            dry_run=dry_run,
            ip_address=ip_address,
        )
    except Exception:
        logger.exception(
            "Échec écriture RouterAuditLog (device=%s action=%s) — l'opération n'est pas affectée.",
            getattr(device, "pk", "?"),
            action,
        )
