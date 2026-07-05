"""
Commandes distantes : MikroTik RouterOS (SSH) pour blocage MAC — abonnés Wi‑Fi Simple.

Wi‑Fi Zone : à l’activation d’un ticket (`USED`), création d’un utilisateur `/ip hotspot user`
(login + mot de passe = code du ticket, `limit-uptime` selon la durée).

Abonnés Wi‑Fi Simple : filtre bridge MAC sur le routeur de bord (hAP ax³, etc.).

Secrets : utiliser `NetworkDevice.password_hint` au format `env:NOM_VARIABLE`.
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

import paramiko

from django.conf import settings

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice, Site
    from apps.wifi_zone.models import Ticket

logger = logging.getLogger(__name__)


def _build_ssh_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    known_hosts = (getattr(settings, "MIKROTIK_SSH_KNOWN_HOSTS_FILE", "") or "").strip()
    if known_hosts and os.path.isfile(known_hosts):
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        logger.warning(
            "MIKROTIK_SSH_KNOWN_HOSTS_FILE non configuré — "
            "les clés SSH MikroTik ne sont pas vérifiées (risque MITM). "
            "Définir MIKROTIK_SSH_KNOWN_HOSTS_FILE en production."
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def normalize_mac(mac: str) -> str:
    parts = re.split(r"[:-]", mac.strip())
    if len(parts) != 6:
        raise ValueError(f"MAC invalide : {mac!r}")
    octets: list[str] = []
    for p in parts:
        if not p or not all(c in "0123456789abcdefABCDEF" for c in p):
            raise ValueError(f"MAC invalide : {mac!r}")
        v = int(p, 16)
        if v > 255:
            raise ValueError(f"MAC invalide : {mac!r}")
        octets.append(f"{v:02X}")
    return ":".join(octets)


def _comment_for_mac(mac: str) -> str:
    return f"faso-isp-{normalize_mac(mac).replace(':', '')}"


def _resolve_ssh_password(device: NetworkDevice) -> str | None:
    hint = (device.password_hint or "").strip()
    if hint.startswith("env:"):
        key = hint[4:].strip()
        return os.environ.get(key)
    if hint:
        val = os.environ.get(hint)
        if val:
            return val
    return os.environ.get(getattr(settings, "MIKROTIK_FALLBACK_SSH_PASSWORD_ENV", ""), None)


def _mikrotik_bridge_name(device: NetworkDevice) -> str:
    name = getattr(device, "mikrotik_bridge_name", None) or ""
    name = name.strip()
    if name:
        if not re.match(r"^[a-zA-Z0-9_-]{1,48}$", name):
            raise ValueError(f"Nom de bridge MikroTik invalide : {name!r}")
        return name
    default = getattr(settings, "MIKROTIK_DEFAULT_BRIDGE_NAME", "bridge")
    return default.strip() or "bridge"


def _ssh_exec(device: NetworkDevice, command: str) -> tuple[int, str, str]:
    password = _resolve_ssh_password(device)
    if not password:
        logger.error(
            "Mot de passe SSH MikroTik manquant pour %s — définir password_hint=env:… "
            "ou la variable indiquée.",
            device,
        )
        return 1, "", "missing_password"

    username = (device.username or "").strip() or getattr(
        settings, "MIKROTIK_DEFAULT_USERNAME", "admin"
    )

    client = _build_ssh_client()
    try:
        client.connect(
            hostname=device.management_host,
            port=device.ssh_port or 22,
            username=username,
            password=password,
            allow_agent=False,
            look_for_keys=False,
            timeout=getattr(settings, "MIKROTIK_SSH_TIMEOUT", 25),
        )
        stdin, stdout, stderr = client.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_status = stdout.channel.recv_exit_status()
        return exit_status, out, err
    finally:
        client.close()


def _mikrotik_remove_bridge_filter(device: NetworkDevice, comment: str) -> bool:
    cmd = f'/interface bridge filter remove [find comment="{comment}"]'
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        logger.info("[DRY-RUN] MikroTik %s : %s", device.management_host, cmd)
        return True
    exit_status, out, err = _ssh_exec(device, cmd)
    if err == "missing_password":
        return False
    if exit_status != 0:
        logger.warning(
            "MikroTik remove filter exit=%s host=%s err=%s out=%s",
            exit_status,
            device.management_host,
            err,
            out,
        )
    return True


def _mikrotik_add_drop_by_mac(device: NetworkDevice, mac: str) -> bool:
    bridge = _mikrotik_bridge_name(device)
    comment = _comment_for_mac(mac)
    mac_n = normalize_mac(mac)
    cmd = (
        f'/interface bridge filter add bridge={bridge} chain=forward '
        f'src-mac-address={mac_n} action=drop comment="{comment}"'
    )
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        logger.info("[DRY-RUN] MikroTik %s : %s", device.management_host, cmd)
        return True
    if not _mikrotik_remove_bridge_filter(device, comment):
        return False
    exit_status, out, err = _ssh_exec(device, cmd)
    if err == "missing_password":
        return False
    if exit_status != 0:
        logger.error(
            "Échec ajout filtre bridge MikroTik exit=%s host=%s cmd=%s err=%s out=%s",
            exit_status,
            device.management_host,
            cmd,
            err,
            out,
        )
        return False
    return True


def block_mac_address(device: NetworkDevice, mac: str) -> bool:
    if not device.is_active:
        logger.warning("Équipement %s inactif — pas de blocage.", device)
        return False
    if device.vendor == device.Vendor.MIKROTIK:
        try:
            normalize_mac(mac)
        except ValueError as e:
            logger.error("%s", e)
            return False
        return _mikrotik_add_drop_by_mac(device, mac)
    if device.vendor == device.Vendor.UBIQUITI:
        logger.warning(
            "Ubiquiti non implémenté pour block_mac — prévoir SSH airOS ou API UNMS pour %s.",
            device,
        )
        return False
    logger.warning("Vendor %s non pris en charge pour block_mac (%s).", device.vendor, device)
    return False


def unblock_mac_address(device: NetworkDevice, mac: str) -> bool:
    if not device.is_active:
        logger.warning("Équipement %s inactif — pas de déblocage.", device)
        return False
    if device.vendor == device.Vendor.MIKROTIK:
        try:
            normalize_mac(mac)
        except ValueError as e:
            logger.error("%s", e)
            return False
        comment = _comment_for_mac(mac)
        if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
            logger.info("[DRY-RUN] MikroTik unblock %s comment=%s", device.management_host, comment)
            return True
        exit_status, out, err = _ssh_exec(
            device,
            f'/interface bridge filter remove [find comment="{comment}"]',
        )
        if err == "missing_password":
            return False
        if exit_status != 0:
            logger.warning(
                "Déblocage MikroTik exit=%s host=%s (règle absente ou autre) err=%s out=%s",
                exit_status,
                device.management_host,
                err,
                out,
            )
        return True
    if device.vendor == device.Vendor.UBIQUITI:
        logger.warning("Ubiquiti non implémenté pour unblock_mac (%s).", device)
        return False
    logger.warning("Vendor %s non pris en charge pour unblock_mac (%s).", device.vendor, device)
    return False


def sync_wifi_simple_subscriber_access(
    cpe_device: NetworkDevice,
    mac: str,
    *,
    should_allow: bool,
) -> bool:
    """Orchestre blocage / déblocage selon paiement à jour."""
    if should_allow:
        return unblock_mac_address(cpe_device, mac)
    return block_mac_address(cpe_device, mac)


_HOTSPOT_PROFILE_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def duration_to_hotspot_limit_uptime(duration: str) -> str:
    """Convertit Ticket.duration en valeur RouterOS `limit-uptime` (aligné profils MikroTik typiques)."""
    from apps.wifi_zone.models import Ticket

    mapping = {
        Ticket.Duration.THREE_HOURS: "3h",
        Ticket.Duration.ONE_DAY: "1d",
        Ticket.Duration.ONE_WEEK: "1w",
        Ticket.Duration.THIRTY_DAYS: "4w2d",
    }
    # Anciennes valeurs en base avant migration de données
    legacy = {"1h": "3h", "24h": "1d", "30d": "4w2d"}
    if duration in legacy:
        return legacy[duration]
    if duration not in mapping:
        raise ValueError(f"Durée ticket inconnue : {duration!r}")
    return mapping[duration]


def _normalize_ticket_duration_key(duration: str) -> str:
    """Clé durée canonique (3h, 1d, 1w, 30j)."""
    from apps.wifi_zone.models import Ticket

    legacy_duration = {"1h": Ticket.Duration.THREE_HOURS, "24h": Ticket.Duration.ONE_DAY}
    if duration in legacy_duration:
        return legacy_duration[duration]
    return duration


def default_hotspot_profile_for_duration(duration: str) -> str:
    """Profil RouterOS selon la durée — uniquement les paramètres globaux (settings / .env)."""
    from apps.wifi_zone.models import Ticket

    d = _normalize_ticket_duration_key(duration)
    mapping = {
        Ticket.Duration.THREE_HOURS: getattr(
            settings, "MIKROTIK_HOTSPOT_PROFILE_3H", "Profil-2H"
        ),
        Ticket.Duration.ONE_DAY: getattr(
            settings, "MIKROTIK_HOTSPOT_PROFILE_1D", "Profil-24H"
        ),
        Ticket.Duration.ONE_WEEK: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_1W", "7j"),
        Ticket.Duration.THIRTY_DAYS: getattr(
            settings, "MIKROTIK_HOTSPOT_PROFILE_30J", "Profil-30Jours"
        ),
    }
    if d not in mapping:
        raise ValueError(f"Durée ticket inconnue pour profil : {duration!r}")
    return mapping[d]


def resolve_hotspot_profile_for_ticket(ticket: Ticket) -> str:
    """
    Profil hotspot pour un ticket : site (unique ou par durée), puis défaut global, puis settings.
    Le routeur utilisé est celui du site (`wifi_zone_hotspot_device` ou premier MikroTik du site).
    """
    from apps.wifi_zone.models import Ticket as T

    site = ticket.site
    single = (getattr(site, "wifi_zone_hotspot_profile", None) or "").strip()
    if single:
        return single

    default_all = (getattr(settings, "MIKROTIK_HOTSPOT_DEFAULT_PROFILE", "") or "").strip()
    if default_all:
        return default_all

    d = _normalize_ticket_duration_key(ticket.duration)
    site_field_by_duration = {
        T.Duration.THREE_HOURS: "wifi_zone_profile_3h",
        T.Duration.ONE_DAY: "wifi_zone_profile_1d",
        T.Duration.ONE_WEEK: "wifi_zone_profile_1w",
        T.Duration.THIRTY_DAYS: "wifi_zone_profile_30j",
    }
    if d not in site_field_by_duration:
        raise ValueError(f"Durée ticket inconnue pour profil : {ticket.duration!r}")
    field_name = site_field_by_duration[d]
    site_profile = (getattr(site, field_name, None) or "").strip()
    if site_profile:
        return site_profile

    return default_hotspot_profile_for_duration(d)


def resolve_wifi_zone_mikrotik_for_site(site: Site) -> NetworkDevice | None:
    """Routeur MikroTik pour provisionner les vouchers du site (Wi‑Fi Zone)."""
    from apps.core.models import NetworkDevice

    dev_id = getattr(site, "wifi_zone_hotspot_device_id", None)
    if dev_id:
        dev = (
            NetworkDevice.objects.filter(
                pk=dev_id,
                vendor=NetworkDevice.Vendor.MIKROTIK,
                is_active=True,
            )
            .select_related("site")
            .first()
        )
        if dev:
            return dev
    return (
        NetworkDevice.objects.filter(
            site_id=site.pk,
            vendor=NetworkDevice.Vendor.MIKROTIK,
            is_active=True,
        )
        .order_by("pk")
        .first()
    )


def _validate_hotspot_profile_name(profile: str) -> str:
    p = profile.strip()
    if not _HOTSPOT_PROFILE_RE.match(p):
        raise ValueError(f"Nom de profil Hotspot RouterOS invalide : {profile!r}")
    return p


def _mikrotik_hotspot_upsert_user(
    device: NetworkDevice,
    *,
    username: str,
    password: str,
    profile: str,
    limit_uptime: str,
    comment: str,
) -> tuple[bool, str]:
    if not device.is_active:
        return False, "Équipement inactif."
    prof = _validate_hotspot_profile_name(profile)
    if any(c in username for c in '"\\\n\r\t'):
        return False, "Caractères non autorisés dans le code / nom utilisateur."
    if any(c in password for c in '"\\\n\r\t'):
        return False, "Caractères non autorisés dans le mot de passe."
    if any(c in comment for c in '"\\\n\r'):
        comment = re.sub(r'["\\\n\r]', "", comment)
    server = (getattr(settings, "MIKROTIK_HOTSPOT_SERVER", "") or "").strip()
    server_arg = f" server={server}" if server else ""
    cmd = (
        f'/ip hotspot user remove [find name="{username}"]; '
        f'/ip hotspot user add name="{username}" password="{password}" '
        f"profile={prof} limit-uptime={limit_uptime}{server_arg} "
        f'comment="{comment}"'
    )
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        logger.info("[DRY-RUN] MikroTik hotspot %s : %s", device.management_host, cmd)
        return True, ""
    exit_status, out, err = _ssh_exec(device, cmd)
    if err == "missing_password":
        return False, "Mot de passe SSH manquant (password_hint / env)."
    if exit_status != 0:
        msg = (err or out or "échec SSH").strip()[:500]
        logger.error(
            "Hotspot user exit=%s host=%s err=%s out=%s",
            exit_status,
            device.management_host,
            err,
            out,
        )
        return False, msg or "Échec commande RouterOS."
    return True, ""


def provision_wifi_zone_hotspot_for_ticket(ticket: Ticket) -> tuple[bool, str]:
    """
    Crée (ou remplace) l’utilisateur Hotspot sur le MikroTik du site pour ce ticket.

    Login et mot de passe RouterOS = code du ticket (charset alphanum. maj. défini à la génération).
    """
    site = ticket.site
    device = resolve_wifi_zone_mikrotik_for_site(site)
    if device is None:
        return False, "Aucun MikroTik actif pour ce site (paramétrez le routeur Hotspot sur le site)."
    try:
        profile = resolve_hotspot_profile_for_ticket(ticket)
    except ValueError as e:
        return False, str(e)
    try:
        limit_uptime = duration_to_hotspot_limit_uptime(ticket.duration)
    except ValueError as e:
        return False, str(e)

    code = ticket.code.strip()
    comment = f"faso-wifi-zone-ticket-{ticket.pk}"
    return _mikrotik_hotspot_upsert_user(
        device,
        username=code,
        password=code,
        profile=profile,
        limit_uptime=limit_uptime,
        comment=comment,
    )


def _ros_hotspot_remove_no_user_ok(exit_status: int, out: str, err: str) -> bool:
    """RouterOS : remove [find …] sans correspondance — souvent message d’échec mais état OK."""
    if exit_status == 0:
        return True
    blob = f"{err} {out}".lower()
    return any(
        x in blob
        for x in (
            "no such item",
            "no entries found",
            "couldn't remove",
            "failure: no such",
        )
    )


def fetch_mikrotik_hotspot_active_users(device: NetworkDevice) -> set[str]:
    """Retourne l'ensemble des codes (usernames) actuellement connectés sur le hotspot."""
    if not device.is_active:
        return set()
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        logger.info("[DRY-RUN] fetch active users %s", device.management_host)
        return set()
    exit_status, out, err = _ssh_exec(
        device, "/ip hotspot active print terse proplist=user"
    )
    if exit_status != 0:
        logger.warning(
            "fetch_active_users exit=%s host=%s err=%s", exit_status, device.management_host, err
        )
        return set()
    users: set[str] = set()
    for line in out.splitlines():
        m = re.search(r"\buser=(\S+)", line)
        if m:
            users.add(m.group(1))
    return users


