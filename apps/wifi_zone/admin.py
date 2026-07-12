from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.tenants.admin_mixins import TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin

from .models import PlanAbonnement, Ticket, WifiTicketBatch, WiFiSimpleSubscriber


@admin.register(PlanAbonnement)
class PlanAbonnementAdmin(TenantScopedFKAdminMixin, admin.ModelAdmin):
    list_display = ("name", "speed_mbps", "upload_mbps", "price_xof", "profil_mikrotik", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "profil_mikrotik")
    list_editable = ("is_active",)
    fieldsets = (
        (None, {"fields": ("tenant", "name", "is_active")}),
        ("Débit", {"fields": ("speed_mbps", "upload_mbps")}),
        ("Tarif & MikroTik", {"fields": ("price_xof", "profil_mikrotik")}),
        ("Notes", {"fields": ("description",)}),
    )


@admin.register(WifiTicketBatch)
class WifiTicketBatchAdmin(TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin, admin.ModelAdmin):
    list_display = ("label", "site", "duration", "quantity", "unit_price_xof", "created_at", "created_by", "imprimer_pdf")
    list_filter = ("site", "duration")

    @admin.display(description="Imprimer")
    def imprimer_pdf(self, obj):
        url = reverse("wifi_zone:print_batch_pdf", args=[obj.pk])
        return format_html('<a href="{}" target="_blank" style="color:#10b981">📄 PDF</a>', url)


@admin.register(Ticket)
class TicketAdmin(TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "duration",
        "price_xof",
        "is_used",
        "status",
        "site",
        "sold_by",
        "hotspot_synced_at",
        "commission_amount_xof",
        "net_to_isp_xof",
        "created_at",
    )
    list_filter = ("status", "is_used", "duration", "site")
    search_fields = ("code",)
    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
        "hotspot_synced_at",
        "hotspot_sync_error",
    )


@admin.register(WiFiSimpleSubscriber)
class WiFiSimpleSubscriberAdmin(TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin, admin.ModelAdmin):
    list_display = (
        "full_name",
        "phone",
        "mac_address",
        "plan_name",
        "plan_vitesse",
        "plan_prix",
        "status",
        "expires_at",
        "site",
        "is_payment_current",
        "mac_blocked_on_network",
    )
    list_filter = ("site", "status", "plan", "is_payment_current", "mac_blocked_on_network")
    search_fields = ("full_name", "phone", "mac_address")
    list_select_related = ("plan", "site")

    @admin.display(description="Plan", ordering="plan__name")
    def plan_name(self, obj):
        return obj.plan.name if obj.plan else "—"

    @admin.display(description="Vitesse")
    def plan_vitesse(self, obj):
        if obj.plan:
            return f"{obj.plan.speed_mbps}↓/{obj.plan.upload_mbps}↑ Mbps"
        return "—"

    @admin.display(description="Prix/mois", ordering="plan__price_xof")
    def plan_prix(self, obj):
        return f"{int(obj.plan.price_xof)} XOF" if obj.plan else "—"
