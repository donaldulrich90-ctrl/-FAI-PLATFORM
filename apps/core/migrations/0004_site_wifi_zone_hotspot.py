import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_networkdevice_mikrotik_bridge_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="wifi_zone_hotspot_device",
            field=models.ForeignKey(
                blank=True,
                help_text="MikroTik sur lequel créer les utilisateurs /ip hotspot user pour les tickets. "
                "Vide : premier équipement MikroTik actif du site.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sites_as_wifi_zone_hotspot",
                to="core.networkdevice",
                verbose_name="Routeur Hotspot Wi‑Fi Zone",
            ),
        ),
        migrations.AddField(
            model_name="site",
            name="wifi_zone_hotspot_profile",
            field=models.CharField(
                blank=True,
                help_text="Nom du profil /ip hotspot user profile (ex. default). "
                "Vide : MIKROTIK_HOTSPOT_DEFAULT_PROFILE.",
                max_length=64,
                verbose_name="Profil Hotspot RouterOS",
            ),
        ),
    ]
