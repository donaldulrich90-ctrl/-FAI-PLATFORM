# Alignement durées tickets avec RouterOS (3h / 1d / 1w / 30j) et profils typiques.

from django.db import migrations


def forwards(apps, schema_editor):
    Ticket = apps.get_model("wifi_zone", "Ticket")
    WifiTicketBatch = apps.get_model("wifi_zone", "WifiTicketBatch")
    Ticket.objects.filter(duration="1h").update(duration="3h")
    Ticket.objects.filter(duration="24h").update(duration="1d")
    WifiTicketBatch.objects.filter(duration="1h").update(duration="3h")
    WifiTicketBatch.objects.filter(duration="24h").update(duration="1d")


def backwards(apps, schema_editor):
    Ticket = apps.get_model("wifi_zone", "Ticket")
    WifiTicketBatch = apps.get_model("wifi_zone", "WifiTicketBatch")
    Ticket.objects.filter(duration="3h").update(duration="1h")
    Ticket.objects.filter(duration="1d").update(duration="24h")
    WifiTicketBatch.objects.filter(duration="3h").update(duration="1h")
    WifiTicketBatch.objects.filter(duration="1d").update(duration="24h")


class Migration(migrations.Migration):
    dependencies = [
        ("wifi_zone", "0003_ticket_hotspot_sync"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
