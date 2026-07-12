"""Tâches planifiées django-q2 pour l'app accounts (revendeurs)."""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def check_revendeur_subscriptions() -> None:
    """
    Tâche quotidienne (8h) :
    - J-3 : envoie rappel WhatsApp aux revendeurs qui expirent dans 3 jours
    - Expiré : suspend le binding hotspot + WhatsApp + statut=expire
    """
    from apps.accounts.models import User
    from apps.core.services.routeros_client import RouterOSClient, RouterOSError
    from apps.monitoring.audit import log_router_action
    from apps.notifications.whatsapp import (
        WhatsAppService,
        msg_rappel_revendeur_j3,
        msg_suspension_revendeur,
    )

    today = date.today()
    j3_date = today + timedelta(days=3)

    qs = User.objects.filter(
        role=User.Role.REVENDEUR,
        date_expiration__isnull=False,
        is_active=True,
    ).exclude(
        statut_revendeur=User.RevendeurStatut.SUSPENDU,
    ).select_related("mikrotik")

    svc = WhatsAppService()
    sent_j3 = suspended = 0

    for rev in qs:
        nom = rev.get_full_name() or rev.username
        exp_str = rev.date_expiration.strftime("%d/%m/%Y")
        montant = str(int(rev.montant_abonnement_xof)) if rev.montant_abonnement_xof else "—"

        # ── J-3 rappel ──────────────────────────────────────────────────────
        if rev.date_expiration == j3_date:
            if rev.phone:
                svc.send(rev.phone, msg_rappel_revendeur_j3(nom, exp_str, montant), tenant_id=rev.tenant_id)
                sent_j3 += 1

        # ── Expiration : suspension ──────────────────────────────────────────
        elif rev.date_expiration < today:
            if rev.mac_antenne and rev.mikrotik:
                comment = f"revendeur-{rev.pk}"
                try:
                    with RouterOSClient(rev.mikrotik) as client:
                        ok, err = client.ip_binding_upsert(rev.mac_antenne, "blocked", comment)
                except RouterOSError as exc:
                    ok, err = False, str(exc)[:200]
                except Exception as exc:
                    ok, err = False, str(exc)[:200]

                log_router_action(
                    rev.mikrotik, "ip_binding", target=rev.mac_antenne,
                    command_sent=f"ip-binding mac={rev.mac_antenne} type=blocked (auto-expiration)",
                    success=ok, error_message="" if ok else err,
                    dry_run=False, performed_by=None,
                )
                if not ok:
                    logger.warning("check_revendeur_subscriptions : échec blocage %s — %s", rev, err)

            rev.statut_revendeur = User.RevendeurStatut.EXPIRE
            rev.save(update_fields=["statut_revendeur"])

            if rev.phone:
                svc.send(rev.phone, msg_suspension_revendeur(nom, exp_str, montant), tenant_id=rev.tenant_id)
            suspended += 1

    logger.info(
        "check_revendeur_subscriptions : J-3=%d rappels envoyés, %d revendeurs expirés suspendus.",
        sent_j3, suspended,
    )
