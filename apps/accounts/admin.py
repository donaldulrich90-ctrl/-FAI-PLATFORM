from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.tenants.admin_mixins import TenantScopedAdminMixin

from .models import User


@admin.register(User)
class UserAdmin(TenantScopedAdminMixin, DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "tenant",
        "role",
        "ticket_prefix",
        "default_commission_percent",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_staff", "is_active", "is_platform_operator", "tenant")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Faso ISP",
            {
                "fields": (
                    "tenant",
                    "is_platform_operator",
                    "role",
                    "phone",
                    "default_commission_percent",
                    "ticket_prefix",
                )
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Faso ISP",
            {
                "fields": (
                    "tenant",
                    "is_platform_operator",
                    "role",
                    "phone",
                    "default_commission_percent",
                    "ticket_prefix",
                )
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            ro.append("is_platform_operator")
        return ro
