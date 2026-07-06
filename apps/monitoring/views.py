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
    context = {
        "sites": sites,
        "sites_geojson": json.dumps(sites_geojson, ensure_ascii=False),
        "ptp_geojson": json.dumps(ptp_geojson, ensure_ascii=False),
        "kuma_json": json.dumps(kuma_summary, ensure_ascii=False, indent=2),
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
        devices = NetworkDevice.objects.filter(vendor="ubiquiti", is_active=True).select_related("site")
    else:
        tid = getattr(user, "tenant_id", None)
        devices = (
            NetworkDevice.objects.filter(vendor="ubiquiti", is_active=True, site__tenant_id=tid)
            .select_related("site")
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
