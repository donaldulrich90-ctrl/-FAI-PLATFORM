"""
Migration : ajout des champs Site.wifi_zone_profile_1w et Site.wifi_zone_profile_illimite.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_rename_site_wifi_zone_profile_1w_to_5j"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="wifi_zone_profile_1w",
            field=models.CharField(
                blank=True,
                help_text="Profil pour les tickets 7 jours. Vide = défaut global.",
                max_length=64,
                verbose_name="Profil hotspot — 7 jours",
            ),
        ),
        migrations.AddField(
            model_name="site",
            name="wifi_zone_profile_illimite",
            field=models.CharField(
                blank=True,
                help_text="Profil pour les tickets Illimité. Vide = défaut global.",
                max_length=64,
                verbose_name="Profil hotspot — Illimité",
            ),
        ),
    ]
