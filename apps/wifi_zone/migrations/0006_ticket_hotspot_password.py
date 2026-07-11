from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0005_alter_ticket_duration_alter_ticket_hotspot_synced_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="hotspot_password",
            field=models.CharField(
                blank=True,
                help_text="Mot de passe distinct du code (tickets revendeurs). Vide = utilise le code comme mot de passe.",
                max_length=64,
                verbose_name="Mot de passe MikroTik",
            ),
        ),
    ]
