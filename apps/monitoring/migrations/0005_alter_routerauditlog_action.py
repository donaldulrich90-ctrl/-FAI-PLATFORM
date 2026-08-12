from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0004_frequence_config_historique"),
    ]

    operations = [
        migrations.AlterField(
            model_name="routerauditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("mac_block", "Blocage MAC"),
                    ("mac_unblock", "Déblocage MAC"),
                    ("hotspot_provision", "Provisionnement hotspot"),
                    ("hotspot_remove", "Suppression hotspot"),
                    ("hotspot_disconnect", "Déconnexion session active"),
                    ("hotspot_batch", "Génération lot tickets"),
                    ("ip_binding", "IP Binding hotspot"),
                    ("freq_change", "Changement fréquence"),
                    ("pppoe_check", "Vérification PPPoE"),
                    ("other", "Autre"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
