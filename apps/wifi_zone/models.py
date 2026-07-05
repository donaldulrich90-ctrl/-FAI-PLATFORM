from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

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


class WiFiSimpleSubscriber(models.Model):
    """Abonné mensuel Wi-Fi Simple : expiration, MAC pour blocage SSH sur routeur Ubiquiti."""

    full_name = models.CharField("Nom", max_length=128)
    phone = models.CharField("Téléphone", max_length=32, db_index=True)
    mac_address = models.CharField(
        "Adresse MAC (CPE / client)",
        max_length=17,
        db_index=True,
        blank=True,
        help_text="Format AA:BB:CC:DD:EE:FF — utilisé pour blocage / déblocage.",
    )
    expires_at = models.DateTimeField("Date d'expiration", db_index=True)
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
        verbose_name="Équipement (routeur / AP)",
        help_text="Cible des commandes SSH / blocage MAC.",
    )
    is_payment_current = models.BooleanField("Abonnement payé à jour", default=True, db_index=True)
    mac_blocked_on_network = models.BooleanField(
        "MAC bloquée sur le réseau",
        default=False,
        help_text="Synchronisé après commande SSH réussie.",
    )
    last_billing_sync_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wifi_zone_clientabonne"
        verbose_name = "abonné Wi-Fi Simple"
        verbose_name_plural = "abonnés Wi-Fi Simple"
        ordering = ["-expires_at"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone})"
