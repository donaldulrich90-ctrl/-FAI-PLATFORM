"""Gestion des utilisateurs — CRUD complet accessible depuis le dashboard."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models import Site

User = get_user_model()


def _ensure_admin(user):
    if not (getattr(user, "is_admin_role", False) or user.is_superuser):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied


@login_required
def user_list(request: HttpRequest) -> HttpResponse:
    """Liste de tous les utilisateurs avec filtrage par rôle."""
    _ensure_admin(request.user)

    role_filter = request.GET.get("role", "")
    search = request.GET.get("q", "").strip()

    qs = User.objects.all().select_related("site", "tenant").order_by("-date_joined")

    if role_filter:
        qs = qs.filter(role=role_filter)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))

    stats = {
        "total": User.objects.count(),
        "admins": User.objects.filter(role=User.Role.ADMIN).count(),
        "techs": User.objects.filter(role=User.Role.TECHNICIAN).count(),
        "revendeurs": User.objects.filter(role=User.Role.REVENDEUR).count(),
    }

    context = {
        "users": page,
        "stats": stats,
        "role_filter": role_filter,
        "search": search,
        "role_choices": User.Role.choices,
    }
    return render(request, "accounts/user_management.html", context)


@login_required
def user_create(request: HttpRequest) -> HttpResponse:
    """Créer un nouvel utilisateur."""
    _ensure_admin(request.user)

    sites = Site.objects.all().order_by("name")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        role = request.POST.get("role", User.Role.TECHNICIAN)
        site_pk = request.POST.get("site", "")
        is_active = request.POST.get("is_active") == "on"
        ticket_prefix = request.POST.get("ticket_prefix", "").strip().upper()
        type_revendeur = request.POST.get("type_revendeur", "autonome")

        try:
            commission = Decimal(request.POST.get("commission", "10") or "10")
        except (InvalidOperation, ValueError):
            commission = Decimal("10")

        if not username or not password:
            messages.error(request, "Le nom d'utilisateur et le mot de passe sont obligatoires.")
            return redirect("accounts:user_create")

        if User.objects.filter(username=username).exists():
            messages.error(request, f"Le nom d'utilisateur « {username} » existe déjà.")
            return redirect("accounts:user_create")

        user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            role=role,
            is_active=is_active,
            default_commission_percent=commission,
            ticket_prefix=ticket_prefix,
            type_revendeur=type_revendeur if role == User.Role.REVENDEUR else "",
        )

        if site_pk:
            try:
                user.site = Site.objects.get(pk=site_pk)
            except Site.DoesNotExist:
                pass

        # Hériter le tenant de l'admin créateur
        if hasattr(request.user, "tenant_id") and request.user.tenant_id:
            user.tenant_id = request.user.tenant_id

        if role == User.Role.ADMIN:
            user.is_staff = True

        # ── Permissions d'accès granulaires ──
        user.access_monitoring = request.POST.get("access_monitoring") == "on"
        user.access_abonnes = request.POST.get("access_abonnes") == "on"
        user.access_wifi = request.POST.get("access_wifi") == "on"
        user.access_revendeur = request.POST.get("access_revendeur") == "on"
        user.access_finance = request.POST.get("access_finance") == "on"
        user.access_admin = request.POST.get("access_admin") == "on"

        user.set_password(password)
        user.save()

        messages.success(request, f"Utilisateur « {username} » créé avec succès (rôle : {user.get_role_display()}).")
        return redirect("accounts:user_list")

    context = {
        "mode": "create",
        "sites": sites,
        "role_choices": User.Role.choices,
        "type_revendeur_choices": User.TypeRevendeur.choices,
    }
    return render(request, "accounts/user_form.html", context)


@login_required
def user_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Modifier un utilisateur existant."""
    _ensure_admin(request.user)

    target = get_object_or_404(User, pk=pk)
    sites = Site.objects.all().order_by("name")

    if request.method == "POST":
        target.first_name = request.POST.get("first_name", "").strip()
        target.last_name = request.POST.get("last_name", "").strip()
        target.email = request.POST.get("email", "").strip()
        target.phone = request.POST.get("phone", "").strip()
        target.role = request.POST.get("role", target.role)
        target.is_active = request.POST.get("is_active") == "on"
        target.ticket_prefix = request.POST.get("ticket_prefix", "").strip().upper()
        target.type_revendeur = request.POST.get("type_revendeur", "autonome") if target.role == User.Role.REVENDEUR else ""

        try:
            target.default_commission_percent = Decimal(request.POST.get("commission", "10") or "10")
        except (InvalidOperation, ValueError):
            pass

        site_pk = request.POST.get("site", "")
        if site_pk:
            try:
                target.site = Site.objects.get(pk=site_pk)
            except Site.DoesNotExist:
                pass
        else:
            target.site = None

        if target.role == User.Role.ADMIN:
            target.is_staff = True

        # ── Permissions d'accès granulaires ──
        target.access_monitoring = request.POST.get("access_monitoring") == "on"
        target.access_abonnes = request.POST.get("access_abonnes") == "on"
        target.access_wifi = request.POST.get("access_wifi") == "on"
        target.access_revendeur = request.POST.get("access_revendeur") == "on"
        target.access_finance = request.POST.get("access_finance") == "on"
        target.access_admin = request.POST.get("access_admin") == "on"

        new_password = request.POST.get("password", "").strip()
        if new_password:
            target.set_password(new_password)

        target.save()
        messages.success(request, f"Utilisateur « {target.username} » mis à jour.")
        return redirect("accounts:user_list")

    context = {
        "mode": "edit",
        "target": target,
        "sites": sites,
        "role_choices": User.Role.choices,
        "type_revendeur_choices": User.TypeRevendeur.choices,
    }
    return render(request, "accounts/user_form.html", context)


@login_required
def user_toggle_active(request: HttpRequest, pk: int) -> HttpResponse:
    """Activer / désactiver un utilisateur."""
    _ensure_admin(request.user)
    if request.method != "POST":
        return redirect("accounts:user_list")

    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "Vous ne pouvez pas vous désactiver vous-même.")
        return redirect("accounts:user_list")

    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    etat = "activé" if target.is_active else "désactivé"
    messages.success(request, f"Utilisateur « {target.username} » {etat}.")
    return redirect("accounts:user_list")


@login_required
def user_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Supprimer un utilisateur."""
    _ensure_admin(request.user)
    if request.method != "POST":
        return redirect("accounts:user_list")

    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
        return redirect("accounts:user_list")

    username = target.username
    target.delete()
    messages.success(request, f"Utilisateur « {username} » supprimé définitivement.")
    return redirect("accounts:user_list")
