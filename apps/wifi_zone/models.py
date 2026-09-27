from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import NetworkDevice, Site


# ── Validité calendaire des tickets ───────────────────────────────────────────
# Délai de validité d'un ticket À PARTIR DE SON ACTIVATION (temps calendaire,
# pas temps de connexion cumulé). None = jamais d'expiration (illimité).
TICKET_DURATION_TIMEDELTA = {
    "2h": timedelta(hours=2),
    "3h": timedelta(hours=3),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "5j": timedelta(days=5),
    "1w": timedelta(days=7),
    "30j": timedelta(days=30),
    "illimite": None,
}
# Anciennes clés éventuellement présentes en base
_TICKET_DURATION_LEGACY = {"1h": "3h", "24h": "1d", "1j": "1d", "7j": "1w"}


def ticket_duration_delta(duration: str):
    """Retourne le timedelta de validité pour une durée de ticket (None si illimité/inconnu)."""
    key = _TICKET_DURATION_LEGACY.get(duration, duration)
    return TICKET_DURATION_TIMEDELTA.get(key)


def compute_ticket_expiry(activated_at, duration):
    """Date d'expiration calendaire = activation + durée. None si illimité ou pas d'activation."""
    if activated_at is None:
        return None
    delta = ticket_duration_delta(duration)
    if delta is None:
        return None
    return activated_at + delta


