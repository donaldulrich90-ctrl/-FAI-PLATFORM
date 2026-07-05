from django.apps import AppConfig


class WifiZoneConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wifi_zone"
    verbose_name = "Wi-Fi zone (tickets & abonnés)"

    def ready(self) -> None:
        from apps.wifi_zone import signals  # noqa: F401
