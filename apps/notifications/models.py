from django.db import models


class WhatsAppLog(models.Model):
    """Journal de chaque message WhatsApp envoyé via CallMeBot."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_logs",
    )
    phone = models.CharField("Destinataire", max_length=32)
    message = models.TextField("Message")
    success = models.BooleanField("Envoyé", default=False)
    error_message = models.CharField("Erreur", max_length=512, blank=True)
    dry_run = models.BooleanField("Mode test", default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "log WhatsApp"
        verbose_name_plural = "logs WhatsApp"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        status = "OK" if self.success else "ERREUR"
        return f"[{status}] {self.phone} — {self.created_at:%Y-%m-%d %H:%M}"
