from django.db import migrations

DEFAULT_PLANS = [
    {"name": "Starter",  "speed_mbps": 2,  "upload_mbps": 2,  "price_xof": 10000},
    {"name": "Standard", "speed_mbps": 5,  "upload_mbps": 5,  "price_xof": 15000},
    {"name": "Premium",  "speed_mbps": 10, "upload_mbps": 10, "price_xof": 25000},
    {"name": "Business", "speed_mbps": 20, "upload_mbps": 20, "price_xof": 50000},
]


def create_default_plans(apps, schema_editor):
    PlanAbonnement = apps.get_model("wifi_zone", "PlanAbonnement")
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.all():
        for plan in DEFAULT_PLANS:
            PlanAbonnement.objects.get_or_create(
                tenant=tenant,
                name=plan["name"],
                defaults={
                    "speed_mbps": plan["speed_mbps"],
                    "upload_mbps": plan["upload_mbps"],
                    "price_xof": plan["price_xof"],
                    "profil_mikrotik": "",
                    "description": "",
                    "is_active": True,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("wifi_zone", "0008_planabonnement_upload_mbps_profil_mikrotik"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_plans, migrations.RunPython.noop),
    ]
