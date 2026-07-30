from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_user_revendeur_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="type_revendeur",
            field=models.CharField(
                blank=True,
                choices=[("autonome", "Autonome"), ("partenaire", "Partenaire")],
                default="autonome",
                help_text="AUTONOME : peut générer ses propres tickets. PARTENAIRE : accès lecture seule à ses ventes.",
                max_length=16,
                verbose_name="Type de revendeur",
            ),
        ),
    ]
