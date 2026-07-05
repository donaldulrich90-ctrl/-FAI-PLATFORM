from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.tenants.access import user_sees_all_tenants

from .models import Ticket, WifiTicketBatch
from .services.ticket_pdf import generate_tickets_pdf


def _ensure_revendeur_or_admin(user) -> None:
    if not (getattr(user, "is_revendeur", False) or getattr(user, "is_admin_role", False)):
        raise PermissionDenied


@login_required
def revendeur_dashboard(request: HttpRequest) -> HttpResponse:
    """Synthèse ventes / commissions pour le revendeur connecté."""
    _ensure_revendeur_or_admin(request.user)

    user = request.user
    qs = Ticket.objects.filter(sold_by=user)
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        qs = qs.filter(site__tenant_id=tid) if tid else qs.none()
    agg = qs.aggregate(
        nb=Count("id"),
        brut=Sum("price_xof"),
        commissions=Sum("commission_amount_xof"),
        net_fai=Sum("net_to_isp_xof"),
    )

    def _d(v) -> Decimal:
        return v if isinstance(v, Decimal) else Decimal(v or 0)

    brut = _d(agg["brut"])
    commissions = _d(agg["commissions"])
    net_fai = _d(agg["net_fai"])
    derniers = qs.select_related("site").order_by("-sold_at")[:25]

    context = {
        "revendeur": user,
        "nb_ventes": agg["nb"] or 0,
        "brut_xof": brut,
        "commissions_xof": commissions,
        "net_a_reverser_xof": net_fai,
        "derniers_tickets": derniers,
        "taux_defaut": user.default_commission_percent
        if getattr(user, "is_revendeur", False)
        else Decimal("0"),
    }
    return render(request, "wifi_zone/revendeur_dashboard.html", context)


# ── Impression PDF ────────────────────────────────────────────────────────────

@login_required
def print_batch_pdf(request: HttpRequest, batch_pk: int) -> HttpResponse:
    """Génère un PDF imprimable pour tous les tickets d'un lot."""
    _ensure_revendeur_or_admin(request.user)
    user = request.user

    batch_qs = WifiTicketBatch.objects.select_related("site")
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        batch_qs = batch_qs.filter(site__tenant_id=tid) if tid else batch_qs.none()

    batch = get_object_or_404(batch_qs, pk=batch_pk)
    tickets = Ticket.objects.filter(batch=batch).select_related("site").order_by("code")

    title = f"Tickets {batch.site.site_id} — {batch.get_duration_display()} — {batch.unit_price_xof} XOF"
    pdf_bytes = generate_tickets_pdf(tickets, title=title)

    filename = f"tickets_{batch.site.site_id}_{batch.duration}_{batch.pk}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def print_tickets_pdf(request: HttpRequest) -> HttpResponse:
    """Génère un PDF pour les tickets sélectionnés (IDs passés en GET ?ids=1,2,3)."""
    _ensure_revendeur_or_admin(request.user)
    user = request.user

    raw_ids = request.GET.get("ids", "")
    try:
        pks = [int(i) for i in raw_ids.split(",") if i.strip().isdigit()]
    except ValueError:
        pks = []

    if not pks:
        return HttpResponse("Aucun ticket sélectionné.", status=400)

    tickets_qs = Ticket.objects.filter(pk__in=pks).select_related("site")
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        tickets_qs = tickets_qs.filter(site__tenant_id=tid) if tid else tickets_qs.none()

    tickets = list(tickets_qs.order_by("code"))
    if not tickets:
        return HttpResponse("Aucun ticket accessible.", status=403)

    pdf_bytes = generate_tickets_pdf(tickets, title="Tickets Wi-Fi Zone")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="tickets.pdf"'
    return response
