import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import PtPLink, Site


class CashJournalEntry(models.Model):
    """Journal de caisse : entrées vs dépenses (détail par écriture)."""

    class EntryType(models.TextChoices):
        INCOME = "income", "Entrée (recette)"
        EXPENSE = "expense", "Dépense (maintenance / autre)"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="cash_journal_entries",
        verbose_name="Organisation",
    )
    entry_type = models.CharField(max_length=16, choices=EntryType.choices, db_index=True)
    amount_xof = models.DecimalField(
        "Montant (XOF)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    description = models.CharField(max_length=255)
    category = models.CharField(
        "Catégorie",
        max_length=64,
        blank=True,
        help_text="Ex. carburant, main-d'œuvre, consommables, vente ticket…",
    )
    entry_date = models.DateField("Date comptable", db_index=True)
    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_entries",
        verbose_name="Site lié (optionnel)",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="cash_entries_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "écriture de caisse"
        verbose_name_plural = "journal de caisse"
        ordering = ["-entry_date", "-created_at"]

    def save(self, *args, **kwargs) -> None:
        from django.core.exceptions import ValidationError

        if self.site_id:
            self.tenant_id = Site.objects.values_list("tenant_id", flat=True).get(pk=self.site_id)
        elif self.created_by_id:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            tid = User.objects.values_list("tenant_id", flat=True).get(pk=self.created_by_id)
            if tid:
                self.tenant_id = tid
        if not self.tenant_id:
            raise ValidationError(
                {"tenant": "Impossible de déduire l'organisation : renseignez le site ou un créateur rattaché à une organisation."}
            )
        super().save(*args, **kwargs)


class CaisseDailyReport(models.Model):
    """
    Synthèse quotidienne de caisse : ventes Wi-Fi Zone vs abonnements Wi-Fi Simple.
    Les montants peuvent être saisis ou calculés par une tâche planifiée.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="caisse_daily_reports",
        verbose_name="Organisation",
    )
    report_date = models.DateField("Date", db_index=True)
    wifi_zone_gross_xof = models.DecimalField(
        "Brut tickets Zone (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        help_text="Total encaissements bruts tickets Wi-Fi Zone.",
    )
    wifi_zone_commissions_xof = models.DecimalField(
        "Commissions revendeurs (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
    )
    wifi_zone_net_isp_xof = models.DecimalField(
        "Net FAI après commissions Zone (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
    )
    wifi_simple_collected_xof = models.DecimalField(
        "Encaissements Wi-Fi Simple (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        help_text="Paiements abonnements mensuels du jour.",
    )
    other_income_xof = models.DecimalField(
        "Autres recettes (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
    )
    expenses_xof = models.DecimalField(
        "Dépenses du jour (XOF)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
    )
    notes = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="caisse_reports_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "rapport de caisse quotidien"
        verbose_name_plural = "rapports de caisse quotidiens"
        ordering = ["-report_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "report_date"],
                name="finance_caissedailyreport_tenant_report_date_uniq",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        from django.core.exceptions import ValidationError

        if not self.tenant_id and self.closed_by_id:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            tid = User.objects.filter(pk=self.closed_by_id).values_list("tenant_id", flat=True).first()
            if tid:
                self.tenant_id = tid
        if not self.tenant_id:
            raise ValidationError(
                {"tenant": "Organisation obligatoire pour un rapport de caisse. Renseignez l'organisation ou désignez un responsable de clôture rattaché à une organisation."}
            )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Caisse {self.report_date}"

    @property
    def net_cash_position_xof(self) -> Decimal:
        gross_in = (
            self.wifi_zone_net_isp_xof
            + self.wifi_simple_collected_xof
            + self.other_income_xof
        )
        return gross_in - self.expenses_xof


class MaintenanceTicket(models.Model):
    """Ticket de panne terrain ; peut être lié à une liaison PtP défectueuse."""

    class Priority(models.TextChoices):
        LOW = "low", "Basse"
        MEDIUM = "medium", "Moyenne"
        HIGH = "high", "Haute"

    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        ASSIGNED = "assigned", "Assigné"
        IN_PROGRESS = "in_progress", "En cours"
        RESOLVED = "resolved", "Résolu"
        CLOSED = "closed", "Fermé"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="maintenance_tickets",
        verbose_name="Organisation",
    )
    reference = models.CharField(max_length=32, db_index=True, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="maintenance_tickets",
    )
    faulty_link = models.ForeignKey(
        PtPLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_tickets",
        verbose_name="Liaison PtP défectueuse",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_tickets",
    )
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "ticket d'intervention"
        verbose_name_plural = "tickets d'intervention"
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "reference"],
                name="finance_maintenanceticket_tenant_reference_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.title}"

    def save(self, *args, **kwargs):
        if self.site_id:
            self.tenant_id = Site.objects.values_list("tenant_id", flat=True).get(pk=self.site_id)
        if not self.reference:
            for _ in range(32):
                candidate = f"PANNE-{secrets.token_hex(4).upper()}"
                qs = MaintenanceTicket.objects.filter(reference=candidate)
                if self.tenant_id:
                    qs = qs.filter(tenant_id=self.tenant_id)
                if not qs.exists():
                    self.reference = candidate
                    break
            else:  # pragma: no cover
                raise RuntimeError("Impossible de générer une référence unique.")
        super().save(*args, **kwargs)


class RevendeurDailyReport(models.Model):
    """Rapport journalier automatique par revendeur — basé sur le préfixe ticket."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="revendeur_daily_reports",
        verbose_name="Organisation",
    )
    revendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="daily_reports",
        verbose_name="Revendeur",
    )
    report_date = models.DateField("Date", db_index=True)
    prefix = models.CharField("Préfixe utilisé", max_length=10, blank=True)
    tickets_sold_count = models.PositiveIntegerField("Tickets vendus", default=0)
    tickets_used_count = models.PositiveIntegerField("Tickets utilisés", default=0)
    gross_xof = models.DecimalField(
        "Montant brut (XOF)", max_digits=14, decimal_places=0, default=Decimal("0")
    )
    commission_xof = models.DecimalField(
        "Commissions (XOF)", max_digits=14, decimal_places=0, default=Decimal("0")
    )
    net_isp_xof = models.DecimalField(
        "Net FAI (XOF)", max_digits=14, decimal_places=0, default=Decimal("0")
    )
    generated_at = models.DateTimeField("Généré le", auto_now=True)
    detail_json = models.JSONField("Détail tickets", default=list)

    class Meta:
        verbose_name = "rapport journalier revendeur"
        verbose_name_plural = "rapports journaliers revendeurs"
        ordering = ["-report_date", "revendeur"]
        constraints = [
            models.UniqueConstraint(
                fields=["revendeur", "report_date"],
                name="finance_revendeurreport_revendeur_date_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"Rapport {self.report_date} — {self.revendeur}"

    @property
    def net_cash_xof(self) -> Decimal:
        return self.gross_xof - self.commission_xof
