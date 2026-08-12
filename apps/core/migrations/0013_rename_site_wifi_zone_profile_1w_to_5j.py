"""
Migration : renommage du champ Site.wifi_zone_profile_1w → wifi_zone_profile_5j.

On utilise RenameField (et non Remove+Add) pour préserver les valeurs existantes.
L'AlterField qui suit met à jour le verbose_name et le help_text.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_networkdevice_aireos_prompt"),
    ]

    operations = [
        migrations.RenameField(
            model_name="site",
            old_name="wifi_zone_profile_1w",
            new_name="wifi_zone_profile_5j",
        ),
        migrations.AlterField(
            model_name="site",
            name="wifi_zone_profile_5j",
            field=models.CharField(
                blank=True,
                help_text="Profil pour les tickets 5 jours. Vide = défaut global.",
                max_length=64,
                verbose_name="Profil hotspot — 5 jours",
            ),
        ),
    ]
