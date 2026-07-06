"""
Client MikroTik RouterOS — API librouteros (port 8728 / 8729-SSL) avec fallback SSH/paramiko.

Utilisation :
    from apps.core.services.routeros_client import RouterOSClient

    with RouterOSClient(device) as client:
        ok, err = client.hotspot_user_upsert(name="ABC123", ...)

Transport sélectionné automatiquement :
  1. API RouterOS (librouteros) sur device.api_port (défaut 8728 si non configuré)
  2. Fallback SSH/paramiko si l'API est inaccessible

Credential resolution (password_hint) :
  - "enc:<token>"  → déchiffrement Fernet (ENCRYPTION_KEY)
  - "env:<VAR>"    → variable d'environnement OS
  - "<VAR>"        → variable d'environnement OS (compatibilité legacy)
  - fallback       → MIKROTIK_FALLBACK_SSH_PASSWORD_ENV
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice

logger = logging.getLogger(__name__)

_ROSAPI_PORT_DEFAULT = 8728
_ROSAPI_SSL_PORT_DEFAULT = 8729
_API_CONNECT_TIMEOUT = 10  # secondes pour tenter l'API avant fallback SSH


class RouterOSError(Exception):
    """Erreur de connexion ou d'opération RouterOS."""


class RouterOSClient:
    """
    Client MikroTik RouterOS avec sélection automatique du transport.

    Contexte manager recommandé :
        with RouterOSClient(device) as client:
            client.hotspot_user_upsert(...)
    """

    def __init__(self, device: NetworkDevice) -> None:
        self.device = device
        self._conn = None       # connexion active (librouteros ou paramiko.SSHClient)
        self._mode = "none"     # "api" | "ssh" | "dry_run" | "none"
        self._dry_run: bool = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
        self._timeout: int = int(getattr(settings, "MIKROTIK_SSH_TIMEOUT", 25))

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> str:
        """
        Établit la connexion. Retourne le mode utilisé ('api', 'ssh', 'dry_run').
        Lève RouterOSError si aucun transport n'est disponible.
        """
        if self._dry_run:
            self._mode = "dry_run"
            return "dry_run"

        password = resolve_device_credential(self.device)
        if not password:
            raise RouterOSError(
                f"Mot de passe manquant pour {self.device} — "
                "vérifiez password_hint (env:VAR, enc:TOKEN) ou MIKROTIK_FALLBACK_SSH_PASSWORD_ENV."
            )

        username = (self.device.username or "").strip() or getattr(
            settings, "MIKROTIK_DEFAULT_USERNAME", "admin"
        )
        host = self.device.management_host

        # ── 1. API RouterOS ──────────────────────────────────────────────────
        ros_port = _effective_api_port(self.device)
        try:
            import librouteros
            conn = librouteros.connect(
                host=host,
                username=username,
                password=password,
                port=ros_port,
                timeout=_API_CONNECT_TIMEOUT,
            )
            self._conn = conn
            self._mode = "api"
            logger.debug(
                "RouterOS API connecté %s:%s (device=%s)", host, ros_port, self.device.pk
            )
            return "api"
        except Exception as exc:
            logger.info(
                "RouterOS API inaccessible %s:%s (%s) — tentative SSH",
                host,
                ros_port,
                exc,
            )

        # ── 2. Fallback SSH ──────────────────────────────────────────────────
        try:
            ssh = _build_ssh_client()
            ssh.connect(
                hostname=host,
                port=self.device.ssh_port or 22,
                username=username,
                password=password,
                allow_agent=False,
                look_for_keys=False,
                timeout=self._timeout,
            )
            self._conn = ssh
            self._mode = "ssh"
            logger.debug("SSH connecté %s (device=%s)", host, self.device.pk)
            return "ssh"
        except Exception as exc:
            raise RouterOSError(
                f"Connexion impossible (API:{ros_port} et SSH:{self.device.ssh_port or 22}) "
                f"à {host} : {exc}"
            ) from exc

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._mode = "none"

    def __enter__(self) -> RouterOSClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def transport_mode(self) -> str:
        return self._mode

    # ── transport internes ────────────────────────────────────────────────────

    def _api(self, path: str, **kwargs) -> list[dict]:
        return list(self._conn(path, **kwargs))

    def _ssh_exec(self, command: str) -> tuple[int, str, str]:
        stdin, stdout, stderr = self._conn.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    # ── opérations Hotspot ────────────────────────────────────────────────────

    def hotspot_user_upsert(
        self,
        name: str,
        password: str,
        profile: str,
        limit_uptime: str,
        comment: str,
        server: str = "",
    ) -> tuple[bool, str]:
        """Crée ou remplace un utilisateur /ip hotspot user (idempotent)."""
        if self._mode == "dry_run":
            logger.info(
                "[DRY-RUN] hotspot_user_upsert name=%s on %s",
                name,
                self.device.management_host,
            )
            return True, ""

        self.hotspot_user_remove(name)  # suppression préalable pour idempotence

        if self._mode == "api":
            try:
                kwargs: dict = {
                    "name": name,
                    "password": password,
                    "profile": profile,
                    "limit-uptime": limit_uptime,
                    "comment": comment,
                }
                if server:
                    kwargs["server"] = server
                self._api("/ip/hotspot/user/add", **kwargs)
                return True, ""
            except Exception as exc:
                msg = str(exc)[:500]
                logger.error("hotspot_user_upsert API %s : %s", name, msg)
                return False, msg

        # SSH fallback
        server_arg = f" server={server}" if server else ""
        cmd = (
            f'/ip hotspot user add name="{name}" password="{password}" '
            f"profile={profile} limit-uptime={limit_uptime}{server_arg} "
            f'comment="{comment}"'
        )
        rc, out, err = self._ssh_exec(cmd)
        if rc != 0:
            msg = (err or out or "erreur SSH").strip()[:500]
            logger.error("hotspot_user_upsert SSH %s rc=%s : %s", name, rc, msg)
            return False, msg
        return True, ""

    def hotspot_user_remove(self, name: str) -> bool:
        """Supprime un utilisateur hotspot (silencieux si absent)."""
        if self._mode == "dry_run":
            return True

        if self._mode == "api":
            try:
                rows = self._api("/ip/hotspot/user/print", **{"?name": name})
                for row in rows:
                    self._api("/ip/hotspot/user/remove", **{".id": row[".id"]})
                return True
            except Exception as exc:
                logger.warning("hotspot_user_remove API %s : %s", name, exc)
                return False

        # SSH
        rc, out, err = self._ssh_exec(f'/ip hotspot user remove [find name="{name}"]')
        return _ros_remove_ok(rc, out, err)

    def hotspot_active_users(self) -> set[str]:
        """Retourne les logins actuellement connectés au hotspot."""
        if self._mode == "dry_run":
            return set()

        if self._mode == "api":
            try:
                rows = self._api("/ip/hotspot/active/print")
                return {r.get("user", "") for r in rows if r.get("user")}
            except Exception as exc:
                logger.warning("hotspot_active_users API : %s", exc)
                return set()

        rc, out, _ = self._ssh_exec("/ip hotspot active print terse proplist=user")
        if rc != 0:
            return set()
        users: set[str] = set()
        for line in out.splitlines():
            m = re.search(r"\buser=(\S+)", line)
            if m:
                users.add(m.group(1))
        return users

    def hotspot_all_users(self) -> list[dict]:
        """Liste complète des utilisateurs hotspot provisionnés."""
        if self._mode == "dry_run":
            return []

        if self._mode == "api":
            try:
                return list(
                    self._api("/ip/hotspot/user/print")
                )
            except Exception as exc:
                logger.warning("hotspot_all_users API : %s", exc)
                return []

        rc, out, _ = self._ssh_exec(
            "/ip hotspot user print terse proplist=name,profile,comment,disabled"
        )
        if rc != 0:
            return []
        entries: list[dict] = []
        for line in out.splitlines():
            entry: dict = {}
            for key in ("name", "profile", "comment", "disabled"):
                m = re.search(rf"\b{key}=(\S+)", line)
                if m:
                    entry[key] = m.group(1)
            if "name" in entry:
                entries.append(entry)
        return entries

    # ── opérations bridge filter (blocage MAC) ────────────────────────────────

    def bridge_filter_remove(self, comment: str) -> bool:
        """Supprime les règles bridge filter portant ce commentaire (idempotent)."""
        if self._mode == "dry_run":
            return True

        if self._mode == "api":
            try:
                rows = self._api("/interface/bridge/filter/print", **{"?comment": comment})
                for row in rows:
                    self._api("/interface/bridge/filter/remove", **{".id": row[".id"]})
                return True
            except Exception as exc:
                logger.warning("bridge_filter_remove API comment=%s : %s", comment, exc)
                return False

        rc, out, err = self._ssh_exec(
            f'/interface bridge filter remove [find comment="{comment}"]'
        )
        return _ros_remove_ok(rc, out, err)

    def bridge_filter_drop_by_mac(self, mac: str, bridge: str, comment: str) -> bool:
        """Ajoute une règle DROP pour l'adresse MAC sur le bridge spécifié."""
        if self._mode == "dry_run":
            logger.info(
                "[DRY-RUN] bridge_filter_drop mac=%s bridge=%s on %s",
                mac,
                bridge,
                self.device.management_host,
            )
            return True

        self.bridge_filter_remove(comment)

        if self._mode == "api":
            try:
                self._api(
                    "/interface/bridge/filter/add",
                    bridge=bridge,
                    chain="forward",
                    **{"src-mac-address": mac},
                    action="drop",
                    comment=comment,
                )
                return True
            except Exception as exc:
                logger.error(
                    "bridge_filter_drop_by_mac API mac=%s bridge=%s : %s", mac, bridge, exc
                )
                return False

        cmd = (
            f"/interface bridge filter add bridge={bridge} chain=forward "
            f"src-mac-address={mac} action=drop "
            f'comment="{comment}"'
        )
        rc, out, err = self._ssh_exec(cmd)
        if rc != 0:
            logger.error(
                "bridge_filter_drop SSH rc=%s mac=%s bridge=%s err=%s out=%s",
                rc,
                mac,
                bridge,
                err,
                out,
            )
            return False
        return True


