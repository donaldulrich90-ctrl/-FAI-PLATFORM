from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_user_ticket_prefix_and_more"),
        ("core", "0009_alter_networkdevice_password_hint"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="site",
            field=models.ForeignKey(
                blank=True,
                help_text="Site principal du revendeur (pour la génération de tickets).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revendeur_users",
                to="core.site",
                verbose_name="Site rattaché",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="balance_xof",
            field=models.DecimalField(
                decimal_places=0,
                default=Decimal("0"),
                help_text="Solde actuel du revendeur en Francs CFA.",
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Solde (XOF)",
            ),
        ),
    ]
