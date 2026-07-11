from __future__ import annotations

import json
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
    """Formulaire + traitement pour générer un lot de tickets MikroTik."""
    _ensure_revendeur_or_admin(request.user)
    from .services.wifi_access_code import WifiAccessCodeService
    from .router_control import default_hotspot_profile_for_duration

    user = request.user
    sites = _tenant_sites(user).order_by("name")

    DURATION_CHOICES = [
        ("3h", "3 Heures"),
        ("1d", "24 Heures"),
        ("1w", "7 Jours"),
        ("30j", "30 Jours"),
    ]
    QUANTITY_CHOICES = [5, 10, 20, 50]

    if request.method == "POST":
        site_pk = request.POST.get("site_pk", "")
        duration = request.POST.get("duration", "3h")
        try:
            quantity = int(request.POST.get("quantity", "10"))
        except ValueError:
            quantity = 10
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
                seller=user,
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
    tickets = Ticket.objects.filter(batch=batch).select_related("site").order_by("code")

    DURATION_LABELS = {"3h": "3 Heures", "1d": "24 Heures", "1w": "7 Jours", "30j": "30 Jours"}
    context = {
        "batch": batch,
        "tickets": tickets,
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


# ── 8. WEBHOOK WHATSAPP ───────────────────────────────────────────────────────

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
