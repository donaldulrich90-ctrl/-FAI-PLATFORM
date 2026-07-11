"""
Logique de décision pour le basculement automatique de fréquences Ubiquiti.

États possibles :
  NORMAL   — SNR >= seuil_snr_min ET signal >= seuil_signal_min
  DÉGRADÉ  — SNR < seuil_snr_min OU signal < seuil_signal_min
  CRITIQUE — SNR < seuil_snr_min * 0.7 OU signal < seuil_signal_min - 10
  URGENCE  — SNR < seuil_snr_min * 0.5 OU signal < seuil_signal_min - 20
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice
    from apps.monitoring.models import FrequenceConfig
    from apps.monitoring.services.snmp_ubiquiti import UbiquitiFullMetrics

logger = logging.getLogger(__name__)

STATE_NORMAL = "normal"
STATE_DEGRADE = "degrade"
STATE_CRITIQUE = "critique"
STATE_URGENCE = "urgence"


def classify_antenna_state(metrics: "UbiquitiFullMetrics", config: "FrequenceConfig") -> str:
    """Classifie l'état de l'antenne selon le SNR et le signal courant."""
    snr = None
    if metrics.rssi_dbm is not None and metrics.noise_floor_dbm is not None:
        snr = metrics.rssi_dbm - metrics.noise_floor_dbm

    signal = metrics.rssi_dbm

    snr_min = config.seuil_snr_min
    sig_min = config.seuil_signal_min

    if (snr is not None and snr < snr_min * 0.5) or (signal is not None and signal < sig_min - 20):
        return STATE_URGENCE
    if (snr is not None and snr < snr_min * 0.7) or (signal is not None and signal < sig_min - 10):
        return STATE_CRITIQUE
    if (snr is not None and snr < snr_min) or (signal is not None and signal < sig_min):
        return STATE_DEGRADE
    return STATE_NORMAL


def should_change_frequency(device: "NetworkDevice", config: "FrequenceConfig") -> bool:
    """
    Vérifie si le changement de fréquence est autorisé selon les gardes anti-oscillation.

    Retourne False si :
    - auto_switch est désactivé sur la config ou globalement
    - Le cooldown n'est pas écoulé depuis le dernier changement
    - Le nombre max de changements dans l'heure est atteint
    """
    from datetime import timedelta
    from apps.monitoring.models import HistoriqueFrequence

    if not config.auto_switch:
        return False
    if not getattr(settings, "FREQUENCY_AUTO_SWITCH", True):
        return False

    now = timezone.now()
    cooldown = getattr(settings, "FREQUENCY_CHANGE_COOLDOWN_MINUTES", 15)
    max_per_hour = getattr(settings, "FREQUENCY_MAX_CHANGES_PER_HOUR", 3)

    # Anti-oscillation : nombre de changements dans la dernière heure
    recent = HistoriqueFrequence.objects.filter(
        device=device,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    if recent >= max_per_hour:
        logger.info(
            "should_change_frequency(%s): refusé — %d/%d changements/heure",
            device, recent, max_per_hour,
        )
        return False

    # Cooldown depuis le dernier changement
    last = HistoriqueFrequence.objects.filter(device=device).first()
    if last and (now - last.created_at).total_seconds() < cooldown * 60:
        logger.info(
            "should_change_frequency(%s): refusé — cooldown actif (%ds restants)",
            device,
            int(cooldown * 60 - (now - last.created_at).total_seconds()),
        )
        return False

    return True


def execute_frequency_change(
    device: "NetworkDevice",
    config: "FrequenceConfig",
    new_freq: int,
    raison: str = "snr_faible",
    declencheur: str = "auto",
    snr_avant: float | None = None,
    signal_avant: float | None = None,
) -> bool:
    """
    Exécute le changement de fréquence et enregistre l'historique.

    Pour les liaisons PtP : change le site_b en premier, attend 35s, puis le site_a.
    Envoie une alerte WhatsApp admin après le changement.

    Retourne True si succès.
    """
    from apps.core.models import PtPLink
    from apps.monitoring.models import HistoriqueFrequence
    from apps.monitoring.services.ubiquiti_ssh import set_frequency
    from apps.notifications.whatsapp import send_admin_alert, msg_alerte_frequence_admin

    dry_run = getattr(settings, "ROUTER_CONTROL_DRY_RUN", False)
    freq_avant = None

    # Lecture fréquence actuelle (best-effort)
    try:
        from apps.monitoring.services.ubiquiti_ssh import read_current_frequency
        r = read_current_frequency(device)
        if r.get("ok"):
            freq_avant = r.get("freq_mhz")
    except Exception:
        pass

    if freq_avant is None:
        freq_avant = config.freq_principale

    logger.info(
        "execute_frequency_change(%s): %d → %d MHz [%s/%s] dry_run=%s",
        device, freq_avant, new_freq, raison, declencheur, dry_run,
    )

    # PtP : identifier le lien et changer l'extrémité distante en premier
    import time
    ptp_link = (
        PtPLink.objects.filter(device_a=device).first()
        or PtPLink.objects.filter(device_b=device).first()
    )

    success = True
    if ptp_link and not dry_run:
        remote_device = ptp_link.device_b if ptp_link.device_a == device else ptp_link.device_a
        logger.info("PtP détecté — changement côté distant (%s) en premier", remote_device)
        res_remote = set_frequency(remote_device, new_freq)
        if not res_remote.get("ok"):
            logger.error("Changement distant échoué : %s", res_remote.get("message"))
            success = False
        else:
            time.sleep(35)
            res_local = set_frequency(device, new_freq)
            if not res_local.get("ok"):
                logger.error("Changement local échoué : %s", res_local.get("message"))
                success = False
            else:
                time.sleep(35)
    elif not dry_run:
        res = set_frequency(device, new_freq)
        if not res.get("ok"):
            logger.error("Changement de fréquence échoué : %s", res.get("message"))
            success = False

    # Enregistrement historique
    HistoriqueFrequence.objects.create(
        device=device,
        freq_avant=freq_avant,
        freq_apres=new_freq,
        raison=raison,
        snr_avant=snr_avant,
        signal_avant=signal_avant,
        declencheur=declencheur,
        resultat="ameliore" if success else "neutre",
        dry_run=dry_run,
    )

    # Mise à jour dernière modif sur la config
    config.derniere_modif = timezone.now()
    config.save(update_fields=["derniere_modif"])

    # Alerte WhatsApp admin
    try:
        msg = msg_alerte_frequence_admin(
            nom_antenne=device.name,
            site=str(device.site) if hasattr(device, "site") else "—",
            snr=snr_avant,
            freq_avant=freq_avant,
            freq_apres=new_freq,
            resultat="OK" if success else "ÉCHEC",
            heure=timezone.now().strftime("%H:%M"),
        )
        send_admin_alert(msg)
    except Exception as exc:
        logger.warning("Alerte WhatsApp admin échouée : %s", exc)

    return success
