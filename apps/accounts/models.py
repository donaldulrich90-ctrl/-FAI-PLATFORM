from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class User(AbstractUser):
    """Utilisateur avec rôles : Admin, Technicien, Revendeur."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrateur"
        TECHNICIAN = "technician", "Technicien"
        REVENDEUR = "revendeur", "Revendeur"

    class RevendeurStatut(models.TextChoices):
        ACTIF = "actif", "Actif"
        SUSPENDU = "suspendu", "Suspendu"
        EXPIRE = "expire", "Expiré"

    class TypeRevendeur(models.TextChoices):
        AUTONOME = "autonome", "Autonome"
        PARTENAIRE = "partenaire", "Partenaire"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.TECHNICIAN,
        db_index=True,
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Organisation",
        help_text="Vide pour les super-utilisateurs plateforme ; obligatoire pour le personnel d’un FAI.",
    )
    is_platform_operator = models.BooleanField(
        "Gestionnaire plateforme (SaaS)",
        default=False,
        help_text="Peut créer les organisations (locataires) et voir toutes les données dans l’admin. "
        "Laisser « Organisation » vide pour ce compte. Réservé au personnel de l’éditeur, pas aux FAI clients.",
    )
    phone = models.CharField("Téléphone", max_length=32, blank=True)
    default_commission_percent = models.DecimalField(
        "Commission par défaut (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Taux appliqué aux ventes de tickets Wi-Fi Zone (ex. 10%).",
    )
    ticket_prefix = models.CharField(
        "Préfixe tickets",
        max_length=10,
        blank=True,
        db_index=True,
        help_text="Préfixe unique assigné à ce revendeur (ex. KONE, REV01). "
        "Lettres majuscules et chiffres uniquement, 2 à 10 caractères. "
        "Les codes générés auront la forme PREFIX-XXXXXXXX.",
    )
    site = models.ForeignKey(
        "core.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revendeur_users",
        verbose_name="Site rattaché",
        help_text="Site principal du revendeur (pour la génération de tickets).",
    )
    balance_xof = models.DecimalField(
        "Solde (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Solde actuel du revendeur en Francs CFA.",
    )

    # ── Champs abonnement revendeur ───────────────────────────────────────────
    mac_antenne = models.CharField(
        "MAC antenne (CPE revendeur)",
        max_length=17,
        blank=True,
        help_text="Format AA:BB:CC:DD:EE:FF — utilisé pour l'ip-binding hotspot.",
    )
    mikrotik = models.ForeignKey(
        "core.NetworkDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revendeurs_connectes",
        verbose_name="MikroTik revendeur",
        limit_choices_to={"vendor": "mikrotik", "is_active": True},
    )
    date_expiration = models.DateField(
        "Date d'expiration abonnement",
        null=True,
        blank=True,
    )
    statut_revendeur = models.CharField(
        "Statut revendeur",
        max_length=16,
        choices=RevendeurStatut.choices,
        blank=True,
        default="",
    )
    montant_abonnement_xof = models.DecimalField(
        "Montant abonnement (XOF/mois)",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    type_revendeur = models.CharField(
        "Type de revendeur",
        max_length=16,
        choices=TypeRevendeur.choices,
        default=TypeRevendeur.AUTONOME,
        blank=True,
        help_text="AUTONOME : peut générer ses propres tickets. PARTENAIRE : accès lecture seule à ses ventes.",
    )


    # ── Permissions d'accès par section ───────────────────────
    access_monitoring = models.BooleanField(
        "Accès Monitoring",
        default=False,
        help_text="Tableau de bord, Interventions, Antennes Ubiquiti, Simulation réseau, Clients connectés.",
    )
    access_abonnes = models.BooleanField(
        "Accès Abonnés Domicile",
        default=False,
        help_text="Abonnés Domicile, Tickets Support.",
    )
    access_wifi = models.BooleanField(
        "Accès Ventes Wi-Fi",
        default=False,
        help_text="Tickets imprimés, Vérifier ticket, Revendeurs, WiFi Zones, Générer tickets.",
    )
    access_revendeur = models.BooleanField(
        "Accès Espace Revendeur",
        default=False,
        help_text="Espace Revendeur, Point de vente, Rapports Journaliers.",
    )
    access_finance = models.BooleanField(
        "Accès Finance",
        default=False,
        help_text="Dashboard Finance, Export Caisse (CSV).",
    )
    access_admin = models.BooleanField(
        "Accès Administration",
        default=False,
        help_text="Admin Django, Gestion Utilisateurs, Organisations.",
    )

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        constraints = [
            models.UniqueConstraint(
                fields=["ticket_prefix"],
                condition=models.Q(ticket_prefix__gt=""),
                name="accounts_user_ticket_prefix_uniq",
            ),
        ]

    def clean(self) -> None:
        import re
        super().clean()
        if self.ticket_prefix:
            self.ticket_prefix = self.ticket_prefix.upper().strip()
            if not re.match(r"^[A-Z0-9]{2,10}$", self.ticket_prefix):
                raise ValidationError(
                    {"ticket_prefix": "Le préfixe doit contenir 2 à 10 caractères : lettres majuscules et chiffres uniquement."}
                )
        if self.is_platform_operator:
            if self.tenant_id:
                raise ValidationError(
                    {"tenant": "Un gestionnaire plateforme ne doit pas être rattaché à une organisation."}
                )
            if not self.is_staff:
                raise ValidationError(
                    {"is_staff": "Cochez « Statut équipe » pour qu’un gestionnaire plateforme accède à l’admin."}
                )
        elif (
            self.is_staff
            and not self.is_superuser
            and not self.tenant_id
        ):
            raise ValidationError(
                {"tenant": "Renseignez l’organisation pour ce compte équipe (sauf super-utilisateur)."}
            )

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_technician(self) -> bool:
        return self.role == self.Role.TECHNICIAN or self.is_admin_role

    @property
    def is_revendeur(self) -> bool:
        return self.role == self.Role.REVENDEUR

    @property
    def is_revendeur_autonome(self) -> bool:
        return self.is_revendeur and self.type_revendeur == self.TypeRevendeur.AUTONOME

    @property
    def is_revendeur_partenaire(self) -> bool:
        return self.is_revendeur and self.type_revendeur == self.TypeRevendeur.PARTENAIRE

    def can_access_monitoring(self) -> bool:
        if self.is_admin_role:
            return True
        return self.access_monitoring

    def can_access_abonnes(self) -> bool:
        if self.is_admin_role:
            return True
        return self.access_abonnes

    def can_access_wifi(self) -> bool:
        if self.is_admin_role:
            return True
        return self.access_wifi

    def can_access_revendeur(self) -> bool:
        if self.is_admin_role:
            return True
        if self.is_revendeur:
            return True
        return self.access_revendeur

    def can_access_finance(self) -> bool:
        if self.is_admin_role:
            return True
        return self.access_finance

    def can_access_admin(self) -> bool:
        if self.is_admin_role:
            return True
        return self.access_admin

    def can_sell_wifi_zone(self) -> bool:
        return self.is_revendeur or self.is_admin_role or self.access_wifi
