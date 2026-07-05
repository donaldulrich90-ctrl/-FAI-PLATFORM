from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0002_alter_ticket_options_ticket_commission_amount_xof_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="hotspot_sync_error",
            field=models.CharField(
                blank=True,
                help_text="Dernier message d’échec (SSH / configuration).",
                max_length=512,
                verbose_name="Erreur sync Hotspot",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="hotspot_synced_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Routeur MikroTik : utilisateur hotspot créé avec succès.",
                null=True,
                verbose_name="Dernier provisionnement Hotspot",
            ),
        ),
    ]
