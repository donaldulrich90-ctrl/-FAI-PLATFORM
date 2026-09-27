from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.tenants.admin_mixins import TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin

from .models import (
    LoyaltyProgress,
    LoyaltyPurchaseEvent,
    PlanAbonnement,
    Ticket,
    TicketConsommation,
    WifiTicketBatch,
    WiFiSimpleSubscriber,
)


@admin.register(LoyaltyProgress)
class LoyaltyProgressAdmin(admin.ModelAdmin):
    list_display = (
        "mac_address", "duration", "plan_price_xof", "paid_count", "bonus_count", "site", "updated_at"
    )
    list_filter = ("duration", "site")
    search_fields = ("mac_address",)
    readonly_fields = (
        "tenant", "site", "mac_address", "duration", "plan_price_xof",
        "paid_count", "bonus_count", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoyaltyPurchaseEvent)
class LoyaltyPurchaseEventAdmin(admin.ModelAdmin):
    list_display = ("source_ticket", "payment_method", "bonus_ticket", "progress", "created_at")
    list_filter = ("payment_method", "created_at")
    search_fields = ("source_ticket__code", "bonus_ticket__code", "progress__mac_address")
    readonly_fields = ("progress", "source_ticket", "payment_method", "bonus_ticket", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
        "expiration_calendaire",
    )

    @admin.display(description="Expiration (calendaire)")
    def expiration_calendaire(self, obj):
        exp = obj.expires_at
        if exp is None:
            return "— (illimité ou non activé)"
        return exp.strftime("%d/%m/%Y %H:%M")


@admin.register(TicketConsommation)
class TicketConsommationAdmin(admin.ModelAdmin):
    """Archive-preuve des tickets consommés — lecture seule."""

    list_display = (
        "code",
        "duration",
        "price_xof",
        "commission_amount_xof",
        "net_to_isp_xof",
        "sold_by",
        "activated_at",
        "expires_at",
        "expired_at",
        "site",
    )
    list_filter = ("duration", "site", "activated_at")
    search_fields = ("code", "mac_address", "client_ip")
    date_hierarchy = "activated_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


# ── Paiement Mobile Money en ligne ────────────────────────────────────────────
from .models import WifiPurchase, WifiZoneTarif  # noqa: E402


@admin.register(WifiZoneTarif)
class WifiZoneTarifAdmin(admin.ModelAdmin):
    list_display = ("__str__", "site", "duration", "label", "price_xof", "is_active", "updated_at")
    list_filter = ("is_active", "duration", "site")
    list_editable = ("price_xof", "is_active")
    search_fields = ("label",)
    fieldsets = (
        (None, {"fields": ("site", "duration", "label")}),
        ("Tarif", {"fields": ("price_xof", "is_active")}),
    )


@admin.register(WifiPurchase)
class WifiPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "site", "duration", "amount_xof", "provider",
        "status", "phone", "ticket", "created_at", "paid_at",
    )
    list_filter = ("status", "provider", "site", "duration", "created_at")
    search_fields = ("reference", "phone", "mac_address", "operator_id", "ticket__code")
    date_hierarchy = "created_at"
    readonly_fields = (
        "reference", "site", "duration", "amount_xof", "provider", "phone",
        "mac_address", "client_ip", "login_url", "destination_url", "status",
        "payment_token", "payment_url", "operator_id", "ticket", "error_message",
        "raw_init", "raw_notify", "created_at", "updated_at", "paid_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
