from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0001_initial"),
        ("tenants", "0001_initial"),
        ("core", "0007_site_tenant"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RouterAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="router_audit_logs",
                        to="tenants.tenant",
                        verbose_name="Organisation",
                    ),
                ),
                (
                    "device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to="core.networkdevice",
                        verbose_name="Équipement",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="router_audit_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Exécuté par",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("mac_block", "Blocage MAC"),
                            ("mac_unblock", "Déblocage MAC"),
                            ("hotspot_provision", "Provisionnement hotspot"),
                            ("hotspot_remove", "Suppression hotspot"),
                            ("freq_change", "Changement fréquence"),
                            ("pppoe_check", "Vérification PPPoE"),
                            ("other", "Autre"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("target", models.CharField(blank=True, max_length=255, verbose_name="Cible (MAC, code ticket, …)")),
                ("command_sent", models.TextField(blank=True, verbose_name="Commande envoyée")),
                ("success", models.BooleanField(db_index=True, default=True, verbose_name="Succès")),
                ("error_message", models.TextField(blank=True, verbose_name="Message d'erreur")),
                ("dry_run", models.BooleanField(default=False, verbose_name="Mode test")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP client")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "audit routeur",
                "verbose_name_plural": "audits routeur",
                "ordering": ["-created_at"],
            },
        ),
    ]
