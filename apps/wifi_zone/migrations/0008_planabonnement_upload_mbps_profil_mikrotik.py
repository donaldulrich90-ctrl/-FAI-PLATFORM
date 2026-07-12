from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0007_alter_wifisimplesubscriber_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="planabonnement",
            name="upload_mbps",
            field=models.PositiveIntegerField(default=2, verbose_name="Débit upload (Mbps)"),
        ),
        migrations.AddField(
            model_name="planabonnement",
            name="profil_mikrotik",
            field=models.CharField(blank=True, max_length=64, verbose_name="Profil MikroTik"),
        ),
        migrations.AlterField(
            model_name="planabonnement",
            name="speed_mbps",
            field=models.PositiveIntegerField(default=2, verbose_name="Débit download (Mbps)"),
        ),
    ]
