from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_site_wifi_zone_profiles_2h_4h"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[
                    ("login", "Connexion"),
                    ("logout", "Déconnexion"),
                    ("user_create", "Création utilisateur"),
                    ("user_edit", "Modification utilisateur"),
                    ("user_delete", "Suppression utilisateur"),
                    ("user_toggle", "Activation/Désactivation"),
                    ("ticket_generate", "Génération tickets"),
                    ("ticket_sell", "Vente ticket"),
                    ("ticket_activate", "Activation ticket"),
                    ("abonne_create", "Création abonné"),
                    ("abonne_edit", "Modification abonné"),
                    ("settings_change", "Modification paramètres"),
                    ("other", "Autre"),
                ], max_length=30, verbose_name="Action")),
                ("detail", models.TextField(blank=True, verbose_name="Détail")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="Adresse IP")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Date")),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="activity_logs",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="Utilisateur",
                )),
            ],
            options={
                "verbose_name": "log d'activité",
                "verbose_name_plural": "logs d'activité",
                "ordering": ["-created_at"],
            },
        ),
    ]
