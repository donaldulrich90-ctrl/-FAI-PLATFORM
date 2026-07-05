from django.urls import path

from . import views

app_name = "monitoring"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/monitoring/uptime-kuma/", views.api_uptime_kuma, name="api_uptime_kuma"),
    path(
        "api/monitoring/zabbix/host/<path:host_name>/",
        views.api_zabbix_host,
        name="api_zabbix_host",
    ),
    path("antennes/", views.antenna_list, name="antenna_list"),
    path("antennes/<int:pk>/frequence/", views.antenna_freq_change, name="antenna_freq_change"),
]
