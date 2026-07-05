from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0007_site_tenant"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceConfigChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="config_changes",
                        to="core.networkdevice",
                        verbose_name="Équipement",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="device_config_changes",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Effectué par",
                    ),
                ),
                (
                    "change_type",
                    models.CharField(
                        choices=[("frequency", "Changement de fréquence"), ("other", "Autre")],
                        default="frequency",
                        max_length=32,
                    ),
                ),
                ("old_value", models.CharField(blank=True, max_length=128, verbose_name="Ancienne valeur")),
                ("new_value", models.CharField(blank=True, max_length=128, verbose_name="Nouvelle valeur")),
                ("success", models.BooleanField(default=True, verbose_name="Succès")),
                ("message", models.TextField(blank=True, verbose_name="Message")),
                ("dry_run", models.BooleanField(default=False, verbose_name="Mode test (dry-run)")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "modification de configuration",
                "verbose_name_plural": "modifications de configuration",
                "ordering": ["-created_at"],
            },
        ),
    ]
