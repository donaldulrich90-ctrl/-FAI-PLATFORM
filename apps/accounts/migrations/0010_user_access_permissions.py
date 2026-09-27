"""Ajout des champs de permissions d'accès par section."""

from django.db import migrations, models


def set_defaults_from_role(apps, schema_editor):
    """Attribue les accès par défaut selon le rôle existant."""
    User = apps.get_model("accounts", "User")
    
    # Admins : tout activé
    User.objects.filter(role="admin").update(
        access_monitoring=True,
        access_abonnes=True,
        access_wifi=True,
        access_revendeur=True,
        access_finance=True,
        access_admin=True,
    )
    # Superusers : tout activé
    User.objects.filter(is_superuser=True).update(
        access_monitoring=True,
        access_abonnes=True,
        access_wifi=True,
        access_revendeur=True,
        access_finance=True,
        access_admin=True,
    )
    # Techniciens : monitoring + abonnés
    User.objects.filter(role="technician").update(
        access_monitoring=True,
        access_abonnes=True,
    )
    # Revendeurs : wifi + revendeur
    User.objects.filter(role="revendeur").update(
        access_wifi=True,
        access_revendeur=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_user_type_revendeur"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="access_monitoring",
            field=models.BooleanField(
                default=False,
                help_text="Tableau de bord, Interventions, Antennes Ubiquiti, Simulation réseau, Clients connectés.",
                verbose_name="Accès Monitoring",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="access_abonnes",
            field=models.BooleanField(
                default=False,
                help_text="Abonnés Domicile, Tickets Support.",
                verbose_name="Accès Abonnés Domicile",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="access_wifi",
            field=models.BooleanField(
                default=False,
                help_text="Tickets imprimés, Vérifier ticket, Revendeurs, WiFi Zones, Générer tickets.",
                verbose_name="Accès Ventes Wi-Fi",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="access_revendeur",
            field=models.BooleanField(
                default=False,
                help_text="Espace Revendeur, Point de vente, Rapports Journaliers.",
                verbose_name="Accès Espace Revendeur",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="access_finance",
            field=models.BooleanField(
                default=False,
                help_text="Dashboard Finance, Export Caisse (CSV).",
                verbose_name="Accès Finance",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="access_admin",
            field=models.BooleanField(
                default=False,
                help_text="Admin Django, Gestion Utilisateurs, Organisations.",
                verbose_name="Accès Administration",
            ),
        ),
        migrations.RunPython(set_defaults_from_role, migrations.RunPython.noop),
    ]
