import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


DEFAULT_TARIFS = [
    # (durée, libellé, prix XOF)  — alignés sur le portail captif (login.html)
    ("3h", "Découverte", 100),
    ("1d", "Journée", 200),
    ("5j", "Séjour", 500),
    ("1w", "Semaine", 700),
    ("30j", "Mensuel", 2500),
]


def seed_default_tarifs(apps, schema_editor):
    WifiZoneTarif = apps.get_model("wifi_zone", "WifiZoneTarif")
    for duration, label, price in DEFAULT_TARIFS:
        WifiZoneTarif.objects.get_or_create(
            site=None,
            duration=duration,
            defaults={"label": label, "price_xof": price, "is_active": True},
        )


def remove_default_tarifs(apps, schema_editor):
    WifiZoneTarif = apps.get_model("wifi_zone", "WifiZoneTarif")
    WifiZoneTarif.objects.filter(site__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("wifi_zone", "0015_loyalty_bonus"),
    ]

    operations = [
        migrations.CreateModel(
            name="WifiZoneTarif",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("duration", models.CharField(choices=[("2h", "2 heures"), ("3h", "3 heures"), ("4h", "4 heures"), ("1d", "24 heures (1 jour)"), ("5j", "5 jours"), ("1w", "7 jours"), ("30j", "30 jours"), ("illimite", "Illimité")], db_index=True, max_length=8, verbose_name="Durée")),
                ("label", models.CharField(blank=True, help_text="Ex. « Découverte », « Journée ». Facultatif.", max_length=64, verbose_name="Libellé commercial")),
                ("price_xof", models.DecimalField(decimal_places=0, help_text="Franc CFA BCEAO. Doit être un multiple de 5 (contrainte Mobile Money).", max_digits=12, validators=[django.core.validators.MinValueValidator(0)], verbose_name="Prix (XOF)")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Actif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("site", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="wifi_zone_tarifs", to="core.site", verbose_name="Site (vide = tarif global toutes zones)")),
            ],
            options={
                "verbose_name": "tarif Wi-Fi Zone",
                "verbose_name_plural": "tarifs Wi-Fi Zone",
                "ordering": ["site_id", "price_xof"],
            },
        ),
        migrations.AddConstraint(
            model_name="wifizonetarif",
            constraint=models.UniqueConstraint(fields=("site", "duration"), name="uniq_wifi_tarif_site_duration"),
        ),
        migrations.CreateModel(
            name="WifiPurchase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(db_index=True, editable=False, max_length=64, unique=True, verbose_name="Référence (transaction_id CinetPay)")),
                ("duration", models.CharField(choices=[("2h", "2 heures"), ("3h", "3 heures"), ("4h", "4 heures"), ("1d", "24 heures (1 jour)"), ("5j", "5 jours"), ("1w", "7 jours"), ("30j", "30 jours"), ("illimite", "Illimité")], max_length=8, verbose_name="Durée")),
                ("amount_xof", models.DecimalField(decimal_places=0, max_digits=12, validators=[django.core.validators.MinValueValidator(0)], verbose_name="Montant (XOF)")),
                ("provider", models.CharField(choices=[("orange_money", "Orange Money"), ("moov_money", "Moov Money"), ("wave", "Wave"), ("telecel_money", "Telecel Money"), ("card", "Carte bancaire"), ("unknown", "Non précisé")], default="unknown", max_length=20, verbose_name="Moyen de paiement")),
                ("phone", models.CharField(blank=True, max_length=32, verbose_name="Téléphone payeur")),
                ("mac_address", models.CharField(blank=True, max_length=17, verbose_name="MAC du client")),
                ("client_ip", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP du client")),
                ("login_url", models.CharField(blank=True, help_text="$(link-login-only) transmis par le portail captif du routeur.", max_length=512, verbose_name="URL de connexion hotspot")),
                ("destination_url", models.CharField(blank=True, max_length=512, verbose_name="Destination d'origine")),
                ("status", models.CharField(choices=[("pending", "Créée"), ("awaiting", "En attente de paiement"), ("success", "Payée"), ("failed", "Échouée"), ("cancelled", "Annulée"), ("expired", "Expirée")], db_index=True, default="pending", max_length=16, verbose_name="Statut")),
                ("payment_token", models.CharField(blank=True, max_length=128, verbose_name="Jeton CinetPay")),
                ("payment_url", models.URLField(blank=True, max_length=512, verbose_name="Guichet de paiement CinetPay")),
                ("operator_id", models.CharField(blank=True, max_length=128, verbose_name="Référence opérateur")),
                ("error_message", models.CharField(blank=True, max_length=512, verbose_name="Dernier message d'erreur")),
                ("raw_init", models.TextField(blank=True, verbose_name="Réponse init CinetPay (debug)")),
                ("raw_notify", models.TextField(blank=True, verbose_name="Réponse check/notify CinetPay (debug)")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True, verbose_name="Payée le")),
                ("site", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="wifi_purchases", to="core.site", verbose_name="Site / zone")),
                ("ticket", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="wifi_purchase", to="wifi_zone.ticket", verbose_name="Ticket délivré")),
            ],
            options={
                "verbose_name": "achat Wi-Fi Zone (Mobile Money)",
                "verbose_name_plural": "achats Wi-Fi Zone (Mobile Money)",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(seed_default_tarifs, remove_default_tarifs),
    ]
