from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_site_wifi_zone_profiles_2h_4h"),
        ("monitoring", "0005_alter_routerauditlog_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="frequenceconfig",
            name="scan_actif",
            field=models.BooleanField(
                default=False,
                help_text="Teste chaque fréquence candidate la nuit pour garder la plus propre (coupe brièvement le lien à chaque test).",
                verbose_name="Scan actif de nuit",
            ),
        ),
        migrations.CreateModel(
            name="FrequenceMesure",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("freq_mhz", models.IntegerField(db_index=True, verbose_name="Fréquence (MHz)")),
                (
                    "noise_floor_dbm",
                    models.IntegerField(blank=True, null=True, verbose_name="Bruit de fond (dBm)"),
                ),
                ("snr", models.FloatField(blank=True, null=True, verbose_name="SNR (dB)")),
                (
                    "signal_dbm",
                    models.IntegerField(blank=True, null=True, verbose_name="Signal (dBm)"),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("passif", "Passif (surveillance)"), ("scan", "Scan actif")],
                        db_index=True,
                        default="passif",
                        max_length=10,
                        verbose_name="Source",
                    ),
                ),
                (
                    "measured_at",
                    models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Mesuré le"),
                ),
                (
                    "device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="freq_mesures",
                        to="core.networkdevice",
                        verbose_name="Antenne",
                    ),
                ),
            ],
            options={
                "verbose_name": "mesure fréquence",
                "verbose_name_plural": "mesures fréquences",
                "ordering": ["-measured_at"],
            },
        ),
        migrations.AddIndex(
            model_name="frequencemesure",
            index=models.Index(
                fields=["device", "freq_mhz", "-measured_at"],
                name="freqmes_dev_freq_idx",
            ),
        ),
    ]
