from __future__ import annotations

import csv
import io
import json
from datetime import date as date_type
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import NetworkDevice, Site
from apps.tenants.access import user_sees_all_tenants

from .models import PlanAbonnement, Ticket, TicketPlainte, WiFiSimpleSubscriber, WifiTicketBatch
from .router_control import (
    activate_subscriber,
    disconnect_hotspot_session,
    fetch_mikrotik_hotspot_active_details,
    fetch_mikrotik_hotspot_hosts,
    suspend_subscriber,
    update_subscriber_speed,
)
from .services.ticket_pdf import generate_tickets_pdf

User = get_user_model()


# ── Helpers de permission ─────────────────────────────────────────────────────

def _ensure_revendeur_or_admin(user) -> None:
    if not (getattr(user, "is_revendeur", False) or getattr(user, "is_admin_role", False)):
        raise PermissionDenied


def _ensure_admin_or_tech(user) -> None:
    if not (getattr(user, "is_admin_role", False) or getattr(user, "is_technician", False)):
        raise PermissionDenied


def _tenant_sites(user):
    if user_sees_all_tenants(user):
        return Site.objects.all()
    tid = getattr(user, "tenant_id", None)
    return Site.objects.filter(tenant_id=tid) if tid else Site.objects.none()


def _tenant_mikrotiks(user):
    if user_sees_all_tenants(user):
        return NetworkDevice.objects.filter(vendor=NetworkDevice.Vendor.MIKROTIK, is_active=True)
    tid = getattr(user, "tenant_id", None)
    return (
        NetworkDevice.objects.filter(
            vendor=NetworkDevice.Vendor.MIKROTIK, is_active=True, site__tenant_id=tid
        )
        if tid
        else NetworkDevice.objects.none()
    )


# ── 1. CLIENTS CONNECTÉS ─────────────────────────────────────────────────────

@login_required
def clients_list(request: HttpRequest) -> HttpResponse:
    """Tableau temps réel des clients connectés au hotspot."""
    _ensure_admin_or_tech(request.user)

    sites = list(_tenant_sites(request.user).order_by("name"))
    context = {
        "sites": sites,
        "selected_site_id": request.GET.get("site", ""),
    }
    return render(request, "wifi_zone/clients_list.html", context)


@login_required
def clients_api(request: HttpRequest) -> JsonResponse:
    """API JSON : sessions hotspot actives de tous les MikroTik du tenant."""
    _ensure_admin_or_tech(request.user)

    site_filter = request.GET.get("site", "")
    devices = _tenant_mikrotiks(request.user).select_related("site")
    if site_filter:
        devices = devices.filter(site__site_id=site_filter)

    sessions: list[dict] = []
    for device in devices:
        raw_sessions = fetch_mikrotik_hotspot_active_details(device)
        for s in raw_sessions:
            sessions.append({
                "session_id": s.get(".id", ""),
                "user": s.get("user", ""),
                "mac": s.get("mac-address", ""),
                "ip": s.get("address", ""),
                "uptime": s.get("uptime", "—"),
                "bytes_in": _fmt_bytes(s.get("bytes-in")),
                "bytes_out": _fmt_bytes(s.get("bytes-out")),
                "site_name": device.site.name,
                "site_id": device.site.site_id,
                "device_pk": device.pk,
                "device_name": device.name,
            })

    return JsonResponse({"sessions": sessions, "count": len(sessions)})


def _fmt_bytes(raw: str | None) -> str:
    if not raw:
        return "—"
    try:
        b = int(raw)
    except (ValueError, TypeError):
        return raw
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.2f} GB"


