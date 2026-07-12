from django import forms
from django.contrib import admin
from django.utils.html import format_html

from apps.tenants.admin_mixins import (
    PtPLinkScopedAdminMixin,
    TenantScopedAdminMixin,
    TenantScopedFKAdminMixin,
    TenantScopedSiteFKAdminMixin,
)

from .models import NetworkDevice, PtPLink, Site


@admin.register(Site)
class SiteAdmin(TenantScopedFKAdminMixin, TenantScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "tenant",
        "name",
        "site_id",
        "is_operational",
        "wifi_zone_hotspot_device",
        "latitude",
        "longitude",
    )
    list_filter = ("is_operational", "tenant")
    search_fields = ("name", "site_id", "address")
    raw_id_fields = ("wifi_zone_hotspot_device",)
    fieldsets = (
        (None, {"fields": ("tenant", "name", "site_id", "address", "latitude", "longitude")}),
        ("Exploitation", {"fields": ("is_operational", "notes")}),
        (
            "Wi‑Fi Zone — routeur et profils hotspot",
            {
                "description": (
                    "Renseignez le MikroTik du site, puis soit un profil unique, soit un profil par durée "
                    "(noms exacts RouterOS). Champs vides : valeurs globales du fichier .env / settings."
                ),
                "fields": (
                    "wifi_zone_hotspot_device",
                    "wifi_zone_hotspot_profile",
                    "wifi_zone_profile_3h",
                    "wifi_zone_profile_1d",
                    "wifi_zone_profile_1w",
                    "wifi_zone_profile_30j",
                ),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            ro.append("tenant")
        return ro


class NetworkDeviceAdminForm(forms.ModelForm):
    """Formulaire admin avec champ mot de passe en clair (chiffré à la sauvegarde)."""

    new_password = forms.CharField(
        label="Définir le mot de passe",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text=(
            "Entrez le mot de passe en clair pour le chiffrer et le stocker de façon sécurisée. "
            "Laisser vide pour conserver l'existant. "
            "⚠️ Nécessite ENCRYPTION_KEY configurée dans l'environnement."
        ),
    )

    class Meta:
        model = NetworkDevice
        exclude = ["encrypted_password"]

    def save(self, commit: bool = True) -> NetworkDevice:
        obj: NetworkDevice = super().save(commit=False)
        plaintext = self.cleaned_data.get("new_password", "").strip()
        if plaintext:
            try:
                obj.set_password(plaintext)
            except ValueError as exc:
                self.add_error("new_password", str(exc))
        if commit:
            obj.save()
        return obj


@admin.register(NetworkDevice)
class NetworkDeviceAdmin(TenantScopedFKAdminMixin, TenantScopedSiteFKAdminMixin, admin.ModelAdmin):
    form = NetworkDeviceAdminForm
    list_display = (
        "name",
        "site",
        "vendor",
        "management_host",
        "api_port",
        "mikrotik_bridge_name",
        "password_status",
        "is_active",
    )
    list_filter = ("vendor", "is_active")
    search_fields = ("name", "management_host", "mikrotik_bridge_name")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "site",
                    "name",
                    "vendor",
                    "management_host",
                    "api_port",
                    "ssh_port",
                    "username",
                    "is_active",
                )
            },
        ),
        (
            "Authentification",
            {
                "description": (
                    "Deux méthodes, par ordre de priorité : "
                    "(1) Mot de passe chiffré en base — entrez-le ci-dessous une seule fois. "
                    "(2) Référence à une variable d'environnement — ex. <code>env:MIKROTIK_PASS_SITE1</code>."
                ),
                "fields": ("new_password", "password_hint"),
            },
        ),
        (
            "MikroTik",
            {"fields": ("mikrotik_bridge_name", "parent_mikrotik", "mikrotik_interface")},
        ),
        (
            "Ubiquiti airOS — SSH direct (port forwarding)",
            {
                "description": (
                    "Connexion SSH directe à l'antenne via le port-forwarding du MikroTik parent. "
                    "Renseignez le port forwardé (ex. 2222) et le username airOS. "
                    "Si configuré, les métriques temps réel (fréquence, clients, TX) utilisent ce canal."
                ),
                "fields": ("ssh_forward_port", "aireos_username"),
            },
        ),
    )
    readonly_fields = ("password_status",)

    @admin.display(description="Credential")
    def password_status(self, obj: NetworkDevice) -> str:
        if obj.has_stored_password():
            return format_html('<span style="color:#22c55e">🔒 Chiffré en base</span>')
        if (obj.password_hint or "").startswith("env:"):
            return format_html('<span style="color:#f59e0b">🔑 Variable env</span>')
        if obj.password_hint:
            return format_html('<span style="color:#f59e0b">🔑 Hint configuré</span>')
        return format_html('<span style="color:#ef4444">⚠ Non configuré</span>')


@admin.register(PtPLink)
class PtPLinkAdmin(TenantScopedFKAdminMixin, PtPLinkScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "site_a", "site_b", "cached_health", "is_active")
    list_filter = ("cached_health", "is_active")
    search_fields = ("name", "zabbix_host_a", "zabbix_host_b")
