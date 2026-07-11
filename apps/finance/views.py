import datetime
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.tenants.access import user_sees_all_tenants

from .forms import MaintenanceTicketStatusForm
from .models import CashJournalEntry, CaisseDailyReport, MaintenanceTicket, RevendeurDailyReport


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


# ── Dashboard financier ───────────────────────────────────────────────────────

@login_required
def finance_dashboard(request: HttpRequest) -> HttpResponse:
    """Dashboard financier : revenus 30 jours, abonnés expirant, résumé caisse."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    user = request.user
    today = timezone.localdate()
    tid = None if user_sees_all_tenants(user) else getattr(user, "tenant_id", None)

    # ── revenus 30 derniers jours (CashJournalEntry income) ──
    start_30 = today - datetime.timedelta(days=29)
    entries_qs = CashJournalEntry.objects.filter(
        entry_type=CashJournalEntry.EntryType.INCOME,
        entry_date__gte=start_30,
    )
    if tid:
        entries_qs = entries_qs.filter(tenant_id=tid)

    daily: dict[str, int] = {}
    for e in entries_qs.values("entry_date", "amount_xof"):
        k = str(e["entry_date"])
        daily[k] = daily.get(k, 0) + int(e["amount_xof"] or 0)
    chart_labels = [(start_30 + datetime.timedelta(days=i)).isoformat() for i in range(30)]
    chart_data = [daily.get(d, 0) for d in chart_labels]

    revenue_30 = sum(chart_data)
    revenue_today = daily.get(str(today), 0)

    # ── abonnés expirant dans 7 jours ──
    from apps.wifi_zone.models import WiFiSimpleSubscriber
    now = timezone.now()
    expiring_qs = WiFiSimpleSubscriber.objects.filter(
        expires_at__gte=now,
        expires_at__lte=now + datetime.timedelta(days=7),
        status=WiFiSimpleSubscriber.Status.ACTIF,
    ).select_related("site", "plan")
    if tid:
        expiring_qs = expiring_qs.filter(site__tenant_id=tid)

    # ── stats abonnés ──
    sub_qs = WiFiSimpleSubscriber.objects.all()
    if tid:
        sub_qs = sub_qs.filter(site__tenant_id=tid)
    actifs = sub_qs.filter(status=WiFiSimpleSubscriber.Status.ACTIF).count()
    suspendus = sub_qs.filter(status=WiFiSimpleSubscriber.Status.SUSPENDU).count()
    expires = sub_qs.filter(status=WiFiSimpleSubscriber.Status.EXPIRE).count()

    # ── top clients (revenus mois en cours) ──
    month_start = today.replace(day=1)
    top_entries = (
        CashJournalEntry.objects.filter(
            entry_type=CashJournalEntry.EntryType.INCOME,
            entry_date__gte=month_start,
        )
    )
    if tid:
        top_entries = top_entries.filter(tenant_id=tid)
    monthly_total = top_entries.aggregate(t=Sum("amount_xof"))["t"] or Decimal("0")

    context = {
        "chart_labels": json.dumps(chart_labels),
        "chart_data": json.dumps(chart_data),
        "revenue_30": revenue_30,
        "revenue_today": revenue_today,
        "monthly_total": monthly_total,
        "expiring_soon": expiring_qs[:20],
        "expiring_count": expiring_qs.count(),
        "actifs": actifs,
        "suspendus": suspendus,
        "expires": expires,
    }
    return render(request, "finance/dashboard.html", context)
