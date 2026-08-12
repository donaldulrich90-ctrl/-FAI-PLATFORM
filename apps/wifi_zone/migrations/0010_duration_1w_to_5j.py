"""
Migration : renommage durée ticket "1w" (7 jours) → "5j" (5 jours).

Ordre : RunPython (données) AVANT AlterField (contraintes choices), ce qui est
toujours sûr sur PostgreSQL (VARCHAR sans CHECK constraint Django).
"""
from django.db import migrations, models


def forward_1w_to_5j(apps, schema_editor):
    Ticket = apps.get_model("wifi_zone", "Ticket")
    WifiTicketBatch = apps.get_model("wifi_zone", "WifiTicketBatch")
    Ticket.objects.filter(duration="1w").update(duration="5j")
    WifiTicketBatch.objects.filter(duration="1w").update(duration="5j")


def reverse_5j_to_1w(apps, schema_editor):
    Ticket = apps.get_model("wifi_zone", "Ticket")
    WifiTicketBatch = apps.get_model("wifi_zone", "WifiTicketBatch")
    Ticket.objects.filter(duration="5j").update(duration="1w")
    WifiTicketBatch.objects.filter(duration="5j").update(duration="1w")


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0009_default_plans"),
    ]

    operations = [
        # 1. Migrer les données existantes avant de mettre à jour les choices
        migrations.RunPython(forward_1w_to_5j, reverse_code=reverse_5j_to_1w),
        # 2. Mettre à jour les choices sur Ticket.duration
        migrations.AlterField(
            model_name="ticket",
            name="duration",
            field=models.CharField(
                choices=[
                    ("3h", "3 heures"),
                    ("1d", "24 heures (1 jour)"),
                    ("5j", "5 jours"),
                    ("30j", "30 jours"),
                ],
                db_index=True,
                max_length=8,
            ),
        ),
        # 3. Mettre à jour les choices sur WifiTicketBatch.duration
        migrations.AlterField(
            model_name="wifiticketbatch",
            name="duration",
            field=models.CharField(
                choices=[
                    ("3h", "3 heures"),
                    ("1d", "24 heures (1 jour)"),
                    ("5j", "5 jours"),
                    ("30j", "30 jours"),
                ],
                db_index=True,
                max_length=8,
            ),
        ),
    ]