class Ticket(models.Model):
    """Ticket d'accès Wi-Fi Zone (voucher) avec code unique et commission revendeur."""

    class Duration(models.TextChoices):
        TWO_HOURS = "2h", "2 heures"
        THREE_HOURS = "3h", "3 heures"
        FOUR_HOURS = "4h", "4 heures"
        ONE_DAY = "1d", "24 heures (1 jour)"
        FIVE_DAYS = "5j", "5 jours"
        ONE_WEEK = "1w", "7 jours"
        THIRTY_DAYS = "30j", "30 jours"
        UNLIMITED = "illimite", "Illimité"

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
    mac_address = models.CharField(
        "MAC du client",
        max_length=17,
        blank=True,
        null=True,
        help_text="Adresse MAC de l’appareil qui a activé le ticket (remontée depuis MikroTik).",
    )
    client_ip = models.GenericIPAddressField(
        "IP du client",
        null=True,
        blank=True,
        help_text="IP attribuée au client lors de la connexion hotspot.",
    )
    first_used_at = models.DateTimeField(
        "Première utilisation",
        null=True,
        blank=True,
        help_text="Date/heure de la première connexion détectée via MikroTik.",
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
            if not self.used_at:
                self.used_at = timezone.now()
        elif self.is_used:
            self.status = self.Status.USED
            if not self.used_at:
                self.used_at = timezone.now()
        self.compute_commission_amounts()
        super().save(*args, **kwargs)

    @property
    def activated_at(self):
        """Moment de l'activation du ticket (1re connexion, sinon date d'usage)."""
        return self.first_used_at or self.used_at

    @property
    def expires_at(self):
        """Fin de validité calendaire à partir de l'activation (None si illimité/non activé)."""
        return compute_ticket_expiry(self.activated_at, self.duration)

    @property
    def is_expired_by_time(self) -> bool:
        """Vrai si la durée calendaire est écoulée (indépendamment du statut en base)."""
        exp = self.expires_at
        return exp is not None and exp < timezone.now()


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


class TicketConsommation(models.Model):
    """Archive-preuve d'un ticket Wi-Fi Zone consommé (activé par un client).

    Créée automatiquement à la PREMIÈRE activation d'un ticket. Sert de preuve
    permanente de la transaction : montants encaissés, appareil du client,
    date d'activation et d'expiration. Les montants sont dénormalisés pour que
    la preuve reste valable même si le ticket d'origine est modifié/supprimé.
    """

    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consommation",
        verbose_name="Ticket d'origine",
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="ticket_consommations",
        null=True,
        blank=True,
        verbose_name="Organisation",
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_consommations",
        verbose_name="Site",
    )
    code = models.CharField("Code ticket", max_length=32, db_index=True)
    duration = models.CharField("Durée", max_length=8, choices=Ticket.Duration.choices)
    price_xof = models.DecimalField(
        "Prix (XOF)", max_digits=12, decimal_places=0, default=Decimal("0")
    )
    commission_amount_xof = models.DecimalField(
        "Commission (XOF)", max_digits=12, decimal_places=0, default=Decimal("0")
    )
    net_to_isp_xof = models.DecimalField(
        "Net FAI (XOF)", max_digits=12, decimal_places=0, default=Decimal("0")
    )
    sold_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_consommations",
        verbose_name="Revendeur / vendeur",
    )
    mac_address = models.CharField("MAC du client", max_length=17, blank=True)
    client_ip = models.GenericIPAddressField("IP du client", null=True, blank=True)
    activated_at = models.DateTimeField("Activé le", db_index=True)
    expires_at = models.DateTimeField(
        "Expire le",
        null=True,
        blank=True,
        db_index=True,
        help_text="Fin de validité calendaire (vide = illimité).",
    )
    expired_at = models.DateTimeField(
        "Expiré le",
        null=True,
        blank=True,
        help_text="Date effective de passage du ticket au statut Expiré.",
    )
    cash_entry = models.ForeignKey(
        "finance.CashJournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_consommations",
        verbose_name="Écriture de caisse (preuve comptable)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ticket consommé (archive)"
        verbose_name_plural = "tickets consommés (archives)"
        ordering = ["-activated_at"]

    def __str__(self) -> str:
        return f"{self.code} — activé le {self.activated_at:%d/%m/%Y %H:%M}"


class LoyaltyProgress(models.Model):
    """Progression du bonus par appareil, site et forfait exact."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="wifi_loyalty_progress",
        null=True,
        blank=True,
        verbose_name="Organisation",
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="wifi_loyalty_progress",
        verbose_name="Site",
    )
    mac_address = models.CharField("MAC du client", max_length=17, db_index=True)
    duration = models.CharField("Durée", max_length=8, choices=Ticket.Duration.choices)
    plan_price_xof = models.DecimalField(
        "Prix du forfait (XOF)", max_digits=12, decimal_places=0, default=Decimal("0")
    )
    paid_count = models.PositiveSmallIntegerField("Progression (0 à 4)", default=0)
    bonus_count = models.PositiveIntegerField("Bonus attribués", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "progression fidélité Wi-Fi"
        verbose_name_plural = "progressions fidélité Wi-Fi"
        constraints = [
            models.UniqueConstraint(
                fields=("site", "mac_address", "duration", "plan_price_xof"),
                name="uniq_loyalty_device_plan",
            ),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.mac_address} — {self.duration}/{self.plan_price_xof} — {self.paid_count}/5"


class LoyaltyPurchaseEvent(models.Model):
    """Achat confirmé ayant compté une fois dans la fidélité."""

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Espèces"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        UNKNOWN = "unknown", "Non précisé"

    progress = models.ForeignKey(
        LoyaltyProgress,
        on_delete=models.PROTECT,
        related_name="purchase_events",
        verbose_name="Progression",
    )
    source_ticket = models.OneToOneField(
        Ticket,
        on_delete=models.PROTECT,
        related_name="loyalty_purchase_event",
        verbose_name="Ticket payé",
    )
    payment_method = models.CharField(
        "Moyen de paiement",
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.UNKNOWN,
    )
    bonus_ticket = models.OneToOneField(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loyalty_bonus_event",
        verbose_name="Ticket bonus",
    )
    client_celebrated_at = models.DateTimeField(
        "Cadeau annoncé au client le",
        null=True,
        blank=True,
        help_text="Renseigné quand l'animation de félicitations a été affichée au client.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "achat fidélité Wi-Fi"
        verbose_name_plural = "achats fidélité Wi-Fi"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source_ticket.code} — {self.progress.mac_address}"


# ══════════════════════════════════════════════════════════════════════════════
# PAIEMENT MOBILE MONEY (portail captif → CinetPay) — achat de tickets en ligne
# ══════════════════════════════════════════════════════════════════════════════
import uuid  # noqa: E402


class WifiZoneTarif(models.Model):
    """Grille tarifaire officielle (source de vérité serveur) des forfaits Wi-Fi Zone.

    Le portail captif affiche des prix, mais le serveur NE FAIT JAMAIS confiance
    au prix envoyé par le client : le montant réellement facturé est toujours
    relu ici, par site + durée. Un tarif « global » (site vide) sert de repli
    pour toutes les zones qui n'ont pas de tarif spécifique.
    """

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="wifi_zone_tarifs",
        null=True,
        blank=True,
        verbose_name="Site (vide = tarif global toutes zones)",
    )
    duration = models.CharField("Durée", max_length=8, choices=Ticket.Duration.choices, db_index=True)
    label = models.CharField(
        "Libellé commercial",
        max_length=64,
        blank=True,
        help_text="Ex. « Découverte », « Journée ». Facultatif.",
    )
    price_xof = models.DecimalField(
        "Prix (XOF)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
        help_text="Franc CFA BCEAO. Doit être un multiple de 5 (contrainte Mobile Money).",
    )
    is_active = models.BooleanField("Actif", default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tarif Wi-Fi Zone"
        verbose_name_plural = "tarifs Wi-Fi Zone"
        ordering = ["site_id", "price_xof"]
        constraints = [
            models.UniqueConstraint(
                fields=("site", "duration"),
                name="uniq_wifi_tarif_site_duration",
            ),
        ]

    def __str__(self) -> str:
        cible = self.site.site_id if self.site_id else "GLOBAL"
        return f"{cible} · {self.get_duration_display()} · {self.price_xof} XOF"

    @classmethod
    def resolve_price(cls, site, duration) -> "Decimal | None":
        """Prix officiel pour (site, durée). Spécifique au site sinon global. None si aucun."""
        site_id = getattr(site, "pk", site)
        specific = (
            cls.objects.filter(site_id=site_id, duration=duration, is_active=True)
            .values_list("price_xof", flat=True)
            .first()
        )
        if specific is not None:
            return specific
        return (
            cls.objects.filter(site__isnull=True, duration=duration, is_active=True)
            .values_list("price_xof", flat=True)
            .first()
        )


class WifiPurchase(models.Model):
    """Transaction d'achat d'un ticket Wi-Fi Zone payée en Mobile Money via CinetPay.

    Cycle de vie :
        PENDING  → transaction créée en base (avant appel CinetPay)
        AWAITING → guichet CinetPay ouvert, en attente du paiement du client
        SUCCESS  → paiement confirmé, ticket créé + poussé sur le MikroTik du site
        FAILED / CANCELLED / EXPIRED → paiement non abouti

    La confirmation est IDEMPOTENTE : le webhook CinetPay et la page de retour
    peuvent arriver plusieurs fois sans jamais créer deux tickets.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Créée"
        AWAITING = "awaiting", "En attente de paiement"
        SUCCESS = "success", "Payée"
        FAILED = "failed", "Échouée"
        CANCELLED = "cancelled", "Annulée"
        EXPIRED = "expired", "Expirée"

    class Provider(models.TextChoices):
        ORANGE_MONEY = "orange_money", "Orange Money"
        MOOV_MONEY = "moov_money", "Moov Money"
        WAVE = "wave", "Wave"
        TELECEL_MONEY = "telecel_money", "Telecel Money"
        CARD = "card", "Carte bancaire"
        UNKNOWN = "unknown", "Non précisé"

    reference = models.CharField(
        "Référence (transaction_id CinetPay)",
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="wifi_purchases",
        verbose_name="Site / zone",
    )
    duration = models.CharField("Durée", max_length=8, choices=Ticket.Duration.choices)
    amount_xof = models.DecimalField(
        "Montant (XOF)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    provider = models.CharField(
        "Moyen de paiement",
        max_length=20,
        choices=Provider.choices,
        default=Provider.UNKNOWN,
    )
    phone = models.CharField("Téléphone payeur", max_length=32, blank=True)
    mac_address = models.CharField("MAC du client", max_length=17, blank=True)
    client_ip = models.GenericIPAddressField("IP du client", null=True, blank=True)
    login_url = models.CharField(
        "URL de connexion hotspot",
        max_length=512,
        blank=True,
        help_text="$(link-login-only) transmis par le portail captif du routeur.",
    )
    destination_url = models.CharField("Destination d'origine", max_length=512, blank=True)

    status = models.CharField(
        "Statut",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    payment_token = models.CharField("Jeton CinetPay", max_length=128, blank=True)
    payment_url = models.URLField("Guichet de paiement CinetPay", max_length=512, blank=True)
    operator_id = models.CharField("Référence opérateur", max_length=128, blank=True)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wifi_purchase",
        verbose_name="Ticket délivré",
    )
    error_message = models.CharField("Dernier message d'erreur", max_length=512, blank=True)
    raw_init = models.TextField("Réponse init CinetPay (debug)", blank=True)
    raw_notify = models.TextField("Réponse check/notify CinetPay (debug)", blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField("Payée le", null=True, blank=True)

    class Meta:
        verbose_name = "achat Wi-Fi Zone (Mobile Money)"
        verbose_name_plural = "achats Wi-Fi Zone (Mobile Money)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference} — {self.get_status_display()} — {self.amount_xof} XOF"

    @staticmethod
    def generate_reference() -> str:
        """Identifiant unique alphanumérique accepté par CinetPay (≤ 64 car.)."""
        return "WZ" + uuid.uuid4().hex[:20].upper()

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self.generate_reference()
        super().save(*args, **kwargs)

    @property
    def is_final(self) -> bool:
        return self.status in {
            self.Status.SUCCESS,
            self.Status.FAILED,
            self.Status.CANCELLED,
            self.Status.EXPIRED,
        }
