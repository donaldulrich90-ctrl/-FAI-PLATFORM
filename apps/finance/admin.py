from django.contrib import admin

from apps.tenants.admin_mixins import TenantScopedAdminMixin, TenantScopedFKAdminMixin

from .models import CaisseDailyReport, CashJournalEntry, MaintenanceTicket, RevendeurDailyReport


@admin.register(CashJournalEntry)
class CashJournalEntryAdmin(TenantScopedFKAdminMixin, TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = ("entry_date", "tenant", "entry_type", "amount_xof", "category", "description", "site")
    list_filter = ("entry_type", "entry_date", "site", "tenant")
    date_hierarchy = "entry_date"


@admin.register(CaisseDailyReport)
class CaisseDailyReportAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "tenant",
        "report_date",
        "wifi_zone_gross_xof",
        "wifi_zone_commissions_xof",
        "wifi_simple_collected_xof",
        "expenses_xof",
        "closed_at",
    )
    date_hierarchy = "report_date"


@admin.register(RevendeurDailyReport)
class RevendeurDailyReportAdmin(TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "report_date",
        "revendeur",
        "prefix",
        "tickets_sold_count",
        "tickets_used_count",
        "gross_xof",
        "commission_xof",
        "net_isp_xof",
        "generated_at",
    )
    list_filter = ("report_date", "tenant")
    date_hierarchy = "report_date"
    readonly_fields = ("generated_at", "detail_json")
    search_fields = ("revendeur__username", "prefix")


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(TenantScopedFKAdminMixin, TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "reference",
        "title",
        "site",
        "faulty_link",
        "assigned_to",
        "priority",
        "status",
        "opened_at",
    )
    list_filter = ("status", "priority", "site")
    search_fields = ("reference", "title", "description")
    readonly_fields = ("reference", "opened_at")
