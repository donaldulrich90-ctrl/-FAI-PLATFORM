from django.contrib import admin

from .models import DeviceConfigChange, RouterAuditLog


@admin.register(RouterAuditLog)
class RouterAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "tenant",
        "device",
        "action",
        "target",
        "success",
        "dry_run",
        "performed_by",
        "ip_address",
    )
    list_filter = ("action", "success", "dry_run", "tenant")
    search_fields = ("target", "command_sent", "error_message", "device__name")
    date_hierarchy = "created_at"
    readonly_fields = (
        "tenant",
        "device",
        "performed_by",
        "action",
        "target",
        "command_sent",
        "success",
        "error_message",
        "dry_run",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DeviceConfigChange)
class DeviceConfigChangeAdmin(admin.ModelAdmin):
    list_display = ("created_at", "device", "change_type", "old_value", "new_value", "success", "dry_run")
    list_filter = ("change_type", "success", "dry_run")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False