# ── fonctions utilitaires (module-level) ───────────────────────────────────────

def resolve_device_credential(device: NetworkDevice) -> str | None:
    """
    Résout le mot de passe de l'équipement, dans cet ordre de priorité :
      1. encrypted_password (Fernet) — si renseigné
      2. password_hint "enc:<token>"  — token Fernet dans le champ hint (legacy)
      3. password_hint "env:<VAR>"    — variable d'environnement OS
      4. password_hint "<VAR>"        — variable d'environnement OS (legacy)
      5. MIKROTIK_FALLBACK_SSH_PASSWORD_ENV
    """
    # 1. Champ chiffré dédié (prioritaire)
    encrypted = (getattr(device, "encrypted_password", None) or "").strip()
    if encrypted:
        from apps.core.services.encryption import decrypt_credential
        return decrypt_credential(encrypted)

    hint = (device.password_hint or "").strip()

    # 2. Ancien format enc: dans password_hint
    if hint.startswith("enc:"):
        from apps.core.services.encryption import decrypt_credential
        return decrypt_credential(hint[4:])

    # 3. Variable d'environnement via env:
    if hint.startswith("env:"):
        return os.environ.get(hint[4:].strip())

    # 4. Nom de variable d'environnement brut (legacy)
    if hint:
        val = os.environ.get(hint)
        if val:
            return val

    # 5. Fallback global
    fallback_env = (getattr(settings, "MIKROTIK_FALLBACK_SSH_PASSWORD_ENV", "") or "").strip()
    if fallback_env:
        return os.environ.get(fallback_env)

    return None


def _effective_api_port(device: NetworkDevice) -> int:
    """
    Port API RouterOS effectif.
    Si api_port vaut 0, 80 ou 443 (valeurs par défaut non configurées), utilise 8728.
    """
    port = getattr(device, "api_port", 0) or 0
    if port in (0, 80, 443):
        return _ROSAPI_PORT_DEFAULT
    return port


def _build_ssh_client():
    import paramiko

    client = paramiko.SSHClient()
    known_hosts = (getattr(settings, "MIKROTIK_SSH_KNOWN_HOSTS_FILE", "") or "").strip()
    if known_hosts and os.path.isfile(known_hosts):
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        logger.warning(
            "MIKROTIK_SSH_KNOWN_HOSTS_FILE non configuré — "
            "clés SSH MikroTik non vérifiées (risque MITM). "
            "Configurez MIKROTIK_SSH_KNOWN_HOSTS_FILE en production."
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def _ros_remove_ok(rc: int, out: str, err: str) -> bool:
    """RouterOS remove [find ...] sans correspondance — souvent exit≠0 mais état correct."""
    if rc == 0:
        return True
    blob = f"{err} {out}".lower()
    return any(
        x in blob
        for x in ("no such item", "no entries found", "couldn't remove", "failure: no such")
    )
