"""Configuration Django — Faso ISP Manager."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)


def _env_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-in-production")
DEBUG = _env_bool("DJANGO_DEBUG", "1")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,web,testserver",
    ).split(",")
    if h.strip()
]

_csrf_raw = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [x.strip() for x in _csrf_raw.split(",") if x.strip()]

_behind_tls = _env_bool("DJANGO_BEHIND_TLS_PROXY", "0")
if _behind_tls:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "apps.tenants",
    "apps.accounts",
    "apps.core",
    "apps.wifi_zone",
    "apps.finance",
    "apps.monitoring",
    "apps.notifications",
    "apps.simulation",
    "django_q",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "apps.tenants.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

ROOT_URLCONF = "faso_isp_manager.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "faso_isp_manager.wsgi.application"

if _env_bool("USE_SQLITE", "0"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "faso_isp"),
            "USER": os.environ.get("POSTGRES_USER", "faso_isp"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "faso_isp_secret"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Ouagadougou"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

# Intégrations monitoring (URLs internes Docker)
UPTIME_KUMA_URL = os.environ.get("UPTIME_KUMA_URL", "http://uptime-kuma:3001")
UPTIME_KUMA_SOCKET_URL = os.environ.get("UPTIME_KUMA_SOCKET_URL", "ws://uptime-kuma:3001/socket.io/")
ZABBIX_API_URL = os.environ.get("ZABBIX_API_URL", "http://zabbix-web:8080/api_jsonrpc.php")
ZABBIX_API_USER = os.environ.get("ZABBIX_API_USER", "Admin")
ZABBIX_API_PASSWORD = os.environ.get("ZABBIX_API_PASSWORD", "zabbix")

SNMP_COMMUNITY = os.environ.get("SNMP_COMMUNITY", "public")
UBNT_SNMP_RSSI_OID = os.environ.get(
    "UBNT_SNMP_RSSI_OID",
    "1.3.6.1.4.1.41112.1.4.5.1.5.1.2.1",
)
UBNT_SNMP_NOISE_OID = os.environ.get(
    "UBNT_SNMP_NOISE_OID",
    "1.3.6.1.4.1.41112.1.4.5.1.5.1.3.1",
)

# MikroTik RouterOS
MIKROTIK_DEFAULT_BRIDGE_NAME = os.environ.get("MIKROTIK_DEFAULT_BRIDGE_NAME", "bridge")
MIKROTIK_DEFAULT_USERNAME = os.environ.get("MIKROTIK_DEFAULT_SSH_USER", "admin")
MIKROTIK_SSH_TIMEOUT = int(os.environ.get("MIKROTIK_SSH_TIMEOUT", "25"))
MIKROTIK_FALLBACK_SSH_PASSWORD_ENV = os.environ.get("MIKROTIK_FALLBACK_SSH_PASSWORD_ENV", "")
ROUTER_CONTROL_DRY_RUN = _env_bool("ROUTER_CONTROL_DRY_RUN", "0")
MIKROTIK_HOTSPOT_DEFAULT_PROFILE = os.environ.get("MIKROTIK_HOTSPOT_DEFAULT_PROFILE", "")
MIKROTIK_HOTSPOT_PROFILE_3H = os.environ.get("MIKROTIK_HOTSPOT_PROFILE_3H", "Profil-2H")
MIKROTIK_HOTSPOT_PROFILE_1D = os.environ.get("MIKROTIK_HOTSPOT_PROFILE_1D", "Profil-24H")
MIKROTIK_HOTSPOT_PROFILE_1W = os.environ.get("MIKROTIK_HOTSPOT_PROFILE_1W", "7j")
MIKROTIK_HOTSPOT_PROFILE_30J = os.environ.get(
    "MIKROTIK_HOTSPOT_PROFILE_30J", "Profil-30Jours"
)
MIKROTIK_HOTSPOT_SERVER = os.environ.get("MIKROTIK_HOTSPOT_SERVER", "hotspot1")

# Clé de chiffrement Fernet pour les credentials équipements (séparée de SECRET_KEY)
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

LOGIN_REDIRECT_URL = "accounts:home"
LOGIN_URL = "accounts:login"
LOGOUT_REDIRECT_URL = "accounts:login"

# django-q2 : planificateur de tâches (broker = PostgreSQL, pas de Redis requis)
Q_CLUSTER = {
    "name": "faso_isp",
    "orm": "default",
    "workers": 2,
    "timeout": 120,
    "retry": 300,
    "schedule_check": 10,
    "catch_up": False,
    "label": "Planificateur",
}

# Seuils RSSI Ubiquiti pour la santé PtP (valeur absolue dBm)
ZABBIX_PTP_RSSI_UP_THRESHOLD = int(os.environ.get("ZABBIX_PTP_RSSI_UP_THRESHOLD", "65"))
ZABBIX_PTP_RSSI_DEGRADED_THRESHOLD = int(os.environ.get("ZABBIX_PTP_RSSI_DEGRADED_THRESHOLD", "75"))

# ── django-axes : protection brute-force login ──
AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", "5"))
AXES_COOLOFF_TIME = 1  # heures avant déblocage automatique
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = True

# SaaS billing CinetPay
CINETPAY_API_KEY = os.environ.get("CINETPAY_API_KEY", "")
CINETPAY_SITE_ID = os.environ.get("CINETPAY_SITE_ID", "")
CINETPAY_NOTIFY_URL = os.environ.get("CINETPAY_NOTIFY_URL", "")
CINETPAY_RETURN_URL = os.environ.get("CINETPAY_RETURN_URL", "")
CINETPAY_MODE = os.environ.get("CINETPAY_MODE", "TEST")  # TEST ou PRODUCTION

# Mapbox GL JS (carte 3D satellite)
MAPBOX_ACCESS_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")

# WhatsApp via CallMeBot
WHATSAPP_CALLMEBOT_APIKEY = os.environ.get("WHATSAPP_CALLMEBOT_APIKEY", "")
WHATSAPP_DRY_RUN = _env_bool("WHATSAPP_DRY_RUN", "1")
WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "faest-webhook-secret")
WHATSAPP_ADMIN_NUMBER = os.environ.get("WHATSAPP_ADMIN_NUMBER", "")

# Gestion intelligente des fréquences Ubiquiti
FREQUENCY_AUTO_SWITCH = _env_bool("FREQUENCY_AUTO_SWITCH", "1")
FREQUENCY_MIN_SNR = int(os.environ.get("FREQUENCY_MIN_SNR", "15"))
FREQUENCY_MIN_SIGNAL = int(os.environ.get("FREQUENCY_MIN_SIGNAL", "-75"))
FREQUENCY_CHANGE_COOLDOWN_MINUTES = int(os.environ.get("FREQUENCY_CHANGE_COOLDOWN_MINUTES", "15"))
FREQUENCY_MAX_CHANGES_PER_HOUR = int(os.environ.get("FREQUENCY_MAX_CHANGES_PER_HOUR", "3"))
