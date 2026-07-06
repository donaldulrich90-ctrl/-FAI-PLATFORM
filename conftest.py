import django
from django.conf import settings


def pytest_configure():
    settings.configure(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "axes",
            "apps.tenants",
            "apps.accounts",
            "apps.core",
            "apps.wifi_zone",
            "apps.finance",
            "apps.monitoring",
            "django_q",
        ],
        AUTH_USER_MODEL="accounts.User",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        ROUTER_CONTROL_DRY_RUN=False,
        MIKROTIK_SSH_TIMEOUT=5,
        MIKROTIK_DEFAULT_BRIDGE_NAME="bridge",
        MIKROTIK_DEFAULT_USERNAME="admin",
        MIKROTIK_FALLBACK_SSH_PASSWORD_ENV="",
        MIKROTIK_HOTSPOT_SERVER="hotspot1",
        MIKROTIK_HOTSPOT_DEFAULT_PROFILE="",
        MIKROTIK_HOTSPOT_PROFILE_3H="Profil-2H",
        MIKROTIK_HOTSPOT_PROFILE_1D="Profil-24H",
        MIKROTIK_HOTSPOT_PROFILE_1W="7j",
        MIKROTIK_HOTSPOT_PROFILE_30J="Profil-30Jours",
        ENCRYPTION_KEY="",
        SECRET_KEY="test-secret-key-not-for-production",
        USE_TZ=True,
        TIME_ZONE="Africa/Ouagadougou",
        AXES_ENABLED=False,
        Q_CLUSTER={
            "name": "test",
            "orm": "default",
            "sync": True,
        },
    )
