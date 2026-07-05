from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path


def handler403(request, exception=None):
    return render(request, "403.html", status=403)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("plateforme/", include("apps.tenants.urls")),
    path("comptes/", include("apps.accounts.urls", namespace="accounts")),
    path("wifi/", include("apps.wifi_zone.urls", namespace="wifi_zone")),
    path("", include("apps.finance.urls", namespace="finance")),
    path("", include("apps.monitoring.urls", namespace="monitoring")),
]

admin.site.site_header = "Faso ISP Manager"
admin.site.site_title = "Faso ISP"
admin.index_title = "Administration"
