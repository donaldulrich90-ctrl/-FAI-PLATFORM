from django.contrib import admin

from apps.tenants.access import user_can_manage_tenant_records
from apps.tenants.models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    def has_module_permission(self, request) -> bool:
        return user_can_manage_tenant_records(request.user)

    def has_view_permission(self, request, obj=None) -> bool:
        return user_can_manage_tenant_records(request.user)

    def has_add_permission(self, request) -> bool:
        return user_can_manage_tenant_records(request.user)

    def has_change_permission(self, request, obj=None) -> bool:
        return user_can_manage_tenant_records(request.user)

    def has_delete_permission(self, request, obj=None) -> bool:
        return user_can_manage_tenant_records(request.user)
