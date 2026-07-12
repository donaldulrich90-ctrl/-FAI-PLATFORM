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
    path("antennes/<int:pk>/snmp/", views.antenna_snmp_api, name="antenna_snmp_api"),
    path("antennes/<int:pk>/kick/", views.antenna_kick_station, name="antenna_kick_station"),
    path("antennes/frequences/", views.frequency_dashboard, name="frequency_dashboard"),
    path("antennes/<int:pk>/frequences/config/", views.frequency_config_save, name="frequency_config_save"),
    path("antennes/<int:pk>/frequences/changer/", views.frequency_manual_change, name="frequency_manual_change"),
    path("antennes/<int:pk>/frequences/auto/", views.frequency_toggle_auto, name="frequency_toggle_auto"),
]
