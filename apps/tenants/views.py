from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.tenants.access import user_can_manage_tenant_records
from apps.tenants.forms import TenantForm
from apps.tenants.models import Tenant


def platform_manager_required(view_func):
    """Connexion obligatoire + droit de gérer les organisations (superuser ou gestionnaire plateforme)."""

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not user_can_manage_tenant_records(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper


@platform_manager_required
def tenant_list(request: HttpRequest) -> HttpResponse:
    tenants = Tenant.objects.annotate(site_count=Count("sites")).order_by("name")
    return render(
        request,
        "tenants/portal_list.html",
        {"tenants": tenants},
    )


@platform_manager_required
def tenant_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = TenantForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "L’organisation a été créée.")
            return redirect("platform:tenant_list")
    else:
        form = TenantForm()
    return render(
        request,
        "tenants/portal_form.html",
        {"form": form, "title": "Nouvelle organisation", "is_create": True},
    )


@platform_manager_required
def tenant_edit(request: HttpRequest, pk: int) -> HttpResponse:
    tenant = get_object_or_404(Tenant, pk=pk)
    if request.method == "POST":
        form = TenantForm(request.POST, instance=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, "L’organisation a été mise à jour.")
            return redirect("platform:tenant_list")
    else:
        form = TenantForm(instance=tenant)
    return render(
        request,
        "tenants/portal_form.html",
        {
            "form": form,
            "title": f"Modifier — {tenant.name}",
            "is_create": False,
            "tenant": tenant,
        },
    )


@platform_manager_required
def tenant_delete(request: HttpRequest, pk: int) -> HttpResponse:
    tenant = get_object_or_404(Tenant, pk=pk)
    if request.method == "POST":
        name = tenant.name
        tenant.delete()
        messages.success(request, f"L’organisation « {name} » a été supprimée.")
        return redirect("platform:tenant_list")
    return render(
        request,
        "tenants/portal_confirm_delete.html",
        {"tenant": tenant},
    )
