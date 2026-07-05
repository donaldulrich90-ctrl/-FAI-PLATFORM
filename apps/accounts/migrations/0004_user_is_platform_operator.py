from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_platform_operator",
            field=models.BooleanField(
                default=False,
                help_text="Peut créer les organisations (locataires) et voir toutes les données dans l’admin. "
                "Laisser « Organisation » vide pour ce compte. Réservé au personnel de l’éditeur, pas aux FAI clients.",
                verbose_name="Gestionnaire plateforme (SaaS)",
            ),
        ),
    ]
