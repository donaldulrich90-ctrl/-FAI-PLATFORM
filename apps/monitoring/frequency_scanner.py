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
    Détermine la meilleure fréquence de secours disponible.

    Logique :
    1. Vérifie le cooldown et le nombre de changements dans l'heure (anti-oscillation).
    2. Retourne la première fréquence de secours non utilisée récemment.
    3. Si toutes récemment utilisées, retourne la plus anciennement utilisée.

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

    # Récupère les dernières fréquences utilisées pour chaque backup
    freq_last_used: dict[int, float] = {}
    for f in backup_freqs:
        last = HistoriqueFrequence.objects.filter(device=device, freq_apres=f).first()
        if last:
            freq_last_used[f] = last.created_at.timestamp()
        else:
            freq_last_used[f] = 0.0  # jamais utilisé = priorité maximale

    # Trie par timestamp croissant (le moins récemment utilisé en premier)
    sorted_freqs = sorted(backup_freqs, key=lambda f: freq_last_used.get(f, 0.0))
    best = sorted_freqs[0]

    # Score simple basé sur la priorité dans la liste de backup
    score = 1.0 - (backup_freqs.index(best) / max(len(backup_freqs), 1)) * 0.3
    return best, round(score, 2)
