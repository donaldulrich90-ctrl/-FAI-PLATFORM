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
        HOTSPOT_DISCONNECT = "hotspot_disconnect", "Déconnexion session active"
        HOTSPOT_BATCH = "hotspot_batch", "Génération lot tickets"
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


class FrequenceConfig(models.Model):
    """Configuration de gestion automatique des fréquences pour une antenne Ubiquiti."""

    device = models.OneToOneField(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="frequence_config",
        verbose_name="Antenne",
    )
    freq_principale = models.IntegerField("Fréquence principale (MHz)", default=5180)
    freq_secours_1 = models.IntegerField("Fréquence secours 1 (MHz)", null=True, blank=True)
    freq_secours_2 = models.IntegerField("Fréquence secours 2 (MHz)", null=True, blank=True)
    freq_secours_3 = models.IntegerField("Fréquence secours 3 (MHz)", null=True, blank=True)
    seuil_snr_min = models.IntegerField("Seuil SNR minimum (dB)", default=15)
    seuil_signal_min = models.IntegerField("Seuil signal minimum (dBm)", default=-75)
    seuil_capacite_min = models.IntegerField("Seuil capacité minimum (%)", default=40)
    auto_switch = models.BooleanField("Basculement automatique", default=True)
    derniere_modif = models.DateTimeField("Dernière modification", null=True, blank=True)
    historique_json = models.JSONField("Historique JSON", default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuration fréquence"
        verbose_name_plural = "configurations fréquences"

    def __str__(self) -> str:
        return f"FreqConfig — {self.device.name} ({self.freq_principale} MHz)"

    def get_backup_frequencies(self) -> list[int]:
        return [f for f in [self.freq_secours_1, self.freq_secours_2, self.freq_secours_3] if f]


class HistoriqueFrequence(models.Model):
    """Trace de chaque changement de fréquence — automatique ou manuel."""

    class Raison(models.TextChoices):
        SNR_FAIBLE = "snr_faible", "SNR insuffisant"
        INTERFERENCE = "interference", "Interférence détectée"
        MANUEL = "manuel", "Action manuelle"
        SECOURS = "secours", "Basculement secours"

    class Declencheur(models.TextChoices):
        AUTO = "auto", "Automatique"
        MANUEL = "manuel", "Manuel"
        URGENCE = "urgence", "Urgence"

    class Resultat(models.TextChoices):
        AMELIORE = "ameliore", "Amélioré"
        DEGRADE = "degrade", "Dégradé"
        NEUTRE = "neutre", "Neutre"

    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="historique_frequences",
        verbose_name="Antenne",
    )
    freq_avant = models.IntegerField("Fréquence avant (MHz)")
    freq_apres = models.IntegerField("Fréquence après (MHz)")
    raison = models.CharField(max_length=20, choices=Raison.choices, default=Raison.SNR_FAIBLE)
    snr_avant = models.FloatField("SNR avant (dB)", null=True, blank=True)
    signal_avant = models.FloatField("Signal avant (dBm)", null=True, blank=True)
    declencheur = models.CharField(max_length=10, choices=Declencheur.choices, default=Declencheur.AUTO)
    resultat = models.CharField(max_length=10, choices=Resultat.choices, default=Resultat.NEUTRE)
    dry_run = models.BooleanField("Mode test", default=False)
    notes = models.TextField("Notes", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "historique fréquence"
        verbose_name_plural = "historiques fréquences"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.device.name}: {self.freq_avant}→{self.freq_apres} MHz ({self.created_at:%d/%m %H:%M})"
