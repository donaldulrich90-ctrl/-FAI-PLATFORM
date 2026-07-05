from django.contrib import admin

from apps.tenants.admin_mixins import (
    PtPLinkScopedAdminMixin,
    TenantScopedAdminMixin,
    TenantScopedFKAdminMixin,
    TenantScopedSiteFKAdminMixin,
)

from .models import NetworkDevice, PtPLink, Site


@admin.register(Site)
class SiteAdmin(TenantScopedFKAdminMixin, TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "tenant",
        "name",
        "site_id",
        "is_operational",
        "wifi_zone_hotspot_device",
        "latitude",
        "longitude",
    )
    list_filter = ("is_operational", "tenant")
    search_fields = ("name", "site_id", "address")
    raw_id_fields = ("wifi_zone_hotspot_device",)
    fieldsets = (
        (None, {"fields": ("tenant", "name", "site_id", "address", "latitude", "longitude")}),
        ("Exploitation", {"fields": ("is_operational", "notes")}),
        (
            "Wi‑Fi Zone — routeur et profils hotspot",
            {
                "description": "Renseignez le MikroTik du site, puis soit un profil unique, soit un profil par durée "
                "(noms exacts RouterOS). Champs vides : valeurs globales du fichier .env / settings.",
                "fields": (
                    "wifi_zone_hotspot_device",
                    "wifi_zone_hotspot_profile",
                    "wifi_zone_profile_3h",
                    "wifi_zone_profile_1d",
                    "wifi_zone_profile_1w",
                    "wifi_zone_profile_30j",
                ),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            ro.append("tenant")
        return ro


@admin.register(NetworkDevice)
class NetworkDeviceAdmin(TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "site",
        "vendor",
        "management_host",
        "mikrotik_bridge_name",
        "is_active",
    )
    list_filter = ("vendor", "is_active")
    search_fields = ("name", "management_host", "mikrotik_bridge_name")


@admin.register(PtPLink)
class PtPLinkAdmin(TenantScopedFKAdminMixin, PtPLinkScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "site_a", "site_b", "cached_health", "is_active")
    list_filter = ("cached_health", "is_active")
    search_fields = ("name", "zabbix_host_a", "zabbix_host_b")
