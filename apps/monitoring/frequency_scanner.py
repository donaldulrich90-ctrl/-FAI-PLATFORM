"""
Scanner de spectre fréquentiel pour antennes Ubiquiti.

Tente d'obtenir les métriques via SNMP puis SSH.
Dégrade gracieusement si les deux sont indisponibles.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice
    from apps.monitoring.models import FrequenceConfig

logger = logging.getLogger(__name__)


def scan_frequency_spectrum(device: "NetworkDevice") -> dict:
    """
    Tente de récupérer l'état RF actuel de l'antenne via SNMP.

    Retourne un dict avec les clés :
      ok       : bool — True si des données ont pu être lues
      freq_mhz : int|None — fréquence courante
      snr      : float|None — SNR calculé (rssi - noise_floor)
      signal   : float|None — RSSI (dBm)
      source   : "snmp" | "unavailable"
      error    : str|None
    """
    from apps.monitoring.services.snmp_ubiquiti import UbiquitiAirMAXSnmpService

    try:
        svc = UbiquitiAirMAXSnmpService(device)
        metrics = svc.fetch_full_metrics()
        snr = None
        if metrics.rssi_dbm is not None and metrics.noise_floor_dbm is not None:
            snr = metrics.rssi_dbm - metrics.noise_floor_dbm
        return {
            "ok": True,
            "freq_mhz": metrics.freq_mhz,
            "snr": snr,
            "signal": metrics.rssi_dbm,
            "source": "snmp",
            "error": None,
        }
    except Exception as exc:
        logger.debug("scan_frequency_spectrum(%s) SNMP failed: %s", device, exc)
        return {
            "ok": False,
            "freq_mhz": None,
            "snr": None,
            "signal": None,
            "source": "unavailable",
            "error": str(exc),
        }


def get_best_frequency(device: "NetworkDevice", config: "FrequenceConfig") -> tuple[int | None, float]:
    """
    Choisit une alternative récemment mesurée, selon l'ordre de préférence configuré.
    Exclut le canal courant, les essais échoués et les canaux sans preuve d'un gain.

    Returns (freq_mhz, score) — freq_mhz est None si aucune alternative disponible.
    Score indicatif : 0.0–1.0, 1.0 = meilleur choix.
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.monitoring.models import HistoriqueFrequence

    backup_freqs = config.get_backup_frequencies()
    if not backup_freqs:
        return None, 0.0

    now = timezone.now()
    cooldown_minutes = getattr(settings, "FREQUENCY_CHANGE_COOLDOWN_MINUTES", 15)
    max_per_hour = getattr(settings, "FREQUENCY_MAX_CHANGES_PER_HOUR", 3)

    # Vérification anti-oscillation
    recent_changes = HistoriqueFrequence.objects.filter(
        device=device,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    if recent_changes >= max_per_hour:
        logger.warning(
            "get_best_frequency(%s): anti-oscillation — %d changements dans l'heure (max %d)",
            device,
            recent_changes,
            max_per_hour,
        )
        return None, 0.0

    last_change = HistoriqueFrequence.objects.filter(device=device).first()
    if last_change and (now - last_change.created_at).total_seconds() < cooldown_minutes * 60:
        remaining = cooldown_minutes - int((now - last_change.created_at).total_seconds() / 60)
        logger.info(
            "get_best_frequency(%s): cooldown actif, %d min restantes",
            device,
            remaining,
        )
        return None, 0.0

    from apps.monitoring.models import FrequenceMesure
    from apps.monitoring.frequency_policy import choose_candidate

    current = FrequenceMesure.objects.filter(device=device, source="passif").first()
    if not current or (now - current.measured_at).total_seconds() > 600:
        return None, 0.0
    if not current.freq_mhz or current.noise_floor_dbm is None:
        return None, 0.0
    # Les fréquences inconnues restent exclues. L'ordre configuré exprime la préférence.
    candidates = [config.freq_principale] + backup_freqs
    failed = set(HistoriqueFrequence.objects.filter(
        device=device, resultat="degrade", dry_run=False,
        created_at__gte=now - timedelta(hours=24),
    ).values_list("freq_apres", flat=True))
    candidates = [f for f in candidates if f not in failed]
    hours = getattr(settings, "FREQUENCY_MEASUREMENT_MAX_AGE_HOURS", 24)
    measurements = list(FrequenceMesure.objects.filter(
        device=device, freq_mhz__in=candidates,
        measured_at__gte=now - timedelta(hours=hours),
    ))
    return choose_candidate(
        candidates, measurements, current.freq_mhz, current.noise_floor_dbm, now,
        min_gain_db=getattr(settings, "FREQUENCY_MIN_GAIN_DB", 3),
        max_age_hours=hours,
    )


def record_measurement(device: "NetworkDevice", metrics, source: str = "passif"):
    """Enregistre une mesure RF (bruit / SNR) pour la fréquence courante — carte de propreté."""
    from apps.monitoring.models import FrequenceMesure

    freq = getattr(metrics, "freq_mhz", None)
    if not freq:
        return None
    noise = getattr(metrics, "noise_floor_dbm", None)
    rssi = getattr(metrics, "rssi_dbm", None)
    snr = (rssi - noise) if (rssi is not None and noise is not None) else None
    try:
        return FrequenceMesure.objects.create(
            device=device,
            freq_mhz=freq,
            noise_floor_dbm=noise,
            snr=snr,
            signal_dbm=rssi,
            source=source,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("record_measurement(%s) échec: %s", device, exc)
        return None


def probe_best_frequency(device: "NetworkDevice", config: "FrequenceConfig") -> dict:
    """
    SCAN ACTIF (méthode B) — teste chaque fréquence candidate, mesure le bruit, garde la plus propre.

    ⚠ Chaque changement REDÉMARRE l'antenne (~30-60 s d'indisponibilité). À lancer en fenêtre creuse
    (nuit) et uniquement sur les antennes avec scan_actif=True. Respecte ROUTER_CONTROL_DRY_RUN.
    """
    return {"ok": False, "message": (
        "Scan actif désactivé : les essais avec redémarrage ne vérifient pas "
        "la reconnexion des clients. Utiliser airMagic et des mesures validées."
    )}
