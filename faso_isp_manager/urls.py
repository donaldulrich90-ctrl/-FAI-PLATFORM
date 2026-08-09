from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path
from django.views.generic import TemplateView


def handler403(request, exception=None):
    return render(request, "403.html", status=403)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("plateforme/", include("apps.tenants.urls")),
    path("comptes/", include("apps.accounts.urls", namespace="accounts")),
    path("wifi/", include("apps.wifi_zone.urls", namespace="wifi_zone")),
    path("", include("apps.finance.urls", namespace="finance")),
    path("", include("apps.monitoring.urls", namespace="monitoring")),
    path("simulation/", include("apps.simulation.urls", namespace="simulation")),
    # PWA
    path(
        "manifest.json",
        TemplateView.as_view(
            template_name="pwa/manifest.json",
            content_type="application/manifest+json",
        ),
    ),
    path(
        "sw.js",
        TemplateView.as_view(
            template_name="pwa/sw.js",
            content_type="application/javascript",
        ),
    ),
    path(
        "offline/",
        TemplateView.as_view(template_name="pwa/offline.html"),
        name="offline",
    ),
]

admin.site.site_header = "Faso ISP Manager"
admin.site.site_title = "Faso ISP"
admin.index_title = "Administration"
