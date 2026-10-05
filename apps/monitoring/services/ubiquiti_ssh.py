"""
Contrôle SSH distant des antennes Ubiquiti airOS AC.

Supporte : Rocket AC, NanoBeam AC, LiteBeam AC, etc.
Commandes airOS AC :
  - Lecture fréquence : iwconfig ath0 (fréquence réellement en service)
  - Application douce : rc.softrestart, uniquement pour les appareils validés

SÉCURITÉ : utilise ROUTER_CONTROL_DRY_RUN pour les tests.
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

import paramiko

from django.conf import settings

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice

logger = logging.getLogger(__name__)

# Fréquences 5 GHz autorisées (sous-bandes courantes airMAX)
ALLOWED_FREQUENCIES_5GHZ: list[tuple[int, str]] = [
    (5180, "5180 MHz (Ch. 36)"),
    (5200, "5200 MHz (Ch. 40)"),
    (5220, "5220 MHz (Ch. 44)"),
    (5240, "5240 MHz (Ch. 48)"),
    (5260, "5260 MHz (Ch. 52)"),
    (5280, "5280 MHz (Ch. 56)"),
    (5300, "5300 MHz (Ch. 60)"),
    (5320, "5320 MHz (Ch. 64)"),
    (5500, "5500 MHz (Ch. 100)"),
    (5520, "5520 MHz (Ch. 104)"),
    (5540, "5540 MHz (Ch. 108)"),
    (5560, "5560 MHz (Ch. 112)"),
    (5580, "5580 MHz (Ch. 116)"),
    (5600, "5600 MHz (Ch. 120)"),
    (5620, "5620 MHz (Ch. 124)"),
    (5640, "5640 MHz (Ch. 128)"),
    (5660, "5660 MHz (Ch. 132)"),
    (5680, "5680 MHz (Ch. 136)"),
    (5700, "5700 MHz (Ch. 140)"),
    (5720, "5720 MHz (Ch. 144)"),
    (5745, "5745 MHz (Ch. 149)"),
    (5765, "5765 MHz (Ch. 153)"),
    (5785, "5785 MHz (Ch. 157)"),
    (5805, "5805 MHz (Ch. 161)"),
    (5825, "5825 MHz (Ch. 165)"),
]

ALLOWED_FREQ_VALUES: set[int] = {f for f, _ in ALLOWED_FREQUENCIES_5GHZ}

SSH_TIMEOUT = 15  # secondes


class UbiquitiSshError(Exception):
    pass


def _resolve_password(device: "NetworkDevice") -> str | None:
    if getattr(device, "encrypted_password", ""):
        from apps.core.services.routeros_client import resolve_device_credential
        return resolve_device_credential(device)
    hint = (device.password_hint or "").strip()
    if hint.startswith("env:"):
        return os.environ.get(hint[4:].strip())
    if hint:
        val = os.environ.get(hint)
        if val:
            return val
    return os.environ.get("UBIQUITI_SSH_PASSWORD") or os.environ.get("AIREOS_SSH_PASSWORD")


def _build_client(device: "NetworkDevice") -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    known_hosts = (getattr(settings, "UBIQUITI_SSH_KNOWN_HOSTS_FILE", "") or "").strip()
    if known_hosts and os.path.isfile(known_hosts):
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        logger.warning(
            "UBIQUITI_SSH_KNOWN_HOSTS_FILE non configuré — clés SSH non vérifiées (risque MITM). "
            "Définir la variable en production."
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def _exec(client: paramiko.SSHClient, cmd: str, timeout: int = SSH_TIMEOUT) -> tuple[str, str]:
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out.strip(), err.strip()


def _connect(device: "NetworkDevice") -> paramiko.SSHClient:
    client = _build_client(device)
    password = _resolve_password(device)
    username = getattr(device, "aireos_username", "") or device.username or "ubnt"
    port = device.ssh_port or 22
    host = device.management_host
    parent = getattr(device, "parent_mikrotik", None)
    forwarded = getattr(device, "ssh_forward_port", None)
    if parent is not None and forwarded:
        if not parent.is_active:
            client.close()
            raise UbiquitiSshError("MikroTik parent désactivé.")
        host, port = parent.management_host, forwarded
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=SSH_TIMEOUT,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as exc:
        client.close()
        raise UbiquitiSshError(f"Connexion SSH échouée ({host}:{port}). Vérifier accès et identifiants.") from exc
    return client


# ── API publique ──────────────────────────────────────────────────────────────

def test_ssh_connection(device: "NetworkDevice") -> dict:
    """Teste la connectivité SSH. Retourne {'ok': bool, 'message': str}."""
    try:
        client = _connect(device)
        out, _ = _exec(client, "echo OK")
        client.close()
        if "OK" in out:
            return {"ok": True, "message": "Connexion SSH réussie."}
        return {"ok": False, "message": f"Réponse inattendue : {out!r}"}
    except UbiquitiSshError as exc:
        return {"ok": False, "message": str(exc)}


def read_current_frequency(device: "NetworkDevice") -> dict:
    """
    Lit la fréquence radio actuelle via SSH.
    Retourne {'ok': bool, 'freq_mhz': int|None, 'raw': str, 'message': str}
    """
    client = None
    try:
        client = _connect(device)
        from .airos_soft_apply import checked_exec
        out = checked_exec(client, "iwconfig ath0")
        m = re.search(r"Frequency[:=]\s*(\d+(?:\.\d+)?)\s*GHz", out, re.I)
        freq = round(float(m.group(1)) * 1000) if m else None
        return {"ok": freq is not None, "freq_mhz": freq, "raw": out,
                "message": f"Fréquence en service : {freq} MHz" if freq else "Fréquence en service illisible."}
    except Exception as exc:
        return {"ok": False, "freq_mhz": None, "raw": "", "message": str(exc)}
    finally:
        if client is not None:
            client.close()


def allowed_frequencies(device):
    """Liste validée par appareil ; ne remplace pas le contrôle du pays sur airOS."""
    mapping = getattr(settings, "FREQUENCY_SOFT_APPLY_ALLOWED", {})
    values = mapping.get(str(getattr(device, "pk", "")), []) if isinstance(mapping, dict) else []
    if not isinstance(values, list):
        return set()
    return {f for f in values if type(f) is int and 4900 <= f <= 5900}


def set_frequency(device: "NetworkDevice", freq_mhz: int) -> dict:
    """Application douce, uniquement pour les appareils et canaux validés."""
    if type(freq_mhz) is not int or not 4900 <= freq_mhz <= 5900:
        return {"ok": False, "message": f"Fréquence {freq_mhz} MHz non autorisée."}
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        return {"ok": True, "message": f"[DRY-RUN] Fréquence {freq_mhz} MHz simulée (aucun changement réel)."}
    if not getattr(settings, "FREQUENCY_COMMANDS_VERIFIED", False) or freq_mhz not in allowed_frequencies(device):
        return {"ok": False, "blocked": True, "message": (
            "Application sans redémarrage non validée pour cet appareil et cette fréquence. "
            "Aucune commande de changement envoyée."
        )}
    from .airos_soft_apply import apply_frequency
    return apply_frequency(_connect, device, freq_mhz)
