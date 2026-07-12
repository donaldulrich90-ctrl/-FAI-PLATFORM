import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import NetworkDevice, PtPLink, Site
from apps.tenants.access import user_sees_all_tenants

from .audit import log_router_action
from .models import DeviceConfigChange
from .services.ubiquiti_ssh import (
    ALLOWED_FREQUENCIES_5GHZ,
    read_current_frequency,
    set_frequency,
    test_ssh_connection,
)
from .services.uptime_kuma import fetch_status_page_public_summary
from .services.zabbix_api import fetch_ubiquiti_snmp_snapshot


def _ptp_line_coordinates(link: PtPLink) -> list[list[float]] | None:
    """[[lng, lat], [lng, lat]] pour GeoJSON LineString."""

    def corner(site, elat, elng):
        lat = elat if elat is not None else site.latitude
        lng = elng if elng is not None else site.longitude
        if lat is None or lng is None:
            return None
        return [float(lng), float(lat)]

    a = corner(link.site_a, link.endpoint_a_lat, link.endpoint_a_lng)
    b = corner(link.site_b, link.endpoint_b_lat, link.endpoint_b_lng)
    if not a or not b:
        return None
    return [a, b]


@login_required
def dashboard(request: HttpRequest):
    if getattr(request.user, "is_revendeur", False) and not getattr(
        request.user, "is_admin_role", False
    ):
        return redirect("wifi_zone:revendeur_dashboard")

    user = request.user
    if user_sees_all_tenants(user):
        sites = Site.objects.all()
    else:
        tid = getattr(user, "tenant_id", None)
        sites = Site.objects.filter(tenant_id=tid) if tid else Site.objects.none()
    sites_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": s.name,
                    "site_id": s.site_id,
                    "ok": s.is_operational,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(s.longitude), float(s.latitude)],
                },
            }
            for s in sites
            if s.latitude is not None and s.longitude is not None
        ],
    }

    ptp_features: list[dict] = []
    ptp_qs = PtPLink.objects.filter(is_active=True).select_related("site_a", "site_b")
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        if tid:
            ptp_qs = ptp_qs.filter(site_a__tenant_id=tid, site_b__tenant_id=tid)
        else:
            ptp_qs = ptp_qs.none()
    for link in ptp_qs:
        coords = _ptp_line_coordinates(link)
        if not coords:
            continue
        ptp_features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": link.name,
                    "health": link.cached_health,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            }
        )
    ptp_geojson = {"type": "FeatureCollection", "features": ptp_features}

    kuma_summary = fetch_status_page_public_summary()
    from django.conf import settings as _s
    from apps.wifi_zone.models import WiFiSimpleSubscriber
    # Abonnés avec GPS pour la carte
    sub_qs = WiFiSimpleSubscriber.objects.filter(
        latitude__isnull=False, longitude__isnull=False
    ).select_related("site")
    if not user_sees_all_tenants(user):
        tid_filter = getattr(user, "tenant_id", None)
        sub_qs = sub_qs.filter(site__tenant_id=tid_filter) if tid_filter else sub_qs.none()
    subscribers_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": s.full_name,
                    "status": s.status,
                    "plan": s.plan.name if s.plan else "",
                    "expires_at": s.expires_at.strftime("%d/%m/%Y"),
                    "pk": s.pk,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(s.longitude), float(s.latitude)],
                },
            }
            for s in sub_qs
        ],
    }
    context = {
        "sites": sites,
        "sites_geojson": json.dumps(sites_geojson, ensure_ascii=False),
        "ptp_geojson": json.dumps(ptp_geojson, ensure_ascii=False),
        "subscribers_geojson": json.dumps(subscribers_geojson, ensure_ascii=False),
        "kuma_json": json.dumps(kuma_summary, ensure_ascii=False, indent=2),
        "mapbox_token": getattr(_s, "MAPBOX_ACCESS_TOKEN", ""),
    }
    return render(request, "monitoring/dashboard.html", context)


@login_required
@require_GET
def api_uptime_kuma(request: HttpRequest):
    return JsonResponse(fetch_status_page_public_summary())


