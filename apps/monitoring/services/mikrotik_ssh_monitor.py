"""
Monitoring des antennes Ubiquiti via SSH sur le MikroTik parent.

Connexion par clé SSH (MIKROTIK_SSH_KEY_PATH) — aucun mot de passe.
Commandes RouterOS exécutées pour chaque antenne :
  - /ping address=<ip> count=3            → statut en ligne
  - /interface bridge host print          → nombre de clients sur le port bridge
  - /ip neighbor print                    → voisins MNDP/LLDP (découverte)
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import paramiko
from django.conf import settings

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice

logger = logging.getLogger(__name__)

SSH_TIMEOUT = 15


class MikrotikSshError(Exception):
    pass


@dataclass
class MikrotikUbiquitiMetrics:
    online: bool = False
    client_count: int | None = None
    avg_signal_dbm: int | None = None
    neighbor_seen: bool = False
    error: str | None = None


def _build_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    known_hosts = (getattr(settings, "MIKROTIK_SSH_KNOWN_HOSTS_FILE", "") or "").strip()
    if known_hosts and os.path.isfile(known_hosts):
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def _connect(mikrotik: "NetworkDevice") -> paramiko.SSHClient:
    key_path = (getattr(settings, "MIKROTIK_SSH_KEY_PATH", "") or "").strip()
    if not key_path:
        raise MikrotikSshError("MIKROTIK_SSH_KEY_PATH non configuré.")
    if not os.path.isfile(key_path):
        raise MikrotikSshError(f"Clé SSH introuvable : {key_path}")

    username = (mikrotik.username or "").strip() or getattr(
        settings, "MIKROTIK_DEFAULT_USERNAME", "admin"
    )
    port = mikrotik.ssh_port or 22
    timeout = int(getattr(settings, "MIKROTIK_SSH_TIMEOUT", SSH_TIMEOUT))

    client = _build_client()
    try:
        client.connect(
            hostname=mikrotik.management_host,
            port=port,
            username=username,
            key_filename=key_path,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
        )
    except Exception as exc:
        client.close()
        raise MikrotikSshError(
            f"SSH clé ({mikrotik.management_host}:{port}) : {exc}"
        ) from exc
    return client


def _exec(client: paramiko.SSHClient, cmd: str) -> tuple[str, str]:
    timeout = int(getattr(settings, "MIKROTIK_SSH_TIMEOUT", SSH_TIMEOUT))
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out, err


def _ping_via_mikrotik(client: paramiko.SSHClient, ip: str) -> bool:
    """Exécute /ping depuis le MikroTik, retourne True si l'hôte répond."""
    out, _ = _exec(client, f"/ping address={ip} count=3")
    m = re.search(r"received=(\d+)", out)
    if m and int(m.group(1)) > 0:
        return True
    if "packet-loss=0%" in out:
        return True
    return False


def _count_bridge_hosts(client: paramiko.SSHClient, interface: str) -> int | None:
    """
    Compte les hôtes bridge appris sur l'interface donnée.
    Utilise count-only pour retourner directement un entier.
    """
    if not interface:
        return None
    safe_iface = re.sub(r"[^a-zA-Z0-9/_-]", "", interface)
    out, err = _exec(
        client,
        f"/interface bridge host print count-only where on-interface={safe_iface}",
    )
    try:
        return int(out.strip())
    except (ValueError, TypeError):
        if err:
            logger.debug("bridge host count err iface=%s : %s", interface, err)
        return None


def _get_neighbors(client: paramiko.SSHClient) -> list[str]:
    """Retourne les adresses IP des voisins MNDP/LLDP visibles depuis le MikroTik."""
    out, _ = _exec(client, "/ip neighbor print terse proplist=address")
    ips: list[str] = []
    for line in out.splitlines():
        m = re.search(r"address=(\S+)", line)
        if m:
            ips.append(m.group(1))
    return ips


class MikrotikSshMonitorService:
    """Récupère les métriques d'une antenne Ubiquiti depuis son MikroTik parent via SSH."""

    def __init__(self, mikrotik_device: "NetworkDevice") -> None:
        self.mikrotik = mikrotik_device

    def fetch_metrics(
        self, ubiquiti_ip: str, mikrotik_interface: str
    ) -> MikrotikUbiquitiMetrics:
        m = MikrotikUbiquitiMetrics()
        client: paramiko.SSHClient | None = None
        try:
            client = _connect(self.mikrotik)

            m.online = _ping_via_mikrotik(client, ubiquiti_ip)

            neighbors = _get_neighbors(client)
            m.neighbor_seen = ubiquiti_ip in neighbors

            if m.online and mikrotik_interface:
                m.client_count = _count_bridge_hosts(client, mikrotik_interface)

        except MikrotikSshError as exc:
            m.error = str(exc)[:200]
            logger.warning("MikrotikSshMonitor(%s → %s) : %s", self.mikrotik, ubiquiti_ip, exc)
        except Exception as exc:
            m.error = f"Erreur inattendue : {exc}"[:200]
            logger.exception("MikrotikSshMonitor inattendu (%s → %s)", self.mikrotik, ubiquiti_ip)
        finally:
            if client is not None:
                client.close()

        return m