@login_required
@require_POST
def client_disconnect(request: HttpRequest) -> JsonResponse:
    """Déconnecte une session hotspot active."""
    _ensure_admin_or_tech(request.user)

    device_pk = request.POST.get("device_pk", "")
    session_id = request.POST.get("session_id", "")
    username = request.POST.get("username", "")

    if not device_pk or not session_id:
        return JsonResponse({"ok": False, "error": "Paramètres manquants."}, status=400)

    devices = _tenant_mikrotiks(request.user)
    device = get_object_or_404(devices, pk=device_pk)

    ok, err = disconnect_hotspot_session(
        device,
        session_id,
        username,
        performed_by=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    return JsonResponse({"ok": ok, "error": err})


@login_required
def client_detail(request: HttpRequest, username: str) -> HttpResponse:
    """Détail d'un client : historique tickets et logs audit."""
    _ensure_admin_or_tech(request.user)
    from apps.monitoring.models import RouterAuditLog

    tickets = (
        Ticket.objects.filter(code=username)
        .select_related("site", "sold_by", "batch")
        .order_by("-created_at")
    )
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        tickets = tickets.filter(site__tenant_id=tid) if tid else tickets.none()

    audit_logs = (
        RouterAuditLog.objects.filter(target=username)
        .select_related("device", "performed_by")
        .order_by("-created_at")[:30]
    )

    context = {
        "username": username,
        "tickets": tickets,
        "audit_logs": audit_logs,
    }
    return render(request, "wifi_zone/client_detail.html", context)


# ── 2. REVENDEUR DASHBOARD ────────────────────────────────────────────────────

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

    batches = WifiTicketBatch.objects.filter(created_by=user).select_related("site").order_by("-created_at")[:10]

    context = {
        "revendeur": user,
        "nb_ventes": agg["nb"] or 0,
        "brut_xof": brut,
        "commissions_xof": commissions,
        "net_a_reverser_xof": net_fai,
        "derniers_tickets": derniers,
        "taux_defaut": user.default_commission_percent if getattr(user, "is_revendeur", False) else Decimal("0"),
        "recent_batches": batches,
    }
    return render(request, "wifi_zone/revendeur_dashboard.html", context)


# ── 3. GÉNÉRATION DE TICKETS REVENDEUR ───────────────────────────────────────

@login_required
def revendeur_generate_batch(request: HttpRequest) -> HttpResponse:
    """Formulaire + traitement pour générer un lot de tickets MikroTik.

    - Admin : sélectionne un revendeur AUTONOME dans un dropdown.
    - Revendeur AUTONOME : génère pour lui-même.
    - Revendeur PARTENAIRE : accès refusé.
    """
    user = request.user
    is_admin = getattr(user, "is_admin_role", False)
    is_rev = getattr(user, "is_revendeur", False)

    if not (is_admin or is_rev):
        raise PermissionDenied

    from .services.wifi_access_code import WifiAccessCodeService
    from .router_control import default_hotspot_profile_for_duration

    sites = _tenant_sites(user).order_by("name")

    # Revendeurs disponibles (pour le dropdown admin)
    autonomes = []
    if is_admin:
        qs = User.objects.filter(
            role=User.Role.REVENDEUR,
        )
        if not user_sees_all_tenants(user):
            tid = getattr(user, "tenant_id", None)
            qs = qs.filter(tenant_id=tid) if tid else qs.none()
        autonomes = list(qs.select_related("site").order_by("username"))

    DURATION_CHOICES = [
        ("3h", "3 Heures"),
        ("1d", "24 Heures"),
        ("1w", "7 Jours"),
        ("30j", "30 Jours"),
    ]
    MAX_QUANTITY = 100
    QUANTITY_CHOICES = [5, 10, 20, 50, 100]

    if request.method == "POST":
        # Déterminer le seller
        if is_admin:
            rev_pk = request.POST.get("revendeur_pk", "").strip()
            if not rev_pk:
                messages.error(request, "Veuillez sélectionner un revendeur.")
                return redirect("wifi_zone:revendeur_generate_batch")
            rev_qs = User.objects.filter(
                role=User.Role.REVENDEUR,
            )
            if not user_sees_all_tenants(user):
                tid = getattr(user, "tenant_id", None)
                rev_qs = rev_qs.filter(tenant_id=tid) if tid else rev_qs.none()
            seller = get_object_or_404(rev_qs, pk=rev_pk)
        else:
            seller = user

        site_pk = request.POST.get("site_pk", "")
        duration = request.POST.get("duration", "3h")
        try:
            quantity = int(request.POST.get("quantity", "10"))
        except ValueError:
            quantity = 10
        if quantity > MAX_QUANTITY:
            messages.error(request, f"La quantité maximale est {MAX_QUANTITY} tickets par lot.")
            return redirect("wifi_zone:revendeur_generate_batch")
        try:
            unit_price = Decimal(request.POST.get("unit_price", "0"))
        except Exception:
            unit_price = Decimal("0")
        profile = request.POST.get("profile", "").strip()

        site = get_object_or_404(sites, pk=site_pk)

        if not profile:
            try:
                profile = default_hotspot_profile_for_duration(duration)
            except ValueError:
                profile = "default"

        svc = WifiAccessCodeService()
        try:
            tickets, errors = svc.create_revendeur_batch(
                site=site,
                duration=duration,
                unit_price_xof=unit_price,
                quantity=quantity,
                seller=seller,
                profile=profile,
                push_to_mikrotik=True,
            )
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("wifi_zone:revendeur_generate_batch")

        if errors:
            for err in errors:
                messages.warning(request, err)

        if tickets:
            request.session[f"batch_print_{tickets[0].batch_id}"] = [t.pk for t in tickets]
            return redirect("wifi_zone:revendeur_print", batch_pk=tickets[0].batch_id)

        messages.error(request, "Aucun ticket généré.")
        return redirect("wifi_zone:revendeur_generate_batch")

    context = {
        "sites": sites,
        "duration_choices": DURATION_CHOICES,
        "quantity_choices": QUANTITY_CHOICES,
        "max_quantity": MAX_QUANTITY,
        "autonomes": autonomes,
        "is_admin": is_admin,
    }
    return render(request, "wifi_zone/revendeur_generate_batch.html", context)


@login_required
def revendeur_print(request: HttpRequest, batch_pk: int) -> HttpResponse:
    """Vue d'impression optimisée pour un lot de tickets revendeur."""
    _ensure_revendeur_or_admin(request.user)
    user = request.user

    batch_qs = WifiTicketBatch.objects.select_related("site")
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        batch_qs = batch_qs.filter(site__tenant_id=tid) if tid else batch_qs.none()
    if getattr(user, "is_revendeur", False) and not getattr(user, "is_admin_role", False):
        batch_qs = batch_qs.filter(created_by=user)

    batch = get_object_or_404(batch_qs, pk=batch_pk)
    ticket_qs = Ticket.objects.filter(batch=batch).select_related("site").order_by("code")
    ticket_list = list(ticket_qs)
    total = len(ticket_list)

    PER_PAGE = 50
    pages = []
    for i in range(0, max(1, total), PER_PAGE):
        chunk = ticket_list[i:i + PER_PAGE]
        unit_price = int(chunk[0].price_xof) if chunk else 0
        pages.append({
            "numbered_tickets": [(i + j + 1, t) for j, t in enumerate(chunk)],
            "count": len(chunk),
            "unit_price": unit_price,
            "total_xof": sum(int(t.price_xof) for t in chunk),
            "first_num": i + 1,
            "last_num": i + len(chunk),
        })

    DURATION_LABELS = {"3h": "3 Heures", "1d": "24 Heures", "1w": "7 Jours", "30j": "30 Jours"}
    context = {
        "batch": batch,
        "tickets": ticket_list,
        "pages": pages,
        "total": total,
        "duration_label": DURATION_LABELS.get(batch.duration, batch.duration),
        "ssid": batch.site.name,
    }
    return render(request, "wifi_zone/revendeur_print.html", context)


# ── 4. ADMIN REVENDEURS ───────────────────────────────────────────────────────

@login_required
def admin_revendeur_list(request: HttpRequest) -> HttpResponse:
    """Liste des revendeurs avec statistiques (admin uniquement)."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    tid = None if user_sees_all_tenants(request.user) else getattr(request.user, "tenant_id", None)

    qs = User.objects.filter(role=User.Role.REVENDEUR)
    if tid:
        qs = qs.filter(tenant_id=tid)

    revendeurs = []
    for rev in qs.select_related("site", "tenant"):
        tickets_qs = Ticket.objects.filter(sold_by=rev)
        agg = tickets_qs.aggregate(
            nb=Count("id"),
            brut=Sum("price_xof"),
            commission=Sum("commission_amount_xof"),
        )
        revendeurs.append({
            "user": rev,
            "nb_tickets": agg["nb"] or 0,
            "ca_xof": agg["brut"] or Decimal("0"),
            "commission_xof": agg["commission"] or Decimal("0"),
        })

    return render(request, "wifi_zone/admin_revendeur_list.html", {"revendeurs": revendeurs})


# ── 5. IMPRESSION PDF ─────────────────────────────────────────────────────────

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


# ── 6. ABONNÉS DOMICILE ───────────────────────────────────────────────────────

def _tenant_subscribers(user):
    qs = WiFiSimpleSubscriber.objects.select_related("site", "plan", "cpe_device")
    if user_sees_all_tenants(user):
        return qs
    tid = getattr(user, "tenant_id", None)
    return qs.filter(site__tenant_id=tid) if tid else qs.none()


@login_required
def abonne_list(request: HttpRequest) -> HttpResponse:
    _ensure_admin_or_tech(request.user)
    qs = _tenant_subscribers(request.user).order_by("-created_at")

    status_filter = request.GET.get("status", "")
    site_filter = request.GET.get("site", "")
    q = request.GET.get("q", "").strip()

    if status_filter:
        qs = qs.filter(status=status_filter)
    if site_filter:
        qs = qs.filter(site__site_id=site_filter)
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(mac_address__icontains=q))

    sites = list(_tenant_sites(request.user).order_by("name"))
    now = timezone.now()
    expiring_soon = qs.filter(expires_at__lte=now + timezone.timedelta(days=7), expires_at__gte=now).count()

    context = {
        "subscribers": qs,
        "sites": sites,
        "status_choices": WiFiSimpleSubscriber.Status.choices,
        "status_filter": status_filter,
        "site_filter": site_filter,
        "q": q,
        "expiring_soon": expiring_soon,
        "now": now,
    }
    return render(request, "wifi_zone/abonne_list.html", context)


@login_required
def abonne_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _ensure_admin_or_tech(request.user)
    qs = _tenant_subscribers(request.user)
    subscriber = get_object_or_404(qs, pk=pk)
    tickets_plainte = TicketPlainte.objects.filter(subscriber=subscriber).order_by("-created_at")[:10]
    context = {
        "subscriber": subscriber,
        "tickets_plainte": tickets_plainte,
    }
    return render(request, "wifi_zone/abonne_detail.html", context)


@login_required
@require_POST
def abonne_action(request: HttpRequest, pk: int) -> JsonResponse:
    """ACTIVER / SUSPENDRE / RENOUVELER / MODIFIER_VITESSE."""
    _ensure_admin_or_tech(request.user)
    qs = _tenant_subscribers(request.user)
    subscriber = get_object_or_404(qs, pk=pk)
    action = request.POST.get("action", "")
    ip = request.META.get("REMOTE_ADDR")

    if action == "activer":
        ok, err = activate_subscriber(subscriber, performed_by=request.user, ip_address=ip)
        if ok:
            _maybe_send_whatsapp_bienvenue(subscriber)
    elif action == "suspendre":
        ok, err = suspend_subscriber(subscriber, performed_by=request.user, ip_address=ip)
        if ok:
            _maybe_send_whatsapp_suspension(subscriber)
    elif action == "reactiver":
        ok, err = activate_subscriber(subscriber, performed_by=request.user, ip_address=ip)
    elif action == "modifier_vitesse":
        try:
            speed = int(request.POST.get("speed_mbps", "0"))
        except ValueError:
            return JsonResponse({"ok": False, "error": "Vitesse invalide."}, status=400)
        if speed <= 0:
            return JsonResponse({"ok": False, "error": "Vitesse doit être > 0 Mbps."}, status=400)
        ok, err = update_subscriber_speed(subscriber, speed, performed_by=request.user, ip_address=ip)
    else:
        return JsonResponse({"ok": False, "error": "Action inconnue."}, status=400)

    return JsonResponse({"ok": ok, "error": err, "status": subscriber.status})


def _maybe_send_whatsapp_bienvenue(subscriber):
    try:
        from apps.notifications.whatsapp import WhatsAppService, msg_bienvenue
        svc = WhatsAppService()
        plan_name = subscriber.plan.name if subscriber.plan else "—"
        speed = f"{subscriber.plan.speed_mbps} Mbps" if subscriber.plan else "—"
        expires = subscriber.expires_at.strftime("%d/%m/%Y")
        svc.send(
            subscriber.effective_whatsapp_phone,
            msg_bienvenue(subscriber.full_name, plan_name, speed, expires),
            tenant_id=getattr(subscriber.site, "tenant_id", None),
        )
    except Exception:
        pass


def _maybe_send_whatsapp_suspension(subscriber):
    try:
        from apps.notifications.whatsapp import WhatsAppService, msg_suspension
        svc = WhatsAppService()
        prix = str(subscriber.plan.price_xof) if subscriber.plan else "—"
        expires = subscriber.expires_at.strftime("%d/%m/%Y")
        svc.send(
            subscriber.effective_whatsapp_phone,
            msg_suspension(subscriber.full_name, expires, prix),
            tenant_id=getattr(subscriber.site, "tenant_id", None),
        )
    except Exception:
        pass


# ── 7. TICKETS PLAINTE ────────────────────────────────────────────────────────

def _tenant_tickets(user):
    qs = TicketPlainte.objects.select_related("subscriber", "assigned_to")
    if user_sees_all_tenants(user):
        return qs
    tid = getattr(user, "tenant_id", None)
    return qs.filter(tenant_id=tid) if tid else qs.none()


@login_required
def ticket_plainte_list(request: HttpRequest) -> HttpResponse:
    _ensure_admin_or_tech(request.user)
    qs = _tenant_tickets(request.user).order_by("-created_at")

    status_filter = request.GET.get("status", "")
    priority_filter = request.GET.get("priority", "")
    view_mode = request.GET.get("view", "list")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if priority_filter:
        qs = qs.filter(priority=priority_filter)

    kanban_columns = []
    if view_mode == "kanban":
        for s, label in TicketPlainte.Status.choices:
            kanban_columns.append({
                "status": s,
                "label": label,
                "tickets": list(qs.filter(status=s)[:50]),
            })

    context = {
        "tickets": qs[:100],
        "kanban_columns": kanban_columns,
        "view_mode": view_mode,
        "status_choices": TicketPlainte.Status.choices,
        "priority_choices": TicketPlainte.Priority.choices,
        "status_filter": status_filter,
        "priority_filter": priority_filter,
        "counts": {
            "nouveau": qs.filter(status=TicketPlainte.Status.NOUVEAU).count(),
            "en_cours": qs.filter(status=TicketPlainte.Status.EN_COURS).count(),
            "resolu": qs.filter(status=TicketPlainte.Status.RESOLU).count(),
        },
    }
    return render(request, "wifi_zone/ticket_plainte_list.html", context)


@login_required
@require_POST
def ticket_plainte_update(request: HttpRequest, pk: int) -> JsonResponse:
    _ensure_admin_or_tech(request.user)
    qs = _tenant_tickets(request.user)
    ticket = get_object_or_404(qs, pk=pk)

    new_status = request.POST.get("status", "")
    notes = request.POST.get("resolution_notes", "").strip()
    assigned_to_id = request.POST.get("assigned_to_id", "")

    if new_status and new_status in dict(TicketPlainte.Status.choices):
        ticket.status = new_status
    if notes:
        ticket.resolution_notes = notes
    if assigned_to_id:
        ticket.assigned_to_id = int(assigned_to_id)
    ticket.save()

    if new_status == TicketPlainte.Status.RESOLU and ticket.subscriber:
        _reply_whatsapp_ticket(ticket)

    return JsonResponse({"ok": True, "status": ticket.status, "reference": ticket.reference})


@login_required
@require_POST
def ticket_plainte_reply(request: HttpRequest, pk: int) -> JsonResponse:
    _ensure_admin_or_tech(request.user)
    qs = _tenant_tickets(request.user)
    ticket = get_object_or_404(qs, pk=pk)
    msg_text = request.POST.get("message", "").strip()
    if not msg_text:
        return JsonResponse({"ok": False, "error": "Message vide."}, status=400)

    phone = ""
    if ticket.subscriber:
        phone = ticket.subscriber.effective_whatsapp_phone
    elif ticket.phone_from:
        phone = ticket.phone_from

    if not phone:
        return JsonResponse({"ok": False, "error": "Numéro destinataire inconnu."}, status=400)

    from apps.notifications.whatsapp import WhatsAppService
    svc = WhatsAppService()
    ok, err = svc.send(phone, msg_text, tenant_id=getattr(ticket, "tenant_id", None))
    return JsonResponse({"ok": ok, "error": err})


def _reply_whatsapp_ticket(ticket):
    try:
        from apps.notifications.whatsapp import WhatsAppService, msg_ticket_reponse
        if ticket.subscriber:
            phone = ticket.subscriber.effective_whatsapp_phone
        elif ticket.phone_from:
            phone = ticket.phone_from
        else:
            return
        svc = WhatsAppService()
        svc.send(phone, msg_ticket_reponse(ticket.reference), tenant_id=ticket.tenant_id)
    except Exception:
        pass


# ── 8. DASHBOARD WIFI ZONES ──────────────────────────────────────────────────

_DURATION_LABELS = {"3h": "3 Heures", "1d": "24 Heures", "1w": "7 Jours", "30j": "30 Jours"}


def _get_revendeurs_qs(user):
    qs = User.objects.filter(role=User.Role.REVENDEUR)
    if not user_sees_all_tenants(user):
        tid = getattr(user, "tenant_id", None)
        return qs.filter(tenant_id=tid) if tid else qs.none()
    return qs


@login_required
def zones_dashboard(request: HttpRequest) -> HttpResponse:
    """Tableau de bord : vue globale de tous les revendeurs Wi-Fi Zone."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    today = timezone.now().date()
    month_start = today.replace(day=1)

    revendeurs_qs = _get_revendeurs_qs(request.user).select_related(
        "site", "tenant", "mikrotik__site"
    )
    revendeurs_list = list(revendeurs_qs)

    # Bulk-fetch hotspot data once per MikroTik device (statut + sessions)
    mikrotik_ids = {rev.mikrotik_id for rev in revendeurs_list if rev.mikrotik_id}
    device_macs: dict[int, set[str]] = {}
    device_sessions: dict[int, list[dict]] = {}
    if mikrotik_ids:
        from apps.core.models import NetworkDevice as ND
        for dev in ND.objects.filter(pk__in=mikrotik_ids, is_active=True):
            device_macs[dev.pk] = fetch_mikrotik_hotspot_hosts(dev)
            device_sessions[dev.pk] = fetch_mikrotik_hotspot_active_details(dev)

    rows = []
    for rev in revendeurs_list:
        # Statut en ligne : MAC antenne présente dans /ip hotspot host
        en_ligne = False
        if rev.mac_antenne and rev.mikrotik_id:
            mac_norm = rev.mac_antenne.upper().replace("-", ":")
            en_ligne = mac_norm in device_macs.get(rev.mikrotik_id, set())

        # Clients connectés : sessions dont le username commence par le préfixe
        clients_connectes = 0
        if rev.ticket_prefix and rev.mikrotik_id:
            prefix = rev.ticket_prefix.upper()
            clients_connectes = sum(
                1 for s in device_sessions.get(rev.mikrotik_id, [])
                if str(s.get("user", "")).upper().startswith(prefix)
            )

        tickets_base = Ticket.objects.filter(sold_by=rev)
        today_qs = tickets_base.filter(created_at__date=today)
        today_agg = today_qs.aggregate(
            count=Count("id"),
            brut=Sum("price_xof", filter=Q(status=Ticket.Status.USED)),
        )
        month_agg = tickets_base.filter(created_at__date__gte=month_start).aggregate(
            brut=Sum("price_xof", filter=Q(status=Ticket.Status.USED))
        )

        rows.append({
            "user": rev,
            "en_ligne": en_ligne,
            "clients_connectes": clients_connectes,
            "tickets_aujourd_hui": today_agg["count"] or 0,
            "revenus_jour": today_agg["brut"] or Decimal("0"),
            "revenus_mois": month_agg["brut"] or Decimal("0"),
            "prochaine_echeance": rev.date_expiration,
            "solde": rev.balance_xof,
            "type_revendeur": rev.type_revendeur,
            "is_partenaire": getattr(rev, "is_revendeur_partenaire", False),
        })

    context = {
        "revendeurs": rows,
        "today": today,
        "nb_en_ligne": sum(1 for r in rows if r["en_ligne"]),
        "total_clients": sum(r["clients_connectes"] for r in rows),
        "total_jour": sum(r["revenus_jour"] for r in rows),
        "total_mois": sum(r["revenus_mois"] for r in rows),
    }
    return render(request, "wifi_zone/zones_dashboard.html", context)


@login_required
def zone_daily_report(request: HttpRequest, revendeur_id: int) -> HttpResponse:
    """Rapport journalier détaillé pour un revendeur Wi-Fi Zone."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    rev = get_object_or_404(_get_revendeurs_qs(request.user).select_related("site"), pk=revendeur_id)

    date_str = request.GET.get("date", "")
    try:
        selected_date = date_type.fromisoformat(date_str)
    except (ValueError, TypeError):
        selected_date = timezone.now().date()

    tickets = (
        Ticket.objects.filter(sold_by=rev, created_at__date=selected_date)
        .select_related("site")
        .order_by("created_at")
    )
    count_generated = tickets.count()

    agg = tickets.filter(status=Ticket.Status.USED).aggregate(
        count=Count("id"),
        brut=Sum("price_xof"),
        commission=Sum("commission_amount_xof"),
        net=Sum("net_to_isp_xof"),
    )

    from django.db.models.functions import ExtractHour
    hourly = (
        tickets.annotate(heure=ExtractHour("created_at"))
        .values("heure")
        .annotate(count=Count("id"), total=Sum("price_xof"))
        .order_by("heure")
    )
    hours_count = [0] * 24
    hours_revenue = [0] * 24
    for entry in hourly:
        h = entry["heure"]
        hours_count[h] = entry["count"]
        hours_revenue[h] = int(entry["total"] or 0)

    context = {
        "revendeur": rev,
        "selected_date": selected_date,
        "tickets": tickets,
        "count_generated": count_generated,
        "count": agg["count"] or 0,
        "brut_xof": agg["brut"] or Decimal("0"),
        "commission_xof": agg["commission"] or Decimal("0"),
        "net_xof": agg["net"] or Decimal("0"),
        "hours_labels": json.dumps(list(range(24))),
        "hours_count": json.dumps(hours_count),
        "hours_revenue": json.dumps(hours_revenue),
        "duration_labels": _DURATION_LABELS,
    }
    return render(request, "wifi_zone/zone_daily_report.html", context)


@login_required
def zone_monthly_report(request: HttpRequest, revendeur_id: int) -> HttpResponse:
    """Rapport mensuel avec graphiques et comparaison mois précédent."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    rev = get_object_or_404(_get_revendeurs_qs(request.user).select_related("site"), pk=revendeur_id)

    import calendar
    today = timezone.now().date()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if not 1 <= month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    month_start = date_type(year, month, 1)
    month_end = date_type(year, month, calendar.monthrange(year, month)[1])
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    prev_start = date_type(prev_year, prev_month, 1)
    prev_end = date_type(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])

    tickets_base = Ticket.objects.filter(sold_by=rev)

    from datetime import timedelta
    from django.db.models.functions import TruncDate
    daily_qs = (
        tickets_base.filter(created_at__date__range=(month_start, month_end))
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"), total=Sum("price_xof"))
        .order_by("day")
    )
    daily_map = {e["day"]: e for e in daily_qs}
    days_labels, days_revenue, days_count = [], [], []
    cur = month_start
    while cur <= month_end:
        days_labels.append(cur.strftime("%d"))
        e = daily_map.get(cur)
        days_revenue.append(int(e["total"] or 0) if e else 0)
        days_count.append(e["count"] if e else 0)
        cur += timedelta(days=1)

    month_tickets = tickets_base.filter(created_at__date__range=(month_start, month_end))
    count_generated = month_tickets.count()
    month_agg = month_tickets.filter(status=Ticket.Status.USED).aggregate(
        count=Count("id"),
        brut=Sum("price_xof"),
        commission=Sum("commission_amount_xof"),
        net=Sum("net_to_isp_xof"),
    )
    prev_agg = tickets_base.filter(created_at__date__range=(prev_start, prev_end)).aggregate(
        count=Count("id"), brut=Sum("price_xof")
    )

    top_durations = (
        tickets_base.filter(created_at__date__range=(month_start, month_end))
        .values("duration")
        .annotate(count=Count("id"), total=Sum("price_xof"))
        .order_by("-count")
    )
    top_dur = [
        {
            "label": _DURATION_LABELS.get(d["duration"], d["duration"]),
            "count": d["count"],
            "total": d["total"] or Decimal("0"),
        }
        for d in top_durations
    ]

    months = [(i, date_type(year, i, 1).strftime("%B")) for i in range(1, 13)]

    context = {
        "revendeur": rev,
        "year": year,
        "month": month,
        "month_name": month_start.strftime("%B %Y"),
        "days_labels": json.dumps(days_labels),
        "days_revenue": json.dumps(days_revenue),
        "days_count": json.dumps(days_count),
        "count_generated": count_generated,
        "count": month_agg["count"] or 0,
        "brut_xof": month_agg["brut"] or Decimal("0"),
        "commission_xof": month_agg["commission"] or Decimal("0"),
        "net_xof": month_agg["net"] or Decimal("0"),
        "prev_count": prev_agg["count"] or 0,
        "prev_brut_xof": prev_agg["brut"] or Decimal("0"),
        "top_durations": top_dur,
        "months": months,
        "years": range(today.year - 2, today.year + 1),
    }
    return render(request, "wifi_zone/zone_monthly_report.html", context)


