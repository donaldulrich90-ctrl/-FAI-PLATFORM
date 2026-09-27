from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("tenants", "0001_initial"),
        ("wifi_zone", "0014_ticketconsommation"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoyaltyProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mac_address", models.CharField(db_index=True, max_length=17, verbose_name="MAC du client")),
                ("duration", models.CharField(choices=[("2h", "2 heures"), ("3h", "3 heures"), ("4h", "4 heures"), ("1d", "24 heures (1 jour)"), ("5j", "5 jours"), ("1w", "7 jours"), ("30j", "30 jours"), ("illimite", "Illimité")], max_length=8, verbose_name="Durée")),
                ("plan_price_xof", models.DecimalField(decimal_places=0, default=Decimal("0"), max_digits=12, verbose_name="Prix du forfait (XOF)")),
                ("paid_count", models.PositiveSmallIntegerField(default=0, verbose_name="Progression (0 à 4)")),
                ("bonus_count", models.PositiveIntegerField(default=0, verbose_name="Bonus attribués")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("site", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="wifi_loyalty_progress", to="core.site", verbose_name="Site")),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="wifi_loyalty_progress", to="tenants.tenant", verbose_name="Organisation")),
            ],
            options={
                "verbose_name": "progression fidélité Wi-Fi",
                "verbose_name_plural": "progressions fidélité Wi-Fi",
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="LoyaltyPurchaseEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment_method", models.CharField(choices=[("cash", "Espèces"), ("mobile_money", "Mobile Money"), ("unknown", "Non précisé")], default="unknown", max_length=20, verbose_name="Moyen de paiement")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("bonus_ticket", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="loyalty_bonus_event", to="wifi_zone.ticket", verbose_name="Ticket bonus")),
                ("progress", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_events", to="wifi_zone.loyaltyprogress", verbose_name="Progression")),
                ("source_ticket", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="loyalty_purchase_event", to="wifi_zone.ticket", verbose_name="Ticket payé")),
            ],
            options={
                "verbose_name": "achat fidélité Wi-Fi",
                "verbose_name_plural": "achats fidélité Wi-Fi",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="loyaltyprogress",
            constraint=models.UniqueConstraint(fields=("site", "mac_address", "duration", "plan_price_xof"), name="uniq_loyalty_device_plan"),
        ),
    ]
