"""Tâches planifiées django-q2 pour l'app monitoring."""
import logging

logger = logging.getLogger(__name__)


def sync_ptp_health():
    from django.core.management import call_command

    logger.info("Synchronisation santé PtP depuis Zabbix…")
    call_command("sync_ptp_health")
    logger.info("Synchronisation santé PtP terminée.")


def monitor_frequencies():
    """
    Vérifie les métriques RF de toutes les antennes Ubiquiti avec auto_switch actif.
    Exécutée toutes les 5 minutes via django-q2.
    """
    from apps.core.models import NetworkDevice
    from apps.monitoring.models import FrequenceConfig
    from apps.monitoring.services.snmp_ubiquiti import UbiquitiAirMAXSnmpService
    from apps.monitoring.frequency_decision import (
        classify_antenna_state,
        should_change_frequency,
        execute_frequency_change,
        STATE_NORMAL,
    )
    from apps.monitoring.frequency_scanner import get_best_frequency

    configs = (
        FrequenceConfig.objects.select_related("device")
        .filter(auto_switch=True, device__is_active=True)
    )

    checked = 0
    changed = 0

    for cfg in configs:
        device = cfg.device
        try:
            svc = UbiquitiAirMAXSnmpService(device)
            metrics = svc.fetch_full_metrics()
        except Exception as exc:
            logger.warning("monitor_frequencies: SNMP(%s) échoué — %s", device, exc)
            continue

        snr = None
        if metrics.rssi_dbm is not None and metrics.noise_floor_dbm is not None:
            snr = metrics.rssi_dbm - metrics.noise_floor_dbm

        state = classify_antenna_state(metrics, cfg)
        checked += 1

        if state == STATE_NORMAL:
            logger.debug("monitor_frequencies: %s → NORMAL (SNR=%.1f)", device, snr or 0)
            continue

        logger.info(
            "monitor_frequencies: %s état=%s SNR=%s signal=%s",
            device, state, snr, metrics.rssi_dbm,
        )

        if not should_change_frequency(device, cfg):
            continue

        new_freq, score = get_best_frequency(device, cfg)
        if new_freq is None:
            logger.info("monitor_frequencies: %s — aucune fréquence de secours disponible", device)
            continue

        raison = "interference" if state in ("critique", "urgence") else "snr_faible"
        declencheur = "urgence" if state == "urgence" else "auto"

        ok = execute_frequency_change(
            device=device,
            config=cfg,
            new_freq=new_freq,
            raison=raison,
            declencheur=declencheur,
            snr_avant=snr,
            signal_avant=metrics.rssi_dbm,
        )
        if ok:
            changed += 1
            logger.info("monitor_frequencies: %s → %d MHz (score=%.2f)", device, new_freq, score)

    logger.info("monitor_frequencies terminé : %d antennes vérifiées, %d changements", checked, changed)
