from __future__ import annotations

import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import NetworkDevice, Site


class Ticket(models.Model):
    """Ticket d'accès Wi-Fi Zone (voucher) avec code unique et commission revendeur."""

    class Duration(models.TextChoices):
        THREE_HOURS = "3h", "3 heures"
        ONE_DAY = "1d", "24 heures (1 jour)"
        ONE_WEEK = "1w", "7 jours"
        THIRTY_DAYS = "30j", "30 jours"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        USED = "used", "Utilisé"
        EXPIRED = "expired", "Expiré"

    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
    )
    duration = models.CharField(max_length=8, choices=Duration.choices, db_index=True)
    price_xof = models.DecimalField(
        "Prix (XOF)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
        help_text="Franc CFA BCEAO — montant encaissé côté revendeur ou PDV.",
    )
    is_used = models.BooleanField("Utilisé ?", default=False, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="wifi_tickets",
        verbose_name="Site",
    )
    batch = models.ForeignKey(
        "WifiTicketBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
        verbose_name="Lot d'origine",
    )
    sold_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wifi_tickets_sold",
        verbose_name="Revendeur / vendeur",
    )
    commission_rate_percent = models.DecimalField(
        "Taux commission (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    commission_amount_xof = models.DecimalField(
        "Commission (XOF)",
        max_digits=12,
        decimal_places=0,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    net_to_isp_xof = models.DecimalField(
        "Net FAI (XOF)",
        max_digits=12,
        decimal_places=0,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Montant dû à l'opérateur après commission.",
    )
    sold_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    hotspot_password = models.CharField(
        "Mot de passe MikroTik",
        max_length=64,
        blank=True,
        help_text="Mot de passe distinct du code (tickets revendeurs). Vide = utilise le code comme mot de passe.",
    )
    hotspot_synced_at = models.DateTimeField(
        "Dernier provisionnement Hotspot",
        null=True,
        blank=True,
        help_text="Routeur MikroTik : utilisateur présent ; vidé après retrait / erreur.",
    )
    hotspot_sync_error = models.CharField(
        "Erreur sync Hotspot",
        max_length=512,
        blank=True,
        help_text="Dernier message d’échec (SSH / configuration).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ticket Wi-Fi Zone"
        verbose_name_plural = "tickets Wi-Fi Zone"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} — {self.site.site_id}"

    def compute_commission_amounts(self) -> None:
        """Calcule commission et net FAI selon le revendeur et le taux."""
        price = self.price_xof
        user = self.sold_by
        if user is not None and getattr(user, "is_revendeur", False):
            rate = self.commission_rate_percent or getattr(
                user, "default_commission_percent", Decimal("0")
            )
            comm = (price * rate / Decimal("100")).quantize(Decimal("1"))
            self.commission_amount_xof = comm
            self.net_to_isp_xof = price - comm
            self.commission_rate_percent = rate
        else:
            self.commission_rate_percent = Decimal("0")
            self.commission_amount_xof = Decimal("0")
            self.net_to_isp_xof = price

    def save(self, *args, **kwargs):
        from apps.wifi_zone.services.wifi_access_code import WifiAccessCodeService

        if not self.code:
            self.code = WifiAccessCodeService().generate_unique_code()
        if self.status == self.Status.EXPIRED:
            self.is_used = False
        elif self.status == self.Status.USED:
            self.is_used = True
        elif self.is_used:
            self.status = self.Status.USED
        self.compute_commission_amounts()
        super().save(*args, **kwargs)


class WifiTicketBatch(models.Model):
    """Lot de tickets généré en masse (export PDF / QR)."""

    label = models.CharField("Libellé", max_length=128, blank=True)
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="wifi_ticket_batches",
        verbose_name="Site",
    )
    duration = models.CharField(
        max_length=8,
        choices=Ticket.Duration.choices,
        db_index=True,
    )
    unit_price_xof = models.DecimalField(
        "Prix unitaire (XOF)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    quantity = models.PositiveIntegerField(
        "Nombre de tickets",
        validators=[MinValueValidator(1), MaxValueValidator(500)],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wifi_ticket_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "lot de tickets Wi-Fi"
        verbose_name_plural = "lots de tickets Wi-Fi"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.label or f"Lot #{self.pk} ({self.quantity})"


class PlanAbonnement(models.Model):
    """Plan d'abonnement domicile (Starter, Standard, Premium, Business)."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="plans_abonnement",
        verbose_name="Organisation",
    )
    name = models.CharField("Nom du plan", max_length=128)
    speed_mbps = models.PositiveIntegerField("Débit download (Mbps)", default=2)
    upload_mbps = models.PositiveIntegerField("Débit upload (Mbps)", default=2)
    price_xof = models.DecimalField(
        "Prix mensuel (XOF)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    profil_mikrotik = models.CharField("Profil MikroTik", max_length=64, blank=True)
    description = models.TextField("Description", blank=True)
    is_active = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "plan d'abonnement"
        verbose_name_plural = "plans d'abonnement"
        ordering = ["price_xof"]

    def __str__(self) -> str:
        return f"{self.name} — {self.speed_mbps}↓/{self.upload_mbps}↑ Mbps — {self.price_xof} XOF"


class WiFiSimpleSubscriber(models.Model):
    """Abonné domicile : expiration, MAC/IP, GPS, plan mensuel, contrôle MikroTik."""

    class Status(models.TextChoices):
        NOUVEAU = "nouveau", "Nouveau"
        ACTIF = "actif", "Actif"
        SUSPENDU = "suspendu", "Suspendu"
        EXPIRE = "expire", "Expiré"

    full_name = models.CharField("Nom", max_length=128)
    phone = models.CharField("Téléphone", max_length=32, db_index=True)
    whatsapp_phone = models.CharField(
        "Numéro WhatsApp",
        max_length=32,
        blank=True,
        help_text="+226XXXXXXXXX — laissez vide pour utiliser le numéro principal.",
    )
    address = models.CharField("Adresse", max_length=255, blank=True)
    quartier = models.CharField("Quartier", max_length=64, blank=True)
    latitude = models.DecimalField(
        "Latitude GPS", max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        "Longitude GPS", max_digits=9, decimal_places=6, null=True, blank=True
    )
    mac_address = models.CharField(
        "Adresse MAC (CPE / client)",
        max_length=17,
        db_index=True,
        blank=True,
        help_text="Format AA:BB:CC:DD:EE:FF — utilisé pour blocage / déblocage.",
    )
    ip_static = models.GenericIPAddressField(
        "IP statique",
        null=True,
        blank=True,
        help_text="IP client pour Simple Queue et ARP statique.",
    )
    plan = models.ForeignKey(
        PlanAbonnement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscribers",
        verbose_name="Plan souscrit",
    )
    expires_at = models.DateTimeField("Date d'expiration", db_index=True)
    status = models.CharField(
        "Statut",
        max_length=16,
        choices=Status.choices,
        default=Status.NOUVEAU,
        db_index=True,
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="wifi_simple_subscribers",
        verbose_name="Site de raccordement",
    )
    cpe_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wifi_simple_subscribers",
        verbose_name="Routeur MikroTik",
        help_text="Équipement cible pour les commandes RouterOS.",
    )
    is_payment_current = models.BooleanField("Abonnement payé à jour", default=True, db_index=True)
    mac_blocked_on_network = models.BooleanField(
        "MAC bloquée sur le réseau",
        default=False,
        help_text="Synchronisé après commande RouterOS réussie.",
    )
    last_billing_sync_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wifi_zone_clientabonne"
        verbose_name = "abonné domicile"
        verbose_name_plural = "abonnés domicile"
        ordering = ["-expires_at"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone})"

    @property
    def effective_whatsapp_phone(self) -> str:
        return (self.whatsapp_phone or self.phone).strip()

    @property
    def is_expiring_soon(self) -> bool:
        from datetime import timedelta
        return self.expires_at <= timezone.now() + timedelta(days=7)

    @property
    def days_until_expiry(self) -> int:
        delta = self.expires_at - timezone.now()
        return max(0, delta.days)


class TicketPlainte(models.Model):
    """Ticket de plainte client (WhatsApp, appel ou manuel)."""

    class Source(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        APPEL = "appel", "Appel téléphonique"
        MANUEL = "manuel", "Saisie manuelle"

    class Priority(models.TextChoices):
        HAUTE = "haute", "Haute"
        MOYENNE = "moyenne", "Moyenne"
        BASSE = "basse", "Basse"

    class Status(models.TextChoices):
        NOUVEAU = "nouveau", "Nouveau"
        EN_COURS = "en_cours", "En cours"
        RESOLU = "resolu", "Résolu"
        FERME = "ferme", "Fermé"

    _HIGH_KEYWORDS = ["urgent", "pas de connexion", "rien", "coupure", "pas internet"]
    _MEDIUM_KEYWORDS = ["lent", "lenteur", "problème", "probleme", "pb"]
    _LOW_KEYWORDS = ["question", "info", "renseignement"]

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="tickets_plainte",
        verbose_name="Organisation",
    )
    reference = models.CharField("Référence", max_length=32, db_index=True, editable=False)
    subscriber = models.ForeignKey(
        WiFiSimpleSubscriber,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_plainte",
        verbose_name="Abonné",
    )
    phone_from = models.CharField("Téléphone expéditeur", max_length=32, blank=True)
    source = models.CharField(
        "Source", max_length=16, choices=Source.choices, default=Source.MANUEL, db_index=True
    )
    message_original = models.TextField("Message original")
    category = models.CharField("Catégorie", max_length=64, blank=True)
    priority = models.CharField(
        "Priorité",
        max_length=16,
        choices=Priority.choices,
        default=Priority.MOYENNE,
        db_index=True,
    )
    status = models.CharField(
        "Statut",
        max_length=16,
        choices=Status.choices,
        default=Status.NOUVEAU,
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_plainte_assigned",
        verbose_name="Technicien assigné",
    )
    resolution_notes = models.TextField("Notes de résolution", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ticket de plainte"
        verbose_name_plural = "tickets de plainte"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "reference"],
                name="wifi_ticketplainte_tenant_reference_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.message_original[:60]}"

    @classmethod
    def classify_priority(cls, text: str) -> str:
        t = text.lower()
        if any(kw in t for kw in cls._HIGH_KEYWORDS):
            return cls.Priority.HAUTE
        if any(kw in t for kw in cls._MEDIUM_KEYWORDS):
            return cls.Priority.MOYENNE
        if any(kw in t for kw in cls._LOW_KEYWORDS):
            return cls.Priority.BASSE
        return cls.Priority.MOYENNE

    def save(self, *args, **kwargs):
        if not self.reference:
            year = timezone.now().year
            last = (
                TicketPlainte.objects.filter(
                    tenant_id=self.tenant_id,
                    reference__startswith=f"TICK-{year}-",
                )
                .order_by("-reference")
                .values_list("reference", flat=True)
                .first()
            )
            if last:
                try:
                    num = int(last.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            for _ in range(10):
                candidate = f"TICK-{year}-{num:03d}"
                if not TicketPlainte.objects.filter(
                    tenant_id=self.tenant_id, reference=candidate
                ).exists():
                    self.reference = candidate
                    break
                num += 1
            else:
                self.reference = f"TICK-{year}-{secrets.token_hex(3).upper()}"
        if not self.priority:
            self.priority = self.classify_priority(self.message_original)
        super().save(*args, **kwargs)
