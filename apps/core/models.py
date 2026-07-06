from django.core.exceptions import ValidationError
from django.db import models


class Site(models.Model):
    """Site de couverture Wi-Fi / point de présence / extrémité PtP."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="sites",
        verbose_name="Organisation",
    )
    name = models.CharField("Nom du site", max_length=128)
    site_id = models.CharField(
        "Identifiant site (réf. expl.)",
        max_length=64,
        db_index=True,
        help_text="Identifiant aligné sur Zabbix / routeurs / procédures terrain. Unique par organisation.",
    )
    address = models.CharField("Adresse", max_length=255, blank=True)
    latitude = models.DecimalField("Latitude", max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField("Longitude", max_digits=9, decimal_places=6, null=True, blank=True)
    is_operational = models.BooleanField(
        "Site opérationnel (carte verte)",
        default=True,
        help_text="Mis à jour manuellement ou par le monitoring.",
    )
    notes = models.TextField(blank=True)
    wifi_zone_hotspot_device = models.ForeignKey(
        "NetworkDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sites_as_wifi_zone_hotspot",
        verbose_name="Routeur Hotspot Wi‑Fi Zone",
        help_text="MikroTik sur lequel créer les utilisateurs /ip hotspot user pour les tickets. "
        "Vide : premier équipement MikroTik actif du site.",
    )
    wifi_zone_hotspot_profile = models.CharField(
        "Profil Hotspot (toutes durées)",
        max_length=64,
        blank=True,
        help_text="Optionnel : un seul profil RouterOS pour tous les tickets de ce site. "
        "Si vide, utilisation des profils par durée ci‑dessous, puis des valeurs globales (.env / settings).",
    )
    wifi_zone_profile_3h = models.CharField(
        "Profil hotspot — 3 h",
        max_length=64,
        blank=True,
        help_text="Nom exact du profil /ip hotspot user profile pour les tickets 3 h. Vide = défaut global.",
    )
    wifi_zone_profile_1d = models.CharField(
        "Profil hotspot — 24 h (1 jour)",
        max_length=64,
        blank=True,
        help_text="Profil pour les tickets 1 jour. Vide = défaut global.",
    )
    wifi_zone_profile_1w = models.CharField(
        "Profil hotspot — 7 jours",
        max_length=64,
        blank=True,
        help_text="Profil pour les tickets 1 semaine. Vide = défaut global.",
    )
    wifi_zone_profile_30j = models.CharField(
        "Profil hotspot — 30 jours",
        max_length=64,
        blank=True,
        help_text="Profil pour les tickets 30 jours. Vide = défaut global.",
    )

    class Meta:
        verbose_name = "site"
        verbose_name_plural = "sites"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "site_id"],
                name="core_site_tenant_site_id_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.site_id})"

    def clean(self) -> None:
        super().clean()
        dev = self.wifi_zone_hotspot_device
        if dev is not None and self.pk is not None and dev.site_id != self.pk:
            raise ValidationError(
                {
                    "wifi_zone_hotspot_device": "L’équipement doit appartenir à ce site.",
                }
            )


class NetworkDevice(models.Model):
    """Routeur / équipement pour commandes SSH (Ubiquiti AirOS, etc.)."""

    class Vendor(models.TextChoices):
        UBIQUITI = "ubiquiti", "Ubiquiti"
        MIKROTIK = "mikrotik", "MikroTik"
        OTHER = "other", "Autre"

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name="Site",
    )
    name = models.CharField(max_length=128)
    vendor = models.CharField(max_length=20, choices=Vendor.choices, default=Vendor.OTHER)
    management_host = models.CharField("IP / hostname", max_length=255)
    api_port = models.PositiveIntegerField(
        default=8728,
        help_text="Port API RouterOS (8728 plain, 8729 SSL). Laisser 8728 par défaut.",
    )
    ssh_port = models.PositiveIntegerField(default=22)
    username = models.CharField(max_length=128, blank=True)
    password_hint = models.CharField(
        "Réf. secret (env var)",
        max_length=128,
        blank=True,
        help_text=(
            "Référence à une variable d’environnement : ex. env:MIKROTIK_PASS_SITE12. "
            "Laisser vide si le mot de passe est défini via le champ ‘Définir le mot de passe’ ci-dessous."
        ),
    )
    encrypted_password = models.TextField(
        "Mot de passe chiffré",
        blank=True,
        editable=False,
        help_text="Token Fernet (géré automatiquement — ne pas modifier manuellement).",
    )
    mikrotik_bridge_name = models.CharField(
        "Bridge MikroTik (filtre MAC)",
        max_length=48,
        blank=True,
        help_text="Nom de l’interface bridge pour /interface bridge filter (ex. bridge). "
        "Vide = paramètre MIKROTIK_DEFAULT_BRIDGE_NAME.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "équipement réseau"
        verbose_name_plural = "équipements réseau"

    def __str__(self) -> str:
        return f"{self.name} @ {self.site}"

    def set_password(self, plaintext: str) -> None:
        """Chiffre le mot de passe et le stocke dans encrypted_password (Fernet)."""
        from apps.core.services.encryption import encrypt_credential
        self.encrypted_password = encrypt_credential(plaintext)

    def has_stored_password(self) -> bool:
        return bool(self.encrypted_password)


class PtPLink(models.Model):
    """
    Liaison point-à-point (typ. Ubiquiti AirMAX) entre deux sites.
    Santé affichée sur la carte (vert / orange / rouge) via Zabbix / SNMP.
    """

    class HealthState(models.TextChoices):
        UP = "up", "OK (vert)"
        DEGRADED = "degraded", "Dégradé (orange)"
        DOWN = "down", "Hors service (rouge)"
        UNKNOWN = "unknown", "Inconnu"

    name = models.CharField(max_length=128)
    site_a = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="ptp_links_as_a",
        verbose_name="Site extrémité A",
    )
    site_b = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="ptp_links_as_b",
        verbose_name="Site extrémité B",
    )
    endpoint_a_lat = models.DecimalField(
        "Lat. antenne A", max_digits=9, decimal_places=6, null=True, blank=True
    )
    endpoint_a_lng = models.DecimalField(
        "Lng. antenne A", max_digits=9, decimal_places=6, null=True, blank=True
    )
    endpoint_b_lat = models.DecimalField(
        "Lat. antenne B", max_digits=9, decimal_places=6, null=True, blank=True
    )
    endpoint_b_lng = models.DecimalField(
        "Lng. antenne B", max_digits=9, decimal_places=6, null=True, blank=True
    )
    zabbix_host_a = models.CharField(
        "Host Zabbix (extrémité A)",
        max_length=128,
        blank=True,
        help_text="Nom d'hôte tel que dans Zabbix (items SNMP RSSI / bruit / débit).",
    )
    zabbix_host_b = models.CharField("Host Zabbix (extrémité B)", max_length=128, blank=True)
    snmp_management_ip = models.GenericIPAddressField(
        "IP SNMP (sonde directe pysnmp)",
        protocol="IPv4",
        unpack_ipv4=False,
        null=True,
        blank=True,
        help_text="Optionnel : interrogation directe airMAX en complément de Zabbix.",
    )
    snmp_community_secret_ref = models.CharField(
        "Réf. communauté SNMP (vault)",
        max_length=128,
        blank=True,
    )
    cached_health = models.CharField(
        max_length=16,
        choices=HealthState.choices,
        default=HealthState.UNKNOWN,
        db_index=True,
    )
    cached_health_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "liaison PtP"
        verbose_name_plural = "liaisons PtP"
        ordering = ["name"]

    def clean(self) -> None:
        super().clean()
        if self.site_a_id and self.site_b_id and self.site_a.tenant_id != self.site_b.tenant_id:
            raise ValidationError(
                "Les deux sites d'une liaison PtP doivent appartenir à la même organisation."
            )

    def __str__(self) -> str:
        return f"{self.name} ({self.site_a_id} ↔ {self.site_b_id})"
