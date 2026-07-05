"""Filtre les ModelAdmin par organisation (sauf superuser)."""

from __future__ import annotations

from typing import Any

from django.db.models import Model, QuerySet
from django.http import HttpRequest

from apps.tenants.access import user_sees_all_tenants


class TenantScopedAdminMixin:
    """
    Réduit le queryset aux objets du tenant de l'utilisateur.
    Superuser ou gestionnaire plateforme : accès à tout ; sinon filtre par organisation.
    """

    tenant_lookup: str = "tenant"

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs = super().get_queryset(request)
        user = request.user
        if not user.is_authenticated:
            return qs.none()
        if user_sees_all_tenants(user):
            return qs
        tid = getattr(user, "tenant_id", None)
        if tid is None:
            return qs.none()
        return qs.filter(**{self.tenant_lookup: tid})

    def save_model(
        self,
        request: HttpRequest,
        obj: Model,
        form: Any,
        change: bool,
    ) -> None:
        if (
            not request.user.is_superuser
            and not getattr(request.user, "is_platform_operator", False)
            and getattr(request.user, "tenant_id", None)
            and hasattr(obj, "tenant_id")
        ):
            obj.tenant_id = request.user.tenant_id
        super().save_model(request, obj, form, change)


class TenantScopedSiteFKAdminMixin(TenantScopedAdminMixin):
    """Pour modèles liés à Site : filtre site__tenant."""

    tenant_lookup = "site__tenant"


class PtPLinkScopedAdminMixin:
    """Liaisons dont les deux sites appartiennent au tenant."""

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs = super().get_queryset(request)
        user = request.user
        if not user.is_authenticated:
            return qs.none()
        if user_sees_all_tenants(user):
            return qs
        tid = getattr(user, "tenant_id", None)
        if tid is None:
            return qs.none()
        return qs.filter(site_a__tenant_id=tid, site_b__tenant_id=tid)


class TenantScopedFKAdminMixin:
    """
    Restreint les listes déroulantes Site / NetworkDevice / PtPLink au tenant
    de l’utilisateur (sauf superuser).
    """

    def formfield_for_foreignkey(self, db_field, request, **kwargs):  # type: ignore[override]
        from apps.core.models import NetworkDevice, PtPLink, Site

        if user_sees_all_tenants(request.user):
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        tid = getattr(request.user, "tenant_id", None)
        if not tid:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.remote_field.model is Site:
            kwargs["queryset"] = Site.objects.filter(tenant_id=tid)
        elif db_field.remote_field.model is NetworkDevice:
            kwargs["queryset"] = NetworkDevice.objects.filter(site__tenant_id=tid)
        elif db_field.remote_field.model is PtPLink:
            kwargs["queryset"] = PtPLink.objects.filter(
                site_a__tenant_id=tid, site_b__tenant_id=tid
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
