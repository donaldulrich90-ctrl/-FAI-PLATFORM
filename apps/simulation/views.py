import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.tenants.access import user_sees_all_tenants

from .models import Simulation, SimulationElement, SimulationLink


def _tenant_simulations(user):
    if user_sees_all_tenants(user):
        return Simulation.objects.all()
    tid = getattr(user, "tenant_id", None)
    return Simulation.objects.filter(tenant_id=tid) if tid else Simulation.objects.none()


def _require_technician(request):
    """Returns redirect response if user lacks technician role, else None."""
    if not getattr(request.user, "is_technician", False):
        return redirect("wifi_zone:revendeur_dashboard")
    return None


@login_required
def simulation_list(request: HttpRequest):
    guard = _require_technician(request)
    if guard:
        return guard
    simulations = _tenant_simulations(request.user).select_related("created_by")
    return render(request, "simulation/list.html", {"simulations": simulations})


@login_required
def simulation_create(request: HttpRequest):
    guard = _require_technician(request)
    if guard:
        return guard
    if request.method == "POST":
        name = request.POST.get("name", "").strip() or "Nouvelle simulation"
        tid = getattr(request.user, "tenant_id", None)
        if tid is None and not user_sees_all_tenants(request.user):
            return redirect("simulation:simulation_list")
        if user_sees_all_tenants(request.user) and not tid:
            from apps.tenants.models import Tenant
            tenant = Tenant.objects.first()
        else:
            from apps.tenants.models import Tenant
            tenant = get_object_or_404(Tenant, pk=tid)
        sim = Simulation.objects.create(
            tenant=tenant,
            name=name,
            created_by=request.user,
        )
        return redirect("simulation:simulation_detail", pk=sim.pk)
    return render(request, "simulation/create.html")


@login_required
def simulation_detail(request: HttpRequest, pk: int):
    guard = _require_technician(request)
    if guard:
        return guard
    sim = get_object_or_404(_tenant_simulations(request.user), pk=pk)
    from django.conf import settings as django_settings
    mapbox_token = getattr(django_settings, "MAPBOX_ACCESS_TOKEN", "")
    return render(request, "simulation/detail.html", {
        "simulation": sim,
        "mapbox_token": mapbox_token,
    })


@login_required
@require_GET
def simulation_api_load(request: HttpRequest, pk: int):
    guard = _require_technician(request)
    if guard:
        return JsonResponse({"error": "Forbidden"}, status=403)
    sim = get_object_or_404(_tenant_simulations(request.user), pk=pk)
    elements = list(sim.elements.values("id", "element_type", "label", "lat", "lng", "config"))
    links = list(sim.links.values("id", "element_a_id", "element_b_id", "link_type", "config", "result"))
    return JsonResponse({
        "id": sim.pk,
        "name": sim.name,
        "center_lat": sim.center_lat,
        "center_lng": sim.center_lng,
        "zoom": sim.zoom,
        "elements": elements,
        "links": links,
    })


@login_required
@require_POST
def simulation_api_save(request: HttpRequest, pk: int):
    guard = _require_technician(request)
    if guard:
        return JsonResponse({"error": "Forbidden"}, status=403)
    sim = get_object_or_404(_tenant_simulations(request.user), pk=pk)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    # Update simulation metadata
    if "name" in data:
        sim.name = str(data["name"])[:128]
    if "center_lat" in data:
        sim.center_lat = float(data["center_lat"])
    if "center_lng" in data:
        sim.center_lng = float(data["center_lng"])
    if "zoom" in data:
        sim.zoom = float(data["zoom"])
    sim.save()

    # Full replace: delete existing, recreate
    sim.elements.all().delete()

    id_map = {}  # client temp id → db id
    for elem_data in data.get("elements", []):
        elem = SimulationElement.objects.create(
            simulation=sim,
            element_type=elem_data.get("element_type", "antenna"),
            label=str(elem_data.get("label", ""))[:64],
            lat=float(elem_data.get("lat", 0)),
            lng=float(elem_data.get("lng", 0)),
            config=elem_data.get("config", {}),
        )
        client_id = elem_data.get("id")
        if client_id is not None:
            id_map[str(client_id)] = elem.pk

    for link_data in data.get("links", []):
        a_id = id_map.get(str(link_data.get("element_a_id")))
        b_id = id_map.get(str(link_data.get("element_b_id")))
        if a_id and b_id:
            SimulationLink.objects.create(
                simulation=sim,
                element_a_id=a_id,
                element_b_id=b_id,
                link_type=link_data.get("link_type", "ptmp"),
                config=link_data.get("config", {}),
                result=link_data.get("result", {}),
            )

    return JsonResponse({"ok": True, "id": sim.pk})
