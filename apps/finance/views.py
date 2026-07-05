import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.tenants.access import user_sees_all_tenants

from .forms import MaintenanceTicketStatusForm
from .models import CashJournalEntry, MaintenanceTicket, RevendeurDailyReport


def _ensure_technician_or_admin(user) -> None:
    if not getattr(user, "is_technician", False):
        raise PermissionDenied


@login_required
def intervention_list(request: HttpRequest) -> HttpResponse:
    """Liste des tickets de panne (terrain, mobile-first)."""
    _ensure_technician_or_admin(request.user)
    qs = MaintenanceTicket.objects.select_related(
        "site",
        "assigned_to",
        "faulty_link",
    ).order_by("-opened_at")
    user = request.user
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        qs = qs.filter(tenant_id=tid) if tid else qs.none()
    if getattr(user, "is_technician", False) and not getattr(user, "is_admin_role", False):
        qs = qs.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True))
    return render(
        request,
        "finance/intervention_list.html",
        {"tickets": qs},
    )


@login_required
def intervention_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Mise à jour du statut depuis le terrain."""
    _ensure_technician_or_admin(request.user)
    ticket_qs = MaintenanceTicket.objects.select_related("site", "faulty_link")
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        ticket_qs = ticket_qs.filter(tenant_id=tid) if tid else ticket_qs.none()
    ticket = get_object_or_404(ticket_qs, pk=pk)
    user = request.user
    if getattr(user, "is_technician", False) and not getattr(user, "is_admin_role", False):
        if ticket.assigned_to_id not in (None, user.id):
            raise PermissionDenied

    if request.method == "POST":
        form = MaintenanceTicketStatusForm(request.POST, instance=ticket)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.status in (
                MaintenanceTicket.Status.RESOLVED,
                MaintenanceTicket.Status.CLOSED,
            ):
                obj.closed_at = timezone.now()
            obj.save()
            messages.success(request, "Statut mis à jour.")
            return redirect("finance:intervention_list")
    else:
        form = MaintenanceTicketStatusForm(instance=ticket)

    return render(
        request,
        "finance/intervention_form.html",
        {"ticket": ticket, "form": form},
    )


# ── Rapports journaliers revendeurs ──────────────────────────────────────────

@login_required
def revendeur_report_list(request: HttpRequest) -> HttpResponse:
    """Liste des rapports journaliers — admin voit tout, revendeur voit les siens."""
    user = request.user
    qs = RevendeurDailyReport.objects.select_related("revendeur", "tenant").order_by(
        "-report_date", "revendeur__username"
    )
    if user_sees_all_tenants(user):
        pass  # tout visible
    elif getattr(user, "is_admin_role", False):
        tid = getattr(user, "tenant_id", None)
        qs = qs.filter(tenant_id=tid) if tid else qs.none()
    elif getattr(user, "is_revendeur", False):
        qs = qs.filter(revendeur=user)
    else:
        raise PermissionDenied

    return render(request, "finance/revendeur_report_list.html", {"reports": qs})


@login_required
def revendeur_report_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Détail d'un rapport journalier (liste complète des tickets)."""
    user = request.user
    qs = RevendeurDailyReport.objects.select_related("revendeur", "tenant")
    if not user_sees_all_tenants(user):
        if getattr(user, "is_revendeur", False):
            qs = qs.filter(revendeur=user)
        elif getattr(user, "is_admin_role", False):
            tid = getattr(user, "tenant_id", None)
            qs = qs.filter(tenant_id=tid) if tid else qs.none()
        else:
            raise PermissionDenied

    report = get_object_or_404(qs, pk=pk)
    return render(request, "finance/revendeur_report_detail.html", {"report": report})


# ── Exports ──────────────────────────────────────────────────────────────────

def _filter_by_date(qs, request):
    """Applique les filtres date_from / date_to depuis les GET params."""
    for param, lookup in [("date_from", "gte"), ("date_to", "lte")]:
        raw = request.GET.get(param)
        if raw:
            try:
                qs = qs.filter(**{f"report_date__{lookup}": datetime.date.fromisoformat(raw)})
            except ValueError:
                pass
    return qs


@login_required
def revendeur_reports_export_excel(request: HttpRequest) -> HttpResponse:
    """Export Excel de la liste des rapports journaliers revendeurs."""
    user = request.user
    qs = RevendeurDailyReport.objects.select_related("revendeur", "tenant").order_by(
        "-report_date", "revendeur__username"
    )
    if user_sees_all_tenants(user):
        pass
    elif getattr(user, "is_admin_role", False):
        tid = getattr(user, "tenant_id", None)
        qs = qs.filter(tenant_id=tid) if tid else qs.none()
    elif getattr(user, "is_revendeur", False):
        qs = qs.filter(revendeur=user)
    else:
        raise PermissionDenied

    qs = _filter_by_date(qs, request)

    from .exports import build_revendeur_reports_excel
    content  = build_revendeur_reports_excel(qs)
    today    = timezone.localdate().strftime("%Y%m%d")
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="rapports_revendeurs_{today}.xlsx"'
    return response


@login_required
def revendeur_report_export_excel(request: HttpRequest, pk: int) -> HttpResponse:
    """Export Excel détaillé d'un rapport journalier revendeur."""
    user = request.user
    qs = RevendeurDailyReport.objects.select_related("revendeur", "tenant")
    if not user_sees_all_tenants(user):
        if getattr(user, "is_revendeur", False):
            qs = qs.filter(revendeur=user)
        elif getattr(user, "is_admin_role", False):
            tid = getattr(user, "tenant_id", None)
            qs = qs.filter(tenant_id=tid) if tid else qs.none()
        else:
            raise PermissionDenied

    report   = get_object_or_404(qs, pk=pk)
    from .exports import build_revendeur_report_detail_excel
    content  = build_revendeur_report_detail_excel(report)
    fname    = f"rapport_{report.report_date}_{report.revendeur.username}.xlsx"
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


@login_required
def caisse_export_csv(request: HttpRequest) -> HttpResponse:
    """Export CSV du journal de caisse (admin / opérateur plateforme uniquement)."""
    user = request.user
    if not (user_sees_all_tenants(user) or getattr(user, "is_admin_role", False)):
        raise PermissionDenied

    qs = CashJournalEntry.objects.select_related("site", "created_by").order_by(
        "-entry_date", "-created_at"
    )
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        qs = qs.filter(tenant_id=tid) if tid else qs.none()

    for param, lookup in [("date_from", "gte"), ("date_to", "lte")]:
        raw = request.GET.get(param)
        if raw:
            try:
                qs = qs.filter(**{f"entry_date__{lookup}": datetime.date.fromisoformat(raw)})
            except ValueError:
                pass

    from .exports import build_caisse_journal_csv
    content  = build_caisse_journal_csv(qs)
    today    = timezone.localdate().strftime("%Y%m%d")
    response = HttpResponse(content, content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="journal_caisse_{today}.csv"'
    return response
