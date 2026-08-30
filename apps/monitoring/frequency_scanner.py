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

    # ── Choix par PROPRETÉ mesurée (carte de bruit) ──────────────────────
    from apps.monitoring.models import FrequenceMesure
    from django.db.models import Avg

    window_days = getattr(settings, "FREQUENCY_CLEANLINESS_WINDOW_DAYS", 7)
    since = now - timedelta(days=window_days)
    noise_by_freq: dict[int, float] = {}
    for f in backup_freqs:
        agg = FrequenceMesure.objects.filter(
            device=device, freq_mhz=f, measured_at__gte=since, noise_floor_dbm__isnull=False
        ).aggregate(n=Avg("noise_floor_dbm"))
        if agg["n"] is not None:
            noise_by_freq[f] = agg["n"]

    if noise_by_freq:
        # bruit le plus faible (le plus négatif) = fréquence la plus propre → on la garde
        best = min(noise_by_freq, key=lambda f: noise_by_freq[f])
        vals = list(noise_by_freq.values())
        lo, hi = min(vals), max(vals)
        score = 1.0 if hi == lo else round(0.7 + 0.3 * (hi - noise_by_freq[best]) / (hi - lo), 2)
        logger.info(
            "get_best_frequency(%s): choix par propreté → %d MHz (bruit≈%.1f dBm)",
            device, best, noise_by_freq[best],
        )
        return best, score

    # ── Repli : fréquence la moins récemment utilisée (aucune mesure disponible) ──
    freq_last_used: dict[int, float] = {}
    for f in backup_freqs:
        last = HistoriqueFrequence.objects.filter(device=device, freq_apres=f).first()
        freq_last_used[f] = last.created_at.timestamp() if last else 0.0

    sorted_freqs = sorted(backup_freqs, key=lambda f: freq_last_used.get(f, 0.0))
    best = sorted_freqs[0]
    score = 1.0 - (backup_freqs.index(best) / max(len(backup_freqs), 1)) * 0.3
    return best, round(score, 2)


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
    import time
    from apps.monitoring.services.snmp_ubiquiti import UbiquitiAirMAXSnmpService
    from apps.monitoring.services.ubiquiti_ssh import set_frequency
    from apps.monitoring.models import HistoriqueFrequence

    candidates: list[int] = []
    for f in [config.freq_principale] + config.get_backup_frequencies():
        if f and f not in candidates:
            candidates.append(f)
    if len(candidates) < 2:
        return {"ok": False, "message": "Moins de 2 fréquences candidates — rien à scanner."}

    settle = int(getattr(settings, "FREQUENCY_SCAN_SETTLE_SECONDS", 60))
    dwell = int(getattr(settings, "FREQUENCY_SCAN_DWELL_SECONDS", 15))

    results: dict[int, float] = {}
    for f in candidates:
        res = set_frequency(device, f)
        if not res.get("ok"):
            logger.warning("probe_best_frequency(%s): set %d MHz échoué — %s", device, f, res.get("message"))
            continue
        time.sleep(settle)   # attendre le redémarrage airOS
        time.sleep(dwell)    # laisser le radio se stabiliser
        try:
            m = UbiquitiAirMAXSnmpService(device).fetch_full_metrics()
        except Exception as exc:
            logger.warning("probe_best_frequency(%s): SNMP %d MHz échoué — %s", device, f, exc)
            continue
        if m and m.noise_floor_dbm is not None:
            record_measurement(device, m, source="scan")
            results[f] = m.noise_floor_dbm
            logger.info("probe_best_frequency(%s): %d MHz → bruit=%s dBm", device, f, m.noise_floor_dbm)

    if not results:
        return {"ok": False, "message": "Aucune mesure exploitable pendant le scan."}

    best = min(results, key=lambda f: results[f])  # bruit le plus faible = plus propre
    set_frequency(device, best)  # se caler sur la meilleure et la garder
    HistoriqueFrequence.objects.create(
        device=device,
        freq_avant=candidates[0],
        freq_apres=best,
        raison="secours",
        declencheur="auto",
        notes=f"Scan nocturne — bruit par fréquence: {results}",
    )
    logger.info("probe_best_frequency(%s): meilleure = %d MHz (bruit=%s)", device, best, results[best])
    return {"ok": True, "best": best, "results": results}
