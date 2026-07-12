"""
Monitoring des antennes Ubiquiti airOS via SSH port-forwarding à travers le MikroTik parent.

Connexion : MikroTik parent.management_host:device.ssh_forward_port
            (le MikroTik NAT-forwarde ce port vers l'IP airOS de l'antenne)
Authentification : mot de passe via AIREOS_SSH_PASSWORD

Méthode de connexion — fallback automatique :
  1. paramiko  → firmwares airOS récents
  2. sshpass   → vieux firmwares airOS v8.x (algorithmes SSH anciens)

Commandes airOS exécutées :
  - iwconfig ath0     → fréquence, débit, puissance TX, signal
  - wstalist          → JSON clients (MAC, signal, débit)
  - cat /proc/net/dev → octets RX/TX sur ath0
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import paramiko
from django.conf import settings

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice

logger = logging.getLogger(__name__)

SSH_TIMEOUT = 15


class UbiquitiSSHError(Exception):
    pass


@dataclass
class AirOSClientEntry:
    mac: str
    signal_dbm: int | None = None
    tx_rate_mbps: float | None = None
    rx_rate_mbps: float | None = None


@dataclass
class AirOSMetrics:
    online: bool = False
    freq_mhz: int | None = None
    tx_rate_mbps: float | None = None
    tx_power_dbm: int | None = None
    signal_dbm: int | None = None
    avg_signal_dbm: int | None = None
    rx_mb: float | None = None
    tx_mb: float | None = None
    clients: list[AirOSClientEntry] = field(default_factory=list)
    client_count: int | None = None
    error: str | None = None


def _build_ssh_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    known_hosts = (getattr(settings, "MIKROTIK_SSH_KNOWN_HOSTS_FILE", "") or "").strip()
    if known_hosts and os.path.isfile(known_hosts):
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def _exec_sshpass(
    host: str, port: int, username: str, password: str, command: str, timeout: int
) -> tuple[str, str]:
    """
    Exécute une commande airOS via sshpass (fallback pour vieux firmwares v8.x).

    Utilise une liste d'arguments (pas shell=True) pour éviter l'injection de commandes.
    """
    try:
        result = subprocess.run(
            [
                "sshpass", "-p", password,
                "ssh",
                "-p", str(port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "PubkeyAuthentication=no",
                f"{username}@{host}",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        return result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        raise UbiquitiSSHError(
            "sshpass introuvable — vérifiez que sshpass est installé (apt-get install -y sshpass)."
        )
    except subprocess.TimeoutExpired:
        raise UbiquitiSSHError(f"Timeout sshpass ({timeout}s) sur {host}:{port}.")
    except Exception as exc:
        raise UbiquitiSSHError(f"sshpass ({host}:{port}) : {exc}") from exc


def _run_aireos_command(
    host: str, port: int, username: str, password: str, command: str, timeout: int = 15
) -> tuple[str, str]:
    """
    Exécute une commande airOS avec fallback automatique :

    1. Essai paramiko (firmwares récents)
       - disabled_algorithms force le handshake vers ssh-rsa (SHA-1) accepté par airOS
    2. Si AuthenticationException ou SSHException → sshpass subprocess (vieux airOS v8.x)
    3. Si les deux échouent → raise UbiquitiSSHError
    """
    # Méthode 1 : paramiko
    try:
        client = _build_ssh_client()
        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=timeout,
                disabled_algorithms={"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
            )
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return out, err
        finally:
            client.close()
    except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
        logger.info(
            "paramiko airOS (%s:%s) échec (%s) — tentative sshpass", host, port, exc
        )

    # Méthode 2 : sshpass
    return _exec_sshpass(host, port, username, password, command, timeout)


def _parse_iwconfig(output: str) -> dict:
    """
    Parse la sortie de `iwconfig ath0`.

    Exemple de sortie airOS :
      Frequency:5.180 GHz
      Bit Rate=54 Mb/s   Tx-Power=23 dBm
      Signal level=-56 dBm
    """
    result: dict = {}

    m = re.search(r"Frequency[:=]\s*(\d+(?:\.\d+)?)\s*GHz", output, re.IGNORECASE)
    if m:
        result["freq_mhz"] = int(float(m.group(1)) * 1000)

    m = re.search(r"Bit Rate[:=]\s*(\d+(?:\.\d+)?)\s*Mb/s", output, re.IGNORECASE)
    if m:
        result["tx_rate_mbps"] = float(m.group(1))

    m = re.search(r"Tx-Power[:=]\s*(\d+)\s*dBm", output, re.IGNORECASE)
    if m:
        result["tx_power_dbm"] = int(m.group(1))

    m = re.search(r"Signal level[:=]\s*(-?\d+)\s*dBm", output, re.IGNORECASE)
    if m:
        result["signal_dbm"] = int(m.group(1))

    return result


def _parse_wstalist(output: str) -> list[AirOSClientEntry]:
    """
    Parse la sortie JSON de `wstalist`.

    airOS retourne typiquement un tableau JSON :
      [{"mac":"aa:bb:cc:dd:ee:ff","signal":-65,"rate":{"rx":54,"tx":54},...}, ...]

    On extrait le premier tableau JSON valide de la sortie brute (la commande
    peut imprimer des entêtes non-JSON avant le tableau).
    """
    m = re.search(r"\[.*\]", output, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []

    clients: list[AirOSClientEntry] = []
    for entry in data if isinstance(data, list) else []:
        mac = entry.get("mac") or entry.get("remote") or ""
        signal = entry.get("signal") or entry.get("rssi")
        if isinstance(signal, list):
            signal = min(signal) if signal else None
        rate = entry.get("rate") or {}
        tx_rate = rate.get("tx") if isinstance(rate, dict) else None
        rx_rate = rate.get("rx") if isinstance(rate, dict) else None
        clients.append(AirOSClientEntry(
            mac=mac,
            signal_dbm=int(signal) if signal is not None else None,
            tx_rate_mbps=float(tx_rate) if tx_rate is not None else None,
            rx_rate_mbps=float(rx_rate) if rx_rate is not None else None,
        ))
    return clients


def _parse_proc_net_dev(output: str, iface: str = "ath0") -> tuple[float | None, float | None]:
    """
    Parse `cat /proc/net/dev` pour extraire RX/TX bytes de l'interface donnée.

    Colonnes : rx_bytes, rx_pkts, rx_errs, rx_drop, rx_fifo, rx_frame,
               rx_compressed, rx_multicast, tx_bytes, tx_pkts, ...
    """
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith(iface + ":"):
            continue
        _, data = line.split(":", 1)
        parts = data.split()
        try:
            rx_bytes = int(parts[0])
            tx_bytes = int(parts[8])
            return round(rx_bytes / 1_048_576, 2), round(tx_bytes / 1_048_576, 2)
        except (IndexError, ValueError):
            break
    return None, None


class UbiquitiSSHService:
    """Récupère les métriques d'une antenne airOS via SSH à travers le port-forwarding MikroTik."""

    def __init__(self, device: "NetworkDevice") -> None:
        self.device = device

    def fetch_metrics(self) -> AirOSMetrics:
        m = AirOSMetrics()

        # Validation de la config avant toute tentative SSH
        parent = self.device.parent_mikrotik
        if parent is None or not parent.is_active:
            m.error = "Pas de MikroTik parent actif configuré pour cette antenne."
            return m
        if not self.device.ssh_forward_port:
            m.error = "ssh_forward_port non configuré sur cette antenne."
            return m
        username = (self.device.aireos_username or "").strip()
        if not username:
            m.error = "aireos_username non configuré sur cette antenne."
            return m
        password = os.environ.get("AIREOS_SSH_PASSWORD", "").strip()
        if not password:
            m.error = "AIREOS_SSH_PASSWORD non configuré dans l'environnement."
            return m

        host = parent.management_host
        port = self.device.ssh_forward_port
        timeout = int(getattr(settings, "AIREOS_SSH_TIMEOUT", SSH_TIMEOUT))

        try:
            iwconfig_out, _ = _run_aireos_command(host, port, username, password, "iwconfig ath0", timeout)
            m.online = True

            parsed = _parse_iwconfig(iwconfig_out)
            m.freq_mhz = parsed.get("freq_mhz")
            m.tx_rate_mbps = parsed.get("tx_rate_mbps")
            m.tx_power_dbm = parsed.get("tx_power_dbm")
            m.signal_dbm = parsed.get("signal_dbm")

            wsta_out, _ = _run_aireos_command(host, port, username, password, "wstalist", timeout)
            m.clients = _parse_wstalist(wsta_out)
            m.client_count = len(m.clients)

            signals = [c.signal_dbm for c in m.clients if c.signal_dbm is not None]
            if signals:
                m.avg_signal_dbm = round(sum(signals) / len(signals))

            proc_out, _ = _run_aireos_command(host, port, username, password, "cat /proc/net/dev", timeout)
            m.rx_mb, m.tx_mb = _parse_proc_net_dev(proc_out)

        except UbiquitiSSHError as exc:
            m.error = str(exc)[:200]
            logger.warning("UbiquitiSSH(%s) : %s", self.device, exc)
        except Exception as exc:
            m.error = f"Erreur inattendue : {exc}"[:200]
            logger.exception("UbiquitiSSH inattendu (%s)", self.device)

        return m