@login_required
def zone_daily_report_csv(request: HttpRequest, revendeur_id: int) -> HttpResponse:
    """Export CSV du rapport journalier d'un revendeur."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    rev = get_object_or_404(_get_revendeurs_qs(request.user), pk=revendeur_id)

    date_str = request.GET.get("date", "")
    try:
        selected_date = date_type.fromisoformat(date_str)
    except (ValueError, TypeError):
        selected_date = timezone.now().date()

    tickets = (
        Ticket.objects.filter(sold_by=rev, created_at__date=selected_date)
        .select_related("site")
        .order_by("created_at")
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Heure", "Code", "Durée", "Site", "Prix (XOF)",
        "Commission (XOF)", "Net FAI (XOF)", "Statut", "Heure validation",
    ])
    for t in tickets:
        writer.writerow([
            t.created_at.strftime("%H:%M"),
            t.code,
            _DURATION_LABELS.get(t.duration, t.duration),
            t.site.name if t.site else "",
            int(t.price_xof),
            int(t.commission_amount_xof),
            int(t.net_to_isp_xof),
            t.get_status_display(),
            t.used_at.strftime("%H:%M") if t.used_at else "",
        ])

    content = "﻿" + output.getvalue()
    fname = f"rapport_{rev.username}_{selected_date}.csv"
    response = HttpResponse(content, content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


# ── 9. RAPPORT DÉTAILLÉ REVENDEUR (période : jour / semaine / mois) ──────────

def _parse_period_range(request: HttpRequest) -> tuple[str, "date_type", "date_type", int, int]:
    """Retourne (period, date_start, date_end, year, month) selon les GET params."""
    from datetime import timedelta
    import calendar as _cal

    today = timezone.now().date()
    period = request.GET.get("period", "day")
    year = today.year
    month = today.month

    if period == "month":
        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
            if not 1 <= month <= 12:
                raise ValueError
        except (ValueError, TypeError):
            year, month = today.year, today.month
        date_start = date_type(year, month, 1)
        date_end = date_type(year, month, _cal.monthrange(year, month)[1])
    elif period == "week":
        try:
            date_start = date_type.fromisoformat(request.GET.get("date", ""))
        except (ValueError, TypeError):
            date_start = today
        date_start = date_start - timedelta(days=date_start.weekday())
        date_end = date_start + timedelta(days=6)
    else:  # day
        period = "day"
        try:
            date_start = date_type.fromisoformat(request.GET.get("date", ""))
        except (ValueError, TypeError):
            date_start = today
        date_end = date_start

    return period, date_start, date_end, year, month


@login_required
def zone_detail_report(request: HttpRequest, revendeur_id: int) -> HttpResponse:
    """Rapport détaillé d'un revendeur avec sélecteur de période (jour/semaine/mois)."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    rev = get_object_or_404(
        _get_revendeurs_qs(request.user).select_related("site"), pk=revendeur_id
    )
    today = timezone.now().date()
    period, date_start, date_end, year, month = _parse_period_range(request)

    tickets = (
        Ticket.objects.filter(sold_by=rev, created_at__date__range=(date_start, date_end))
        .select_related("site")
        .order_by("created_at")
    )
    count_generated = tickets.count()
    agg = tickets.filter(status=Ticket.Status.USED).aggregate(
        count=Count("id"),
        brut=Sum("price_xof"),
        commission=Sum("commission_amount_xof"),
        net=Sum("net_to_isp_xof"),
    )

    # Données graphique
    if period == "day":
        from django.db.models.functions import ExtractHour
        hourly = (
            tickets.annotate(heure=ExtractHour("created_at"))
            .values("heure")
            .annotate(count=Count("id"), total=Sum("price_xof"))
            .order_by("heure")
        )
        ch_count = [0] * 24
        ch_revenue = [0] * 24
        for e in hourly:
            ch_count[e["heure"]] = e["count"]
            ch_revenue[e["heure"]] = int(e["total"] or 0)
        chart_labels = json.dumps([f"{h}h" for h in range(24)])
        chart_count = json.dumps(ch_count)
        chart_revenue = json.dumps(ch_revenue)
    else:
        from datetime import timedelta
        from django.db.models.functions import TruncDate
        daily_qs = (
            tickets.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"), total=Sum("price_xof"))
            .order_by("day")
        )
        daily_map = {e["day"]: e for e in daily_qs}
        ch_labels_list, ch_count_list, ch_revenue_list = [], [], []
        cur = date_start
        while cur <= date_end:
            e = daily_map.get(cur)
            ch_labels_list.append(cur.strftime("%d/%m"))
            ch_count_list.append(e["count"] if e else 0)
            ch_revenue_list.append(int(e["total"] or 0) if e else 0)
            cur += timedelta(days=1)
        chart_labels = json.dumps(ch_labels_list)
        chart_count = json.dumps(ch_count_list)
        chart_revenue = json.dumps(ch_revenue_list)

    context = {
        "revendeur": rev,
        "period": period,
        "date_start": date_start,
        "date_end": date_end,
        "selected_date": date_start,
        "year": year,
        "month": month,
        "today": today,
        "tickets": tickets,
        "count_generated": count_generated,
        "count": agg["count"] or 0,
        "brut_xof": agg["brut"] or Decimal("0"),
        "commission_xof": agg["commission"] or Decimal("0"),
        "net_xof": agg["net"] or Decimal("0"),
        "chart_labels": chart_labels,
        "chart_count": chart_count,
        "chart_revenue": chart_revenue,
        "duration_labels": _DURATION_LABELS,
        "months": [(i, date_type(today.year, i, 1).strftime("%B")) for i in range(1, 13)],
        "years": range(today.year - 2, today.year + 1),
    }
    return render(request, "wifi_zone/zone_detail_report.html", context)


