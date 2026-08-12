"""
Migration : ajout des durées "1w" (7 jours) et "illimite" (Illimité) aux tickets.

Additive uniquement — aucune migration de données nécessaire.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0010_duration_1w_to_5j"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticket",
            name="duration",
            field=models.CharField(
                choices=[
                    ("3h", "3 heures"),
                    ("1d", "24 heures (1 jour)"),
                    ("5j", "5 jours"),
                    ("1w", "7 jours"),
                    ("30j", "30 jours"),
                    ("illimite", "Illimité"),
                ],
                db_index=True,
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="wifiticketbatch",
            name="duration",
            field=models.CharField(
                choices=[
                    ("3h", "3 heures"),
                    ("1d", "24 heures (1 jour)"),
                    ("5j", "5 jours"),
                    ("1w", "7 jours"),
                    ("30j", "30 jours"),
                    ("illimite", "Illimité"),
                ],
                db_index=True,
                max_length=8,
            ),
        ),
    ]
