"""
Migration de données : crée les antennes Ubiquiti airMAX.

Identique à la commande `python manage.py setup_antennas` mais s'exécute
automatiquement au déploiement via `python manage.py migrate`.
"""
from django.db import migrations


# ── Antennes connues par site ───────────────────────────────────
ANTENNA_MAP = [
    {
        "site_match": "central",
        "fwd_start": 2222,
        "count": 8,
        "ip_start": 2,
        "prefix": "Central",
        "password": "@dminF@est202",
    },
    {
        "site_match": "ziniar",
        "fwd_start": 2242,
        "count": 8,
        "ip_start": 2,
        "prefix": "Ziniaré",
        "password": "Admin@Projet202@",
    },
    {
        "site_match": "saaba",
        "fwd_start": 2252,
        "count": 3,
        "ip_start": 2,
        "prefix": "Saaba",
        "password": "@dminF@est202",
    },
]


def create_antennas(apps, schema_editor):
    NetworkDevice = apps.get_model("core", "NetworkDevice")
    Site = apps.get_model("core", "Site")

    # Trouver les MikroTik parents
    mikrotiks = {}
    for dev in NetworkDevice.objects.filter(vendor="mikrotik", is_active=True):
        site = Site.objects.get(pk=dev.site_id)
        mikrotiks[dev.site_id] = (dev, site.name)

    if not mikrotiks:
        print("  ⚠ Aucun MikroTik trouvé — skip")
        return

    for group in ANTENNA_MAP:
        match = group["site_match"].lower()
        parent = None
        parent_site_id = None
        for sid, (mt, site_name) in mikrotiks.items():
            if match in site_name.lower():
                parent = mt
                parent_site_id = sid
                break

        if not parent:
            print(f"  ⚠ Pas de MikroTik pour '{group['site_match']}' — skip")
            continue

        for i in range(group["count"]):
            fwd_port = group["fwd_start"] + i
            ip = f"10.0.0.{group['ip_start'] + i}"
            name = f"Antenne {group['prefix']}-{i + 1}"

            dev, created = NetworkDevice.objects.update_or_create(
                site_id=parent_site_id,
                vendor="ubiquiti",
                ssh_forward_port=fwd_port,
                defaults={
                    "name": name,
                    "management_host": ip,
                    "ssh_port": 22,
                    "api_port": 0,
                    "username": "AdminFasoEq",
                    "aireos_username": "AdminFasoEq",
                    "aireos_prompt": "XC#",
                    "parent_mikrotik": parent,
                    "is_active": True,
                },
            )

            # Chiffrer et stocker le mot de passe
            if created and group.get("password"):
                try:
                    from apps.core.services.encryption import encrypt_credential
                    dev.encrypted_password = encrypt_credential(group["password"])
                    dev.save(update_fields=["encrypted_password"])
                except Exception:
                    pass  # Si le chiffrement échoue, on continue

            action = "CRÉÉ" if created else "MAJ"
            print(f"  {action}: {name} (port {fwd_port})")


def remove_antennas(apps, schema_editor):
    NetworkDevice = apps.get_model("core", "NetworkDevice")
    # Supprime uniquement les antennes créées par cette migration
    for group in ANTENNA_MAP:
        for i in range(group["count"]):
            fwd_port = group["fwd_start"] + i
            NetworkDevice.objects.filter(
                vendor="ubiquiti",
                ssh_forward_port=fwd_port,
            ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("monitoring", "0006_frequencemesure_scan_actif"),
        ("core", "0015_site_wifi_zone_profiles_2h_4h"),
    ]

    operations = [
        migrations.RunPython(create_antennas, remove_antennas),
    ]
