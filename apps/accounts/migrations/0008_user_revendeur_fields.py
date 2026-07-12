from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_user_site_balance"),
        ("core", "0009_alter_networkdevice_password_hint"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mac_antenne",
            field=models.CharField(
                blank=True,
                help_text="Format AA:BB:CC:DD:EE:FF — utilisé pour l'ip-binding hotspot.",
                max_length=17,
                verbose_name="MAC antenne (CPE revendeur)",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="mikrotik",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"is_active": True, "vendor": "mikrotik"},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revendeurs_connectes",
                to="core.networkdevice",
                verbose_name="MikroTik revendeur",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="date_expiration",
            field=models.DateField(blank=True, null=True, verbose_name="Date d'expiration abonnement"),
        ),
        migrations.AddField(
            model_name="user",
            name="statut_revendeur",
            field=models.CharField(
                blank=True,
                choices=[("actif", "Actif"), ("suspendu", "Suspendu"), ("expire", "Expiré")],
                default="",
                max_length=16,
                verbose_name="Statut revendeur",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="montant_abonnement_xof",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Montant abonnement (XOF/mois)",
            ),
        ),
    ]
