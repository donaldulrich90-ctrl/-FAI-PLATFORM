"""
Commandes distantes MikroTik RouterOS — Wi-Fi Zone (hotspot) et Wi-Fi Simple (MAC filter).

Transport : API RouterOS via librouteros (port 8728/8729-SSL) avec fallback SSH/paramiko.
Centralisé dans RouterOSClient (apps.core.services.routeros_client).

Wi-Fi Zone  : création/suppression d'utilisateurs /ip hotspot user pour les tickets.
Wi-Fi Simple: blocage/déblocage MAC via /interface bridge filter.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from django.conf import settings

from apps.core.services.routeros_client import RouterOSClient, RouterOSError, _ros_remove_ok
from apps.monitoring.audit import log_router_action

if TYPE_CHECKING:
    from apps.core.models import NetworkDevice, Site
    from apps.wifi_zone.models import Ticket

logger = logging.getLogger(__name__)


# ── utilitaires MAC ────────────────────────────────────────────────────────────

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


def _mikrotik_bridge_name(device: NetworkDevice) -> str:
    name = (getattr(device, "mikrotik_bridge_name", None) or "").strip()
    if name:
        if not re.match(r"^[a-zA-Z0-9_-]{1,48}$", name):
            raise ValueError(f"Nom de bridge MikroTik invalide : {name!r}")
        return name
    default = getattr(settings, "MIKROTIK_DEFAULT_BRIDGE_NAME", "bridge")
    return default.strip() or "bridge"


# ── utilitaires profils hotspot ───────────────────────────────────────────────

_HOTSPOT_PROFILE_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _validate_hotspot_profile_name(profile: str) -> str:
    p = profile.strip()
    if not _HOTSPOT_PROFILE_RE.match(p):
        raise ValueError(f"Nom de profil Hotspot RouterOS invalide : {profile!r}")
    return p


def _normalize_ticket_duration_key(duration: str) -> str:
    from apps.wifi_zone.models import Ticket

    legacy = {"1h": Ticket.Duration.THREE_HOURS, "24h": Ticket.Duration.ONE_DAY}
    return legacy.get(duration, duration)


def duration_to_hotspot_limit_uptime(duration: str) -> str:
    from apps.wifi_zone.models import Ticket

    mapping = {
        Ticket.Duration.TWO_HOURS: "2h",
        Ticket.Duration.THREE_HOURS: "3h",
        Ticket.Duration.FOUR_HOURS: "4h",
        Ticket.Duration.ONE_DAY: "1d",
        Ticket.Duration.FIVE_DAYS: "5d",
        Ticket.Duration.ONE_WEEK: "1w",
        Ticket.Duration.THIRTY_DAYS: "4w2d",
        Ticket.Duration.UNLIMITED: "0s",
    }
    legacy = {"1h": "3h", "24h": "1d", "30d": "4w2d"}
    if duration in legacy:
        return legacy[duration]
    if duration not in mapping:
        raise ValueError(f"Durée ticket inconnue : {duration!r}")
    return mapping[duration]


def default_hotspot_profile_for_duration(duration: str) -> str:
    from apps.wifi_zone.models import Ticket

    d = _normalize_ticket_duration_key(duration)
    mapping = {
        Ticket.Duration.TWO_HOURS: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_2H", "2h"),
        Ticket.Duration.THREE_HOURS: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_3H", "Profil-2H"),
        Ticket.Duration.FOUR_HOURS: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_4H", "4h"),
        Ticket.Duration.ONE_DAY: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_1D", "Profil-24H"),
        Ticket.Duration.FIVE_DAYS: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_5J", "5j"),
        Ticket.Duration.ONE_WEEK: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_1W", "7j"),
        Ticket.Duration.THIRTY_DAYS: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_30J", "Profil-30Jours"),
        Ticket.Duration.UNLIMITED: getattr(settings, "MIKROTIK_HOTSPOT_PROFILE_ILLIMITE", "illimite"),
    }
    if d not in mapping:
        raise ValueError(f"Durée ticket inconnue pour profil : {duration!r}")
    return mapping[d]


def resolve_hotspot_profile_for_ticket(ticket: Ticket) -> str:
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
        T.Duration.TWO_HOURS: "wifi_zone_profile_2h",
        T.Duration.THREE_HOURS: "wifi_zone_profile_3h",
        T.Duration.FOUR_HOURS: "wifi_zone_profile_4h",
        T.Duration.ONE_DAY: "wifi_zone_profile_1d",
        T.Duration.FIVE_DAYS: "wifi_zone_profile_5j",
        T.Duration.ONE_WEEK: "wifi_zone_profile_1w",
        T.Duration.THIRTY_DAYS: "wifi_zone_profile_30j",
        T.Duration.UNLIMITED: "wifi_zone_profile_illimite",
    }
    if d not in site_field_by_duration:
        raise ValueError(f"Durée ticket inconnue pour profil : {ticket.duration!r}")
    site_profile = (getattr(site, site_field_by_duration[d], None) or "").strip()
    if site_profile:
        return site_profile

    return default_hotspot_profile_for_duration(d)


def resolve_wifi_zone_mikrotik_for_site(site: Site) -> NetworkDevice | None:
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


# ── API publique : blocage / déblocage MAC (Wi-Fi Simple) ─────────────────────

def block_mac_address(
    device: NetworkDevice,
    mac: str,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> bool:
    if not device.is_active:
        logger.warning("Équipement %s inactif — blocage annulé.", device)
        return False
    if device.vendor != device.Vendor.MIKROTIK:
        logger.warning("block_mac non implémenté pour vendor %s (%s).", device.vendor, device)
        return False
    try:
        mac_n = normalize_mac(mac)
    except ValueError as e:
        logger.error("%s", e)
        return False

    bridge = _mikrotik_bridge_name(device)
    comment = _comment_for_mac(mac_n)
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    try:
        with RouterOSClient(device) as client:
            ok = client.bridge_filter_drop_by_mac(mac_n, bridge, comment)
        log_router_action(
            device,
            "mac_block",
            target=mac_n,
            command_sent=f"bridge filter drop mac={mac_n} bridge={bridge}",
            success=ok,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        return ok
    except RouterOSError as exc:
        log_router_action(
            device,
            "mac_block",
            target=mac_n,
            success=False,
            error_message=str(exc)[:500],
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        logger.error("block_mac %s device=%s : %s", mac_n, device, exc)
        return False


def unblock_mac_address(
    device: NetworkDevice,
    mac: str,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> bool:
    if not device.is_active:
        logger.warning("Équipement %s inactif — déblocage annulé.", device)
        return False
    if device.vendor != device.Vendor.MIKROTIK:
        logger.warning("unblock_mac non implémenté pour vendor %s (%s).", device.vendor, device)
        return False
    try:
        mac_n = normalize_mac(mac)
    except ValueError as e:
        logger.error("%s", e)
        return False

    comment = _comment_for_mac(mac_n)
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    try:
        with RouterOSClient(device) as client:
            ok = client.bridge_filter_remove(comment)
        log_router_action(
            device,
            "mac_unblock",
            target=mac_n,
            command_sent=f"bridge filter remove comment={comment}",
            success=ok,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        return ok
    except RouterOSError as exc:
        log_router_action(
            device,
            "mac_unblock",
            target=mac_n,
            success=False,
            error_message=str(exc)[:500],
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        logger.error("unblock_mac %s device=%s : %s", mac_n, device, exc)
        return False


def sync_wifi_simple_subscriber_access(
    cpe_device: NetworkDevice,
    mac: str,
    *,
    should_allow: bool,
) -> bool:
    if should_allow:
        return unblock_mac_address(cpe_device, mac)
    return block_mac_address(cpe_device, mac)


# ── API publique : hotspot vouchers (Wi-Fi Zone) ──────────────────────────────

def disconnect_hotspot_session(
    device: NetworkDevice,
    session_id: str,
    username: str,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Déconnecte une session hotspot active via son identifiant RouterOS."""
    if not device.is_active:
        return False, "Équipement inactif."
    if device.vendor != device.Vendor.MIKROTIK:
        return False, "Déconnexion hotspot non implémentée pour ce vendor."

    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    try:
        with RouterOSClient(device) as client:
            ok = client.hotspot_active_remove_by_id(session_id)
        err_msg = "" if ok else "Échec déconnexion session RouterOS."
        log_router_action(
            device,
            "hotspot_disconnect",
            target=username,
            command_sent=f"hotspot active remove .id={session_id}",
            success=ok,
            error_message=err_msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        return ok, err_msg
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(
            device,
            "hotspot_disconnect",
            target=username,
            success=False,
            error_message=msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        logger.error("disconnect_hotspot device=%s session=%s : %s", device, session_id, exc)
        return False, msg


def fetch_mikrotik_hotspot_active_details(device: NetworkDevice) -> list[dict]:
    """Retourne les sessions actives avec détails (user, IP, MAC, uptime, bytes)."""
    if not device.is_active:
        return []
    try:
        with RouterOSClient(device) as client:
            return client.hotspot_active_details()
    except RouterOSError as exc:
        logger.warning("fetch_active_details device=%s : %s", device, exc)
        return []


def provision_wifi_zone_hotspot_for_ticket(
    ticket: Ticket,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Crée ou remplace l'utilisateur Hotspot sur le MikroTik du site pour ce ticket."""
    site = ticket.site
    device = resolve_wifi_zone_mikrotik_for_site(site)
    if device is None:
        return (
            False,
            "Aucun MikroTik actif pour ce site "
            "(paramétrez le routeur Hotspot sur le site).",
        )
    try:
        profile = _validate_hotspot_profile_name(resolve_hotspot_profile_for_ticket(ticket))
    except ValueError as e:
        return False, str(e)
    try:
        limit_uptime = duration_to_hotspot_limit_uptime(ticket.duration)
    except ValueError as e:
        return False, str(e)

    code = ticket.code.strip()
    if any(c in code for c in '"\\\n\r\t'):
        return False, "Caractères non autorisés dans le code ticket."

    password = (getattr(ticket, "hotspot_password", "") or "").strip() or code

    server = (getattr(settings, "MIKROTIK_HOTSPOT_SERVER", "") or "").strip()
    comment = f"faso-wifi-zone-ticket-{ticket.pk}"
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))

    try:
        with RouterOSClient(device) as client:
            ok, err_msg = client.hotspot_user_upsert(
                name=code,
                password=password,
                profile=profile,
                limit_uptime=limit_uptime,
                comment=comment,
                server=server,
            )
        log_router_action(
            device,
            "hotspot_provision",
            target=code,
            command_sent=f"hotspot user add name={code} profile={profile} limit-uptime={limit_uptime}",
            success=ok,
            error_message=err_msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        return ok, err_msg
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(
            device,
            "hotspot_provision",
            target=code,
            success=False,
            error_message=msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        logger.error("provision_hotspot ticket=%s device=%s : %s", ticket.pk, device, exc)
        return False, msg


def _provision_tickets_with_client(
    client: RouterOSClient,
    device: NetworkDevice,
    tickets,
    *,
    performed_by=None,
    ip_address: str | None = None,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Pousse une liste de tickets avec un RouterOSClient déjà ouvert (une connexion partagée)."""
    from apps.wifi_zone.models import Ticket as TicketModel
    from django.utils import timezone as tz

    server = (getattr(settings, "MIKROTIK_HOTSPOT_SERVER", "") or "").strip()
    now = tz.now()
    ok_count = 0
    errors: list[str] = []

    for ticket in tickets:
        code = ticket.code.strip()
        if any(c in code for c in '"\\\n\r\t'):
            err = f"Code {code!r} : caractères non autorisés."
            errors.append(err)
            TicketModel.objects.filter(pk=ticket.pk).update(hotspot_synced_at=None, hotspot_sync_error=err[:512])
            continue
        try:
            profile = _validate_hotspot_profile_name(resolve_hotspot_profile_for_ticket(ticket))
            limit_uptime = duration_to_hotspot_limit_uptime(ticket.duration)
        except ValueError as e:
            err = str(e)
            errors.append(f"{code}: {err}")
            TicketModel.objects.filter(pk=ticket.pk).update(hotspot_synced_at=None, hotspot_sync_error=err[:512])
            continue

        password = (getattr(ticket, "hotspot_password", "") or "").strip() or code
        comment = f"faso-wifi-zone-ticket-{ticket.pk}"
        ok, err_msg = client.hotspot_user_upsert(
            name=code,
            password=password,
            profile=profile,
            limit_uptime=limit_uptime,
            comment=comment,
            server=server,
        )
        log_router_action(
            device,
            "hotspot_provision",
            target=code,
            command_sent=f"hotspot user add name={code} profile={profile} limit-uptime={limit_uptime}",
            success=ok,
            error_message=err_msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        if ok:
            TicketModel.objects.filter(pk=ticket.pk).update(hotspot_synced_at=now, hotspot_sync_error="")
            ok_count += 1
        else:
            TicketModel.objects.filter(pk=ticket.pk).update(hotspot_synced_at=None, hotspot_sync_error=err_msg[:512])
            errors.append(f"{code}: {err_msg}")

    return ok_count, errors


def provision_wifi_zone_hotspot_for_batch(
    batch,
    tickets=None,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[int, list[str]]:
    """Pousse tous les tickets d'un lot sur le MikroTik du site (une seule connexion)."""
    from apps.wifi_zone.models import Ticket as TicketModel

    site = batch.site
    device = resolve_wifi_zone_mikrotik_for_site(site)
    if device is None:
        return 0, ["Aucun MikroTik actif pour ce site."]

    if tickets is None:
        tickets = list(TicketModel.objects.filter(batch=batch).select_related("site"))
    else:
        tickets = list(tickets)

    if not tickets:
        return 0, []

    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    try:
        with RouterOSClient(device) as client:
            return _provision_tickets_with_client(
                client, device, tickets,
                performed_by=performed_by,
                ip_address=ip_address,
                dry_run=dry_run,
            )
    except RouterOSError as exc:
        msg = str(exc)[:500]
        logger.error("provision_batch batch=%s device=%s : %s", batch.pk, device, exc)
        return 0, [f"Erreur connexion MikroTik : {msg}"]


def provision_wifi_zone_hotspot_for_device(
    device: NetworkDevice,
    tickets,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[int, list[str]]:
    """Pousse une liste de tickets sur un MikroTik déjà résolu (une seule connexion)."""
    if not device.is_active:
        return 0, ["Équipement inactif."]
    if device.vendor != device.Vendor.MIKROTIK:
        return 0, ["Vendor non supporté pour le hotspot."]

    tickets = list(tickets)
    if not tickets:
        return 0, []

    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    try:
        with RouterOSClient(device) as client:
            return _provision_tickets_with_client(
                client, device, tickets,
                performed_by=performed_by,
                ip_address=ip_address,
                dry_run=dry_run,
            )
    except RouterOSError as exc:
        msg = str(exc)[:500]
        logger.error("provision_device device=%s : %s", device, exc)
        return 0, [f"Erreur connexion MikroTik : {msg}"]


def sync_ticket_mac_from_mikrotik(
    ticket: Ticket,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Remonte MAC, IP et première utilisation depuis MikroTik vers le ticket."""
    from apps.wifi_zone.models import Ticket as TicketModel
    from django.utils import timezone as tz

    site = ticket.site
    device = resolve_wifi_zone_mikrotik_for_site(site)
    if device is None:
        return False, "Aucun MikroTik actif pour ce site."

    code = ticket.code.strip()
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))

    try:
        with RouterOSClient(device) as client:
            mac: str | None = None
            client_ip: str | None = None
            for session in client.hotspot_active_details():
                if session.get("user") == code:
                    mac = session.get("mac-address") or None
                    client_ip = session.get("address") or None
                    break
            if not mac:
                user_info = client.hotspot_user_details(code)
                if user_info:
                    mac = user_info.get("mac-address") or None
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(
            device, "other", target=code,
            success=False, error_message=msg, dry_run=dry_run,
            performed_by=performed_by, ip_address=ip_address,
        )
        logger.error("sync_mac ticket=%s device=%s : %s", ticket.pk, device, exc)
        return False, msg

    if not mac:
        return False, "Aucune session active ni MAC enregistrée sur le MikroTik."

    update_fields: dict = {"mac_address": mac}
    if client_ip:
        update_fields["client_ip"] = client_ip
    if ticket.first_used_at is None:
        update_fields["first_used_at"] = tz.now()

    TicketModel.objects.filter(pk=ticket.pk).update(**update_fields)
    log_router_action(
        device, "other", target=code,
        command_sent=f"hotspot active/user print where user={code}",
        success=True, dry_run=dry_run,
        performed_by=performed_by, ip_address=ip_address,
    )
    return True, mac


def remove_wifi_zone_hotspot_for_ticket(
    ticket: Ticket,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Supprime l'utilisateur Hotspot (login = code du ticket) sur le MikroTik du site."""
    site = ticket.site
    device = resolve_wifi_zone_mikrotik_for_site(site)
    if device is None:
        return True, ""

    code = ticket.code.strip()
    if any(c in code for c in '"\\\n\r\t'):
        return False, "Caractères non autorisés dans le code pour la commande RouterOS."

    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    try:
        with RouterOSClient(device) as client:
            ok = client.hotspot_user_remove(code)
            # IMPORTANT : retirer l'utilisateur ne déconnecte PAS un client déjà
            # connecté. On coupe donc aussi sa/ses session(s) active(s), sinon le
            # ticket « ne s'expire pas » côté client tant qu'il reste en ligne.
            try:
                for session in client.hotspot_active_details():
                    if session.get("user") == code:
                        sid = session.get(".id")
                        if sid:
                            client.hotspot_active_remove_by_id(sid)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning(
                    "remove_hotspot : échec coupure session active %s : %s", code, exc
                )
        err_msg = "" if ok else "Échec suppression utilisateur RouterOS."
        log_router_action(
            device,
            "hotspot_remove",
            target=code,
            command_sent=f"hotspot user remove [find name={code}] + active remove",
            success=ok,
            error_message=err_msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        return ok, err_msg
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(
            device,
            "hotspot_remove",
            target=code,
            success=False,
            error_message=msg,
            dry_run=dry_run,
            performed_by=performed_by,
            ip_address=ip_address,
        )
        logger.error("remove_hotspot ticket=%s device=%s : %s", ticket.pk, device, exc)
        return False, msg


# ── API publique : lecture état hotspot ───────────────────────────────────────

# ── API publique : abonnés domicile (address-list + ARP + SimpleQueue) ────────

def _subscriber_comment(subscriber_pk: int) -> str:
    return f"faso-abonne-{subscriber_pk}"


def activate_subscriber(
    subscriber,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Active un abonné : MAC → address-list abonnes-actifs + ARP statique."""
    device = subscriber.cpe_device
    if device is None:
        return False, "Aucun routeur MikroTik assigné à cet abonné."
    if not device.is_active:
        return False, "Équipement inactif."

    mac = (subscriber.mac_address or "").strip()
    ip = (str(subscriber.ip_static) if subscriber.ip_static else "").strip()
    comment = _subscriber_comment(subscriber.pk)
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))

    try:
        with RouterOSClient(device) as client:
            ok1 = client.address_list_remove_by_comment(comment)
            ok2 = True
            if mac:
                ok2 = client.address_list_add(mac, "abonnes-actifs", comment)
            ok3 = True
            if ip and mac:
                bridge = _mikrotik_bridge_name(device)
                ok3 = client.arp_add_static(ip, mac, bridge, comment)
            ok = ok1 and ok2 and ok3
        log_router_action(
            device, "mac_unblock", target=mac or str(subscriber.pk),
            command_sent=f"address-list add mac={mac} list=abonnes-actifs",
            success=ok, dry_run=dry_run,
            performed_by=performed_by, ip_address=ip_address,
        )
        if ok:
            subscriber.status = subscriber.Status.ACTIF
            subscriber.mac_blocked_on_network = False
            subscriber.is_payment_current = True
            subscriber.save(update_fields=["status", "mac_blocked_on_network", "is_payment_current", "updated_at"])
        return ok, "" if ok else "Erreur lors de l'activation RouterOS."
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(device, "mac_unblock", target=mac or str(subscriber.pk),
                          success=False, error_message=msg, dry_run=dry_run,
                          performed_by=performed_by, ip_address=ip_address)
        return False, msg


def suspend_subscriber(
    subscriber,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Suspend un abonné : retire de abonnes-actifs, ajoute à abonnes-suspendus."""
    device = subscriber.cpe_device
    if device is None:
        subscriber.status = subscriber.Status.SUSPENDU
        subscriber.save(update_fields=["status", "updated_at"])
        return True, "(pas de routeur assigné — statut mis à jour)"

    mac = (subscriber.mac_address or "").strip()
    comment = _subscriber_comment(subscriber.pk)
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))

    try:
        with RouterOSClient(device) as client:
            client.address_list_remove_by_comment(comment)
            ok = True
            if mac:
                ok = client.address_list_add(mac, "abonnes-suspendus", comment)
            client.arp_remove_by_comment(comment)
        log_router_action(
            device, "mac_block", target=mac or str(subscriber.pk),
            command_sent=f"address-list add mac={mac} list=abonnes-suspendus",
            success=ok, dry_run=dry_run,
            performed_by=performed_by, ip_address=ip_address,
        )
        if ok:
            subscriber.status = subscriber.Status.SUSPENDU
            subscriber.mac_blocked_on_network = True
            subscriber.save(update_fields=["status", "mac_blocked_on_network", "updated_at"])
        return ok, "" if ok else "Erreur lors de la suspension RouterOS."
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(device, "mac_block", target=mac or str(subscriber.pk),
                          success=False, error_message=msg, dry_run=dry_run,
                          performed_by=performed_by, ip_address=ip_address)
        return False, msg


def update_subscriber_speed(
    subscriber,
    speed_mbps: int,
    *,
    performed_by=None,
    ip_address: str | None = None,
) -> tuple[bool, str]:
    """Modifie la vitesse via Simple Queue sur l'IP statique de l'abonné."""
    device = subscriber.cpe_device
    if device is None:
        return False, "Aucun routeur MikroTik assigné."
    ip = (str(subscriber.ip_static) if subscriber.ip_static else "").strip()
    if not ip:
        return False, "IP statique non renseignée pour l'abonné."

    name = f"abonne-{subscriber.pk}"
    max_rate = f"{speed_mbps}M"
    comment = _subscriber_comment(subscriber.pk)
    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))

    try:
        with RouterOSClient(device) as client:
            ok, err = client.simple_queue_upsert(name, ip, max_rate, max_rate, comment)
        log_router_action(
            device, "other", target=ip,
            command_sent=f"queue simple set name={name} target={ip} max-limit={max_rate}",
            success=ok, error_message=err, dry_run=dry_run,
            performed_by=performed_by, ip_address=ip_address,
        )
        return ok, err
    except RouterOSError as exc:
        msg = str(exc)[:500]
        log_router_action(device, "other", target=ip, success=False,
                          error_message=msg, dry_run=dry_run,
                          performed_by=performed_by, ip_address=ip_address)
        return False, msg


def fetch_mikrotik_hotspot_active_users(device: NetworkDevice) -> set[str]:
    """Retourne les codes (usernames) actuellement connectés sur le hotspot."""
    if not device.is_active:
        return set()
    try:
        with RouterOSClient(device) as client:
            return client.hotspot_active_users()
    except RouterOSError as exc:
        logger.warning("fetch_active_users device=%s : %s", device, exc)
        return set()


def fetch_mikrotik_hotspot_hosts(device: NetworkDevice) -> set[str]:
    """Retourne les MACs présentes dans /ip hotspot host (connexions antenne actives)."""
    if not device.is_active:
        return set()
    try:
        with RouterOSClient(device) as client:
            hosts = client.hotspot_hosts()
            return {h.get("mac-address", "").upper() for h in hosts if h.get("mac-address")}
    except RouterOSError as exc:
        logger.warning("fetch_hotspot_hosts device=%s : %s", device, exc)
        return set()


def fetch_mikrotik_hotspot_all_users(device: NetworkDevice) -> list[dict]:
    """Retourne la liste complète des utilisateurs hotspot provisionnés."""
    if not device.is_active:
        return []
    try:
        with RouterOSClient(device) as client:
            return client.hotspot_all_users()
    except RouterOSError as exc:
        logger.warning("fetch_all_users device=%s : %s", device, exc)
        return []
