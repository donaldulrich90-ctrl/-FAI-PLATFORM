"""
Ajout du champ encrypted_password sur NetworkDevice + correction default api_port (443→8728).

Les enregistrements existants gardent encrypted_password vide (les credentials
sont déjà référencés via password_hint=env:VAR). Les opérateurs peuvent
définir un mot de passe chiffré via l'interface d'admin (champ "Définir le mot de passe").
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_site_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="networkdevice",
            name="encrypted_password",
            field=models.TextField(
                blank=True,
                default="",
                editable=False,
                help_text="Token Fernet (géré automatiquement — ne pas modifier manuellement).",
                verbose_name="Mot de passe chiffré",
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="networkdevice",
            name="api_port",
            field=models.PositiveIntegerField(
                default=8728,
                help_text="Port API RouterOS (8728 plain, 8729 SSL). Laisser 8728 par défaut.",
            ),
        ),
        migrations.AlterField(
            model_name="networkdevice",
            name="password_hint",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Référence à une variable d'environnement : ex. env:MIKROTIK_PASS_SITE12. "
                    "Laisser vide si le mot de passe est défini via le champ 'Définir le mot de passe' ci-dessous."
                ),
                max_length=128,
                verbose_name="Réf. secret (env var)",
            ),
        ),
    ]