@login_required
def zone_detail_report_csv(request: HttpRequest, revendeur_id: int) -> HttpResponse:
    """Export CSV du rapport détaillé (période variable)."""
    if not getattr(request.user, "is_admin_role", False):
        raise PermissionDenied

    rev = get_object_or_404(_get_revendeurs_qs(request.user), pk=revendeur_id)
    period, date_start, date_end, _year, _month = _parse_period_range(request)

    tickets = (
        Ticket.objects.filter(sold_by=rev, created_at__date__range=(date_start, date_end))
        .select_related("site")
        .order_by("created_at")
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Date", "Heure", "Code", "Durée", "Site", "Prix (XOF)",
        "Commission (XOF)", "Net FAI (XOF)", "Statut", "Heure validation",
    ])
    for t in tickets:
        writer.writerow([
            t.created_at.strftime("%d/%m/%Y"),
            t.created_at.strftime("%H:%M"),
            t.code,
            _DURATION_LABELS.get(t.duration, t.duration),
            t.site.name if t.site else "",
            int(t.price_xof),
            int(t.commission_amount_xof),
            int(t.net_to_isp_xof),
            t.get_status_display(),
            t.used_at.strftime("%d/%m/%Y %H:%M") if t.used_at else "",
        ])

    period_label = {"day": date_start.isoformat(), "week": f"semaine_{date_start}", "month": f"{_year}-{_month:02d}"}
    fname = f"rapport_{rev.username}_{period_label.get(period, date_start)}.csv"
    content = "﻿" + output.getvalue()
    response = HttpResponse(content, content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


# ── 10. TICKETS IMPRIMÉS (listing + sync status) ─────────────────────────────

@login_required
def tickets_imprime_list(request: HttpRequest) -> HttpResponse:
    """Liste paginée des tickets Wi-Fi Zone avec statut sync hotspot et uptime en temps réel."""
    _ensure_admin_or_tech(request.user)

    sites = list(_tenant_sites(request.user).order_by("name"))

    qs = Ticket.objects.select_related("site", "batch", "sold_by").order_by("-created_at")
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        qs = qs.filter(site__tenant_id=tid) if tid else qs.none()

    site_filter = request.GET.get("site", "")
    batch_filter = request.GET.get("batch", "")
    status_filter = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()

    if site_filter:
        qs = qs.filter(site__site_id=site_filter)
    if batch_filter:
        try:
            qs = qs.filter(batch_id=int(batch_filter))
        except ValueError:
            pass
    if status_filter:
        qs = qs.filter(status=status_filter)
    if q:
        qs = qs.filter(Q(code__icontains=q))

    tickets = list(qs[:200])

    # Fetch uptime per site (one API call per unique MikroTik)
    from .router_control import resolve_wifi_zone_mikrotik_for_site
    site_ids_needed = {t.site_id for t in tickets}
    site_user_map: dict[int, dict[str, dict]] = {}
    for site_obj in sites:
        if site_obj.pk in site_ids_needed:
            device = resolve_wifi_zone_mikrotik_for_site(site_obj)
            if device:
                try:
                    from apps.core.services.routeros_client import RouterOSClient, RouterOSError
                    with RouterOSClient(device) as client:
                        rows = client.hotspot_all_users()
                        active_rows = client.hotspot_active_details()
                    active_map = {r.get("user", ""): r for r in active_rows if r.get("user")}
                    site_user_map[site_obj.pk] = {
                        r.get("name", ""): {
                            "bytes_in": r.get("bytes-in", "0"),
                            "bytes_out": r.get("bytes-out", "0"),
                            "disabled": r.get("disabled", "false"),
                            "uptime": active_map.get(r.get("name", ""), {}).get("uptime", ""),
                        }
                        for r in rows if r.get("name")
                    }
                except Exception:
                    site_user_map[site_obj.pk] = {}
            else:
                site_user_map[site_obj.pk] = {}

    enriched = []
    for t in tickets:
        user_info = site_user_map.get(t.site_id, {}).get(t.code, None)
        enriched.append({
            "ticket": t,
            "on_router": user_info is not None,
            "uptime": user_info.get("uptime", "") if user_info else "",
            "sync_icon": (
                "ok" if (t.hotspot_synced_at and not t.hotspot_sync_error)
                else ("error" if t.hotspot_sync_error
                      else "pending")
            ),
        })

    batches_qs = WifiTicketBatch.objects.select_related("site", "created_by").annotate(
        ticket_count=Count("tickets")
    ).order_by("-created_at")
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        batches_qs = batches_qs.filter(site__tenant_id=tid) if tid else batches_qs.none()
    batches = list(batches_qs[:50])

    context = {
        "enriched": enriched,
        "sites": sites,
        "batches": batches,
        "site_filter": site_filter,
        "batch_filter": batch_filter,
        "status_filter": status_filter,
        "q": q,
        "status_choices": Ticket.Status.choices,
        "total": len(enriched),
    }
    return render(request, "wifi_zone/tickets_imprime_list.html", context)


# ── 11. SUPPRESSION TICKET ────────────────────────────────────────────────────

@login_required
@require_POST
def ticket_delete(request: HttpRequest, pk: int) -> JsonResponse:
    """Supprime un ticket : retire du MikroTik d'abord, puis de la DB."""
    _ensure_admin_or_tech(request.user)

    qs = Ticket.objects.select_related("site")
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        qs = qs.filter(site__tenant_id=tid) if tid else qs.none()

    ticket = get_object_or_404(qs, pk=pk)

    from .router_control import remove_wifi_zone_hotspot_for_ticket
    ok, err = remove_wifi_zone_hotspot_for_ticket(
        ticket,
        performed_by=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    if not ok:
        return JsonResponse({"ok": False, "error": f"Erreur MikroTik : {err}"})

    ticket.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def ticket_batch_delete(request: HttpRequest, batch_pk: int) -> JsonResponse:
    """Supprime tous les tickets d'un lot : retire du MikroTik puis de la DB."""
    _ensure_admin_or_tech(request.user)

    batch_qs = WifiTicketBatch.objects.select_related("site")
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        batch_qs = batch_qs.filter(site__tenant_id=tid) if tid else batch_qs.none()

    batch = get_object_or_404(batch_qs, pk=batch_pk)
    tickets = list(Ticket.objects.filter(batch=batch).select_related("site"))

    from .router_control import resolve_wifi_zone_mikrotik_for_site
    from apps.core.services.routeros_client import RouterOSClient, RouterOSError
    from apps.monitoring.audit import log_router_action
    from django.conf import settings as _settings

    failed_codes: list[str] = []
    deleted = 0
    ip_address = request.META.get("REMOTE_ADDR")
    dry_run = bool(getattr(_settings, "ROUTER_CONTROL_DRY_RUN", False))

    device = resolve_wifi_zone_mikrotik_for_site(batch.site) if tickets else None

    if device is None:
        # No MikroTik for this site — delete directly from DB
        for ticket in tickets:
            ticket.delete()
            deleted += 1
    else:
        try:
            with RouterOSClient(device) as client:
                for ticket in tickets:
                    code = ticket.code.strip()
                    ok = client.hotspot_user_remove(code)
                    log_router_action(
                        device,
                        "hotspot_remove",
                        target=code,
                        command_sent=f"hotspot user remove [find name={code}]",
                        success=ok,
                        error_message="" if ok else "Échec suppression utilisateur RouterOS.",
                        dry_run=dry_run,
                        performed_by=request.user,
                        ip_address=ip_address,
                    )
                    if ok:
                        ticket.delete()
                        deleted += 1
                    else:
                        failed_codes.append(code)
        except RouterOSError as exc:
            return JsonResponse({
                "ok": False,
                "deleted": deleted,
                "error": f"MikroTik inaccessible : {exc}",
                "failed_codes": [],
            })

    if failed_codes:
        return JsonResponse({
            "ok": False,
            "deleted": deleted,
            "error": f"MikroTik inaccessible pour {len(failed_codes)} ticket(s). DB non modifiée pour ces tickets.",
            "failed_codes": failed_codes[:10],
        })

    if not Ticket.objects.filter(batch=batch).exists():
        batch.delete()
    return JsonResponse({"ok": True, "deleted": deleted})


# ── 12. RE-SYNCHRONISATION TICKET ─────────────────────────────────────────────

@login_required
@require_POST
def ticket_resync(request: HttpRequest, pk: int) -> JsonResponse:
    """Re-provisionne un ticket sur MikroTik et remet les compteurs à zéro."""
    _ensure_admin_or_tech(request.user)

    qs = Ticket.objects.select_related("site")
    if not user_sees_all_tenants(request.user):
        tid = getattr(request.user, "tenant_id", None)
        qs = qs.filter(site__tenant_id=tid) if tid else qs.none()

    ticket = get_object_or_404(qs, pk=pk)

    from .router_control import provision_wifi_zone_hotspot_for_ticket, resolve_wifi_zone_mikrotik_for_site
    from apps.core.services.routeros_client import RouterOSClient, RouterOSError

    ok, err = provision_wifi_zone_hotspot_for_ticket(
        ticket,
        performed_by=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    now = timezone.now()
    if ok:
        Ticket.objects.filter(pk=ticket.pk).update(
            hotspot_synced_at=now,
            hotspot_sync_error="",
        )
        return JsonResponse({"ok": True, "synced_at": now.strftime("%d/%m/%Y %H:%M")})
    else:
        Ticket.objects.filter(pk=ticket.pk).update(
            hotspot_synced_at=None,
            hotspot_sync_error=err[:512],
        )
        return JsonResponse({"ok": False, "error": err})


# ── 10. WEBHOOK WHATSAPP ───────────────────────────────────────────────────────

@csrf_exempt
def whatsapp_webhook(request: HttpRequest) -> HttpResponse:
    """Reçoit des messages WhatsApp entrants et crée des TicketPlainte."""
    from django.conf import settings as _settings

    verify_token = getattr(_settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "faest-webhook-secret")

    if request.method == "GET":
        token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")
        if token == verify_token:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponse("Forbidden", status=403)

    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponse(status=400)

    phone = data.get("phone", "").strip()
    message_text = data.get("message", data.get("text", "")).strip()

    if not message_text:
        return HttpResponse(status=200)

    subscriber = None
    if phone:
        subscriber = (
            WiFiSimpleSubscriber.objects.filter(
                Q(phone=phone) | Q(whatsapp_phone=phone)
            )
            .first()
        )

    tenant_id = None
    if subscriber:
        tenant_id = getattr(subscriber.site, "tenant_id", None)

    if tenant_id is None:
        from apps.tenants.models import Tenant
        tenant = Tenant.objects.first()
        tenant_id = tenant.pk if tenant else None

    if tenant_id is None:
        return HttpResponse(status=200)

    priority = TicketPlainte.classify_priority(message_text)
    ticket = TicketPlainte.objects.create(
        tenant_id=tenant_id,
        subscriber=subscriber,
        phone_from=phone,
        source=TicketPlainte.Source.WHATSAPP,
        message_original=message_text[:2000],
        priority=priority,
        status=TicketPlainte.Status.NOUVEAU,
    )

    from apps.notifications.whatsapp import WhatsAppService, msg_ticket_reponse
    svc = WhatsAppService()
    svc.send(phone, msg_ticket_reponse(ticket.reference), tenant_id=tenant_id)

    return HttpResponse(status=200)
