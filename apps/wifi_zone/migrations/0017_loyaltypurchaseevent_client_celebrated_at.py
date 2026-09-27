from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0016_wifipurchase_wifizonetarif"),
    ]

    operations = [
        migrations.AddField(
            model_name="loyaltypurchaseevent",
            name="client_celebrated_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Renseigné quand l'animation de félicitations a été affichée au client.",
                verbose_name="Cadeau annoncé au client le",
            ),
        ),
    ]
