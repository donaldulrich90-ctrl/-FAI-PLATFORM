from django.conf import settings
from django.db import models


class Simulation(models.Model):
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="simulations",
        verbose_name="Organisation",
    )
    name = models.CharField("Nom", max_length=128)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="simulations",
        verbose_name="Créé par",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    center_lat = models.FloatField("Latitude centre", null=True, blank=True)
    center_lng = models.FloatField("Longitude centre", null=True, blank=True)
    zoom = models.FloatField("Zoom initial", default=14.0)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "simulation"
        verbose_name_plural = "simulations"

    def __str__(self) -> str:
        return self.name


class SimulationElement(models.Model):
    class ElementType(models.TextChoices):
        ANTENNA = "antenna", "Antenne"
        CPE = "cpe", "CPE client"
        RELAY = "relay", "Relais"
        TOWER = "tower", "Tour/mât"

    simulation = models.ForeignKey(
        Simulation,
        on_delete=models.CASCADE,
        related_name="elements",
    )
    element_type = models.CharField(
        max_length=16,
        choices=ElementType.choices,
        db_index=True,
    )
    label = models.CharField("Libellé", max_length=64, blank=True)
    lat = models.FloatField("Latitude")
    lng = models.FloatField("Longitude")
    config = models.JSONField("Configuration", default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "élément de simulation"
        verbose_name_plural = "éléments de simulation"

    def __str__(self) -> str:
        return f"{self.get_element_type_display()} — {self.label or self.pk}"


class SimulationLink(models.Model):
    class LinkType(models.TextChoices):
        PTMP = "ptmp", "Point-à-multipoint"
        PTP = "ptp", "Point-à-point"

    simulation = models.ForeignKey(
        Simulation,
        on_delete=models.CASCADE,
        related_name="links",
    )
    element_a = models.ForeignKey(
        SimulationElement,
        on_delete=models.CASCADE,
        related_name="links_as_a",
    )
    element_b = models.ForeignKey(
        SimulationElement,
        on_delete=models.CASCADE,
        related_name="links_as_b",
    )
    link_type = models.CharField(max_length=8, choices=LinkType.choices, default=LinkType.PTMP)
    config = models.JSONField("Paramètres", default=dict)
    result = models.JSONField("Résultat calculé", default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "lien de simulation"
        verbose_name_plural = "liens de simulation"

    def __str__(self) -> str:
        return f"{self.get_link_type_display()} : {self.element_a_id} ↔ {self.element_b_id}"
