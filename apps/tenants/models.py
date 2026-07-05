from django.db import models


class Tenant(models.Model):
    """Locataire SaaS (ex. un FAI) : isole les sites, utilisateurs et données financières."""

    name = models.CharField("Nom de l'organisation", max_length=128)
    slug = models.SlugField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Identifiant technique unique (URL, API). Ex. mon-fai.",
    )
    is_active = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "organisation"
        verbose_name_plural = "organisations"

    def __str__(self) -> str:
        return self.name
