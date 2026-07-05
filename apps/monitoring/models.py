from django.conf import settings
from django.db import models

from apps.core.models import NetworkDevice


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