@login_required
@require_GET
def api_zabbix_host(request: HttpRequest, host_name: str):
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        if not tid:
            return JsonResponse({"error": "Accès refusé."}, status=403)
        allowed = PtPLink.objects.filter(
            site_a__tenant_id=tid,
            site_b__tenant_id=tid,
        ).filter(
            Q(zabbix_host_a=host_name) | Q(zabbix_host_b=host_name)
        ).exists()
        if not allowed:
            return JsonResponse({"error": "Hôte introuvable ou accès refusé."}, status=403)
    return JsonResponse(fetch_ubiquiti_snmp_snapshot(host_name))


# ── Gestion fréquence antennes Ubiquiti ──────────────────────────────────────

def _admin_required(request: HttpRequest) -> bool:
    return getattr(request.user, "is_admin_role", False) or request.user.is_superuser


@login_required
def antenna_list(request: HttpRequest):
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect("monitoring:dashboard")

    user = request.user
    if user_sees_all_tenants(user):
        devices = NetworkDevice.objects.filter(vendor="ubiquiti", is_active=True).select_related("site", "parent_mikrotik")
    else:
        tid = getattr(user, "tenant_id", None)
        devices = (
            NetworkDevice.objects.filter(vendor="ubiquiti", is_active=True, site__tenant_id=tid)
            .select_related("site", "parent_mikrotik")
            if tid
            else NetworkDevice.objects.none()
        )

    recent_changes = (
        DeviceConfigChange.objects.filter(device__in=devices)
        .select_related("device", "changed_by")[:20]
    )

    return render(request, "monitoring/antenna_list.html", {
        "devices": devices,
        "recent_changes": recent_changes,
    })


@login_required
@require_GET
def antenna_snmp_api(request: HttpRequest, pk: int) -> JsonResponse:
    """API JSON : métriques temps réel d'une antenne Ubiquiti via SSH MikroTik parent."""
    if not _admin_required(request):
        return JsonResponse({"error": "Accès refusé."}, status=403)

    user = request.user
    device = get_object_or_404(NetworkDevice, pk=pk, vendor="ubiquiti", is_active=True)

    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        if not tid or device.site.tenant_id != tid:
            return JsonResponse({"error": "Accès refusé."}, status=403)

    # Chemin 1 : SSH direct airOS via port-forwarding MikroTik
    if device.ssh_forward_port:
        from .services.ubiquiti_ssh_monitor import UbiquitiSSHService

        m = UbiquitiSSHService(device=device).fetch_metrics()
        clients_data = [
            {
                "mac": c.mac,
                "signal_dbm": c.signal_dbm,
                "tx_rate_mbps": c.tx_rate_mbps,
                "rx_rate_mbps": c.rx_rate_mbps,
            }
            for c in m.clients
        ]
        return JsonResponse({
            "online": m.online,
            "freq_mhz": m.freq_mhz,
            "tx_power_dbm": m.tx_power_dbm,
            "tx_rate_mbps": m.tx_rate_mbps,
            "client_count": m.client_count,
            "avg_signal_dbm": m.avg_signal_dbm,
            "throughput_in_mbps": m.rx_mb,
            "throughput_out_mbps": m.tx_mb,
            "uptime": "—",
            "error": m.error,
            "device_name": device.name,
            "neighbor_seen": None,
            "clients": clients_data,
            "source": "airos_ssh",
        })

    # Chemin 2 : métriques via RouterOS SSH sur le MikroTik parent (fallback)
    parent = device.parent_mikrotik
    if parent is None or not parent.is_active:
        return JsonResponse({
            "online": False,
            "freq_mhz": None,
            "tx_power_dbm": None,
            "client_count": None,
            "avg_signal_dbm": None,
            "throughput_in_mbps": None,
            "throughput_out_mbps": None,
            "uptime": "—",
            "error": "Pas de MikroTik parent configuré pour cette antenne.",
            "device_name": device.name,
            "clients": [],
            "source": "none",
        })

    from .services.mikrotik_ssh_monitor import MikrotikSshMonitorService

    svc = MikrotikSshMonitorService(mikrotik_device=parent)
    m = svc.fetch_metrics(
        ubiquiti_ip=device.management_host,
        mikrotik_interface=device.mikrotik_interface,
    )

    return JsonResponse({
        "online": m.online,
        "freq_mhz": None,
        "tx_power_dbm": None,
        "tx_rate_mbps": None,
        "client_count": m.client_count,
        "avg_signal_dbm": m.avg_signal_dbm,
        "throughput_in_mbps": None,
        "throughput_out_mbps": None,
        "uptime": "—",
        "error": m.error,
        "device_name": device.name,
        "neighbor_seen": m.neighbor_seen,
        "clients": [],
        "source": "mikrotik_ssh",
    })


