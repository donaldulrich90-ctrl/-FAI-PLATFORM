"""
Contrôle SSH distant des antennes Ubiquiti airOS AC.

Supporte : Rocket AC, NanoBeam AC, LiteBeam AC, etc.
Commandes airOS AC :
  - Lecture fréquence : cfg show | grep -i freq
  - Écriture          : cfg -s 'radio.1.freq=XXXX' && cfg -c
  - Redémarrage       : reboot

SÉCURITÉ : utilise ROUTER_CONTROL_DRY_RUN pour les tests.
"""
from __future__ import annotations

import logging
import os
import re
import time
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
    hint = (device.password_hint or "").strip()
    if hint.startswith("env:"):
        return os.environ.get(hint[4:].strip())
    if hint:
        val = os.environ.get(hint)
        if val:
            return val
    return os.environ.get("UBIQUITI_SSH_PASSWORD", None)


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
    username = device.username or "ubnt"
    port = device.ssh_port or 22
    try:
        client.connect(
            hostname=device.management_host,
            port=port,
            username=username,
            password=password,
            timeout=SSH_TIMEOUT,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as exc:
        client.close()
        raise UbiquitiSshError(f"Connexion SSH échouée ({device.management_host}:{port}) : {exc}") from exc
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
    try:
        client = _connect(device)
        out, _err = _exec(client, "cfg show | grep -i freq")
        client.close()
    except UbiquitiSshError as exc:
        return {"ok": False, "freq_mhz": None, "raw": "", "message": str(exc)}

    freq_mhz: int | None = None

    # Cherche radio.1.freq=XXXX en premier
    m = re.search(r"radio\.1\.freq\s*=\s*(\d+)", out)
    if m:
        freq_mhz = int(m.group(1))
    else:
        # Fallback: cherche la première valeur numérique ressemblant à une fréquence 5 GHz
        m2 = re.search(r"\b(5[1-8]\d{2})\b", out)
        if m2:
            freq_mhz = int(m2.group(1))

    return {
        "ok": True,
        "freq_mhz": freq_mhz,
        "raw": out,
        "message": f"Fréquence lue : {freq_mhz} MHz" if freq_mhz else "Fréquence non trouvée dans la config.",
    }


def set_frequency(device: "NetworkDevice", freq_mhz: int) -> dict:
    """
    Change la fréquence radio et redémarre l'antenne.

    IMPORTANT : Pour les liaisons PtP, changer l'extrémité DISTANTE en premier.
    L'antenne redémarre (~30 s d'indisponibilité).

    Retourne {'ok': bool, 'message': str}
    """
    if freq_mhz not in ALLOWED_FREQ_VALUES:
        return {
            "ok": False,
            "message": f"Fréquence {freq_mhz} MHz non autorisée. Valeurs acceptées : {sorted(ALLOWED_FREQ_VALUES)}",
        }

    dry_run: bool = getattr(settings, "ROUTER_CONTROL_DRY_RUN", False)
    if dry_run:
        logger.info("[DRY-RUN] set_frequency(%s, %d MHz) — aucune commande envoyée.", device, freq_mhz)
        return {"ok": True, "message": f"[DRY-RUN] Fréquence {freq_mhz} MHz simulée (aucun changement réel)."}

    try:
        client = _connect(device)
        # Appliquer le réglage dans la config persistante
        set_cmd = f"cfg -s 'radio.1.freq={freq_mhz}' && cfg -c"
        out_set, err_set = _exec(client, set_cmd)
        logger.info("set_frequency cfg output: %r / %r", out_set, err_set)

        # Laisser 1 s avant le reboot pour que cfg -c finisse d'écrire
        time.sleep(1)

        out_rb, err_rb = _exec(client, "reboot", timeout=8)
        logger.info("set_frequency reboot output: %r / %r", out_rb, err_rb)
        client.close()
    except UbiquitiSshError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "message": f"Erreur inattendue : {exc}"}

    return {
        "ok": True,
        "message": (
            f"Fréquence {freq_mhz} MHz appliquée. L'antenne redémarre (~30 secondes d'indisponibilité)."
        ),
    }
