from django.conf import settings
from django.db import models

from apps.core.models import NetworkDevice


class RouterAuditLog(models.Model):
    """Trace immuable de toutes les commandes envoyées aux routeurs, par tenant."""

    class Action(models.TextChoices):
        MAC_BLOCK = "mac_block", "Blocage MAC"
        MAC_UNBLOCK = "mac_unblock", "Déblocage MAC"
        HOTSPOT_PROVISION = "hotspot_provision", "Provisionnement hotspot"
        HOTSPOT_REMOVE = "hotspot_remove", "Suppression hotspot"
        FREQ_CHANGE = "freq_change", "Changement fréquence"
        PPPOE_CHECK = "pppoe_check", "Vérification PPPoE"
        OTHER = "other", "Autre"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="router_audit_logs",
        verbose_name="Organisation",
        null=True,
        blank=True,
    )
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="Équipement",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="router_audit_logs",
        verbose_name="Exécuté par",
    )
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    target = models.CharField("Cible (MAC, code ticket, …)", max_length=255, blank=True)
    command_sent = models.TextField("Commande envoyée", blank=True)
    success = models.BooleanField("Succès", default=True, db_index=True)
    error_message = models.TextField("Message d'erreur", blank=True)
    dry_run = models.BooleanField("Mode test", default=False)
    ip_address = models.GenericIPAddressField("IP client", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "audit routeur"
        verbose_name_plural = "audits routeur"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_action_display()} — {self.device} ({self.created_at:%d/%m/%Y %H:%M})"


class DeviceConfigChange(models.Model):
    """Journal des modifications de configuration appliquées à distance sur un équipement."""

    class ChangeType(models.TextChoices):
        FREQUENCY = "frequency", "Changement de fréquence"
        OTHER = "other", "Autre"

    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="config_changes",
        verbose_name="Équipement",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="device_config_changes",
        verbose_name="Effectué par",
    )
    change_type = models.CharField(
        max_length=32,
        choices=ChangeType.choices,
        default=ChangeType.FREQUENCY,
    )
    old_value = models.CharField("Ancienne valeur", max_length=128, blank=True)
    new_value = models.CharField("Nouvelle valeur", max_length=128, blank=True)
    success = models.BooleanField("Succès", default=True)
    message = models.TextField("Message", blank=True)
    dry_run = models.BooleanField("Mode test (dry-run)", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "modification de configuration"
        verbose_name_plural = "modifications de configuration"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.change_type} — {self.device} ({self.created_at:%d/%m/%Y %H:%M})"