@login_required
def antenna_freq_change(request: HttpRequest, pk: int):
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect("monitoring:dashboard")

    user = request.user
    device = get_object_or_404(NetworkDevice, pk=pk, vendor="ubiquiti", is_active=True)

    # Vérification tenant
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        if not tid or device.site.tenant_id != tid:
            messages.error(request, "Équipement introuvable ou accès refusé.")
            return redirect("monitoring:antenna_list")

    if request.method == "POST":
        freq_str = request.POST.get("freq_mhz", "").strip()
        confirmed = request.POST.get("confirmed") == "1"

        if not freq_str.isdigit():
            messages.error(request, "Fréquence invalide.")
            return redirect("monitoring:antenna_freq_change", pk=pk)

        freq_mhz = int(freq_str)

        if not confirmed:
            # Étape 1 : afficher la confirmation
            current = read_current_frequency(device)
            return render(request, "monitoring/antenna_freq_change.html", {
                "device": device,
                "freq_mhz": freq_mhz,
                "current_freq": current.get("freq_mhz"),
                "confirm_step": True,
                "frequencies": ALLOWED_FREQUENCIES_5GHZ,
            })

        # Étape 2 : exécuter le changement
        from django.conf import settings as django_settings
        dry_run = getattr(django_settings, "ROUTER_CONTROL_DRY_RUN", False)
        current = read_current_frequency(device)
        old_freq = current.get("freq_mhz")

        result = set_frequency(device, freq_mhz)

        DeviceConfigChange.objects.create(
            device=device,
            changed_by=user,
            change_type=DeviceConfigChange.ChangeType.FREQUENCY,
            old_value=str(old_freq) if old_freq else "",
            new_value=str(freq_mhz),
            success=result["ok"],
            message=result["message"],
            dry_run=dry_run,
        )
        log_router_action(
            device,
            "freq_change",
            target=str(freq_mhz),
            command_sent=f"cfg -s radio.1.freq={freq_mhz} && cfg -c && reboot",
            success=result["ok"],
            error_message="" if result["ok"] else result["message"],
            dry_run=dry_run,
            performed_by=user,
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        if result["ok"]:
            messages.success(request, result["message"])
        else:
            messages.error(request, result["message"])

        return redirect("monitoring:antenna_list")

    # GET : afficher le formulaire de sélection de fréquence
    current = read_current_frequency(device)
    return render(request, "monitoring/antenna_freq_change.html", {
        "device": device,
        "current_freq": current.get("freq_mhz"),
        "current_raw": current.get("raw", ""),
        "confirm_step": False,
        "frequencies": ALLOWED_FREQUENCIES_5GHZ,
    })


# ── Dashboard gestion intelligente des fréquences ────────────────────────────

@login_required
def frequency_dashboard(request: HttpRequest):
    """Vue principale de gestion des fréquences Ubiquiti."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect("monitoring:dashboard")

    from .models import FrequenceConfig, HistoriqueFrequence

    user = request.user
    if user_sees_all_tenants(user):
        devices = NetworkDevice.objects.filter(vendor="ubiquiti", is_active=True).select_related("site")
    else:
        tid = getattr(user, "tenant_id", None)
        devices = (
            NetworkDevice.objects.filter(vendor="ubiquiti", is_active=True, site__tenant_id=tid).select_related("site")
            if tid
            else NetworkDevice.objects.none()
        )

    # Enrichissement : config fréquence et dernier historique pour chaque antenne
    device_rows = []
    for dev in devices:
        cfg = FrequenceConfig.objects.filter(device=dev).first()
        last_change = HistoriqueFrequence.objects.filter(device=dev).first()
        device_rows.append({
            "device": dev,
            "config": cfg,
            "last_change": last_change,
        })

    recent_history = (
        HistoriqueFrequence.objects.select_related("device")
        .filter(device__in=devices)
        [:30]
    )

    return render(request, "monitoring/frequency_dashboard.html", {
        "device_rows": device_rows,
        "recent_history": recent_history,
        "frequencies": ALLOWED_FREQUENCIES_5GHZ,
        "dry_run": getattr(__import__("django.conf", fromlist=["settings"]).settings, "ROUTER_CONTROL_DRY_RUN", False),
    })


@login_required
@require_POST
def frequency_config_save(request: HttpRequest, pk: int) -> JsonResponse:
    """Crée ou met à jour la FrequenceConfig d'une antenne (AJAX)."""
    if not _admin_required(request):
        return JsonResponse({"ok": False, "error": "Accès refusé."}, status=403)

    from .models import FrequenceConfig

    device = get_object_or_404(NetworkDevice, pk=pk, vendor="ubiquiti", is_active=True)
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        if not tid or device.site.tenant_id != tid:
            return JsonResponse({"ok": False, "error": "Accès refusé."}, status=403)

    def _intval(name, default=None):
        v = request.POST.get(name, "").strip()
        try:
            return int(v) if v else default
        except ValueError:
            return default

    cfg, _ = FrequenceConfig.objects.get_or_create(device=device)
    cfg.freq_principale = _intval("freq_principale", cfg.freq_principale)
    cfg.freq_secours_1 = _intval("freq_secours_1")
    cfg.freq_secours_2 = _intval("freq_secours_2")
    cfg.freq_secours_3 = _intval("freq_secours_3")
    cfg.seuil_snr_min = _intval("seuil_snr_min", cfg.seuil_snr_min)
    cfg.seuil_signal_min = _intval("seuil_signal_min", cfg.seuil_signal_min)
    cfg.auto_switch = request.POST.get("auto_switch") == "1"
    cfg.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def frequency_manual_change(request: HttpRequest, pk: int) -> JsonResponse:
    """Déclenche un changement de fréquence manuel (AJAX)."""
    if not _admin_required(request):
        return JsonResponse({"ok": False, "error": "Accès refusé."}, status=403)

    from .models import FrequenceConfig
    from .frequency_decision import execute_frequency_change

    device = get_object_or_404(NetworkDevice, pk=pk, vendor="ubiquiti", is_active=True)
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        if not tid or device.site.tenant_id != tid:
            return JsonResponse({"ok": False, "error": "Accès refusé."}, status=403)

    freq_str = request.POST.get("freq_mhz", "").strip()
    if not freq_str.isdigit():
        return JsonResponse({"ok": False, "error": "Fréquence invalide."})

    freq_mhz = int(freq_str)
    cfg, _ = FrequenceConfig.objects.get_or_create(device=device, defaults={"freq_principale": freq_mhz})

    ok = execute_frequency_change(
        device=device,
        config=cfg,
        new_freq=freq_mhz,
        raison="manuel",
        declencheur="manuel",
    )
    return JsonResponse({"ok": ok})


@login_required
@require_POST
def frequency_toggle_auto(request: HttpRequest, pk: int) -> JsonResponse:
    """Active/désactive le basculement automatique pour une antenne (AJAX)."""
    if not _admin_required(request):
        return JsonResponse({"ok": False, "error": "Accès refusé."}, status=403)

    from .models import FrequenceConfig

    device = get_object_or_404(NetworkDevice, pk=pk, vendor="ubiquiti", is_active=True)
    cfg, _ = FrequenceConfig.objects.get_or_create(device=device)
    cfg.auto_switch = not cfg.auto_switch
    cfg.save(update_fields=["auto_switch"])
    return JsonResponse({"ok": True, "auto_switch": cfg.auto_switch})