def fetch_mikrotik_hotspot_all_users(device: NetworkDevice) -> list[dict]:
    """Retourne la liste complète des utilisateurs hotspot provisionnés."""
    if not device.is_active:
        return []
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        logger.info("[DRY-RUN] fetch all hotspot users %s", device.management_host)
        return []
    exit_status, out, err = _ssh_exec(
        device, "/ip hotspot user print terse proplist=name,profile,comment,disabled"
    )
    if exit_status != 0:
        logger.warning(
            "fetch_all_users exit=%s host=%s err=%s", exit_status, device.management_host, err
        )
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


def remove_wifi_zone_hotspot_for_ticket(ticket: Ticket) -> tuple[bool, str]:
    """
    Supprime l’utilisateur Hotspot (login = code du ticket) sur le MikroTik du site.

    À appeler lorsque le ticket est expiré, révoqué ou repassé disponible.
    """
    site = ticket.site
    device = resolve_wifi_zone_mikrotik_for_site(site)
    if device is None:
        return True, ""

    code = ticket.code.strip()
    if any(c in code for c in '"\\\n\r\t'):
        return False, "Caractères non autorisés dans le code pour la commande RouterOS."

    cmd = f'/ip hotspot user remove [find name="{code}"]'
    if getattr(settings, "ROUTER_CONTROL_DRY_RUN", False):
        logger.info("[DRY-RUN] MikroTik hotspot remove %s : %s", device.management_host, cmd)
        return True, ""

    exit_status, out, err = _ssh_exec(device, cmd)
    if err == "missing_password":
        return False, "Mot de passe SSH manquant (password_hint / env)."

    if _ros_hotspot_remove_no_user_ok(exit_status, out, err):
        if exit_status != 0:
            logger.info(
                "Retrait Hotspot considéré OK (exit=%s) host=%s out=%s err=%s",
                exit_status,
                device.management_host,
                out,
                err,
            )
        return True, ""

    msg = (err or out or "échec SSH").strip()[:500]
    logger.error(
        "Retrait Hotspot exit=%s host=%s err=%s out=%s",
        exit_status,
        device.management_host,
        err,
        out,
    )
    return False, msg or "Échec retrait utilisateur RouterOS."
