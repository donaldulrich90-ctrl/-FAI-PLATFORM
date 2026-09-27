"""
Crée / met à jour les antennes Ubiquiti airMAX dans la base de données.

Utilisation :
    python manage.py setup_antennas
    python manage.py setup_antennas --dry-run
    python manage.py setup_antennas --password "monmotdepasse"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

# ── Définition des antennes par site ──────────────────────────────
# Clé = sous-chaîne cherchée dans le nom du site (insensible à la casse)
# fwd_start  = premier port SSH forwarding sur le MikroTik parent
# count      = nombre d'antennes
# ip_start   = dernier octet de la première IP LAN (10.0.0.X)
ANTENNA_MAP = [
    {
        "site_match": "central",
        "fwd_start": 2222,
        "count": 8,
        "ip_start": 2,
        "prefix": "Central",
        "password_env": "@dminF@est202",
    },
    {
        "site_match": "ziniar",
        "fwd_start": 2242,
        "count": 8,
        "ip_start": 2,
        "prefix": "Ziniaré",
        "password_env": "Admin@Projet202@",
    },
    {
        "site_match": "saaba",
        "fwd_start": 2252,
        "count": 3,
        "ip_start": 2,
        "prefix": "Saaba",
        "password_env": "@dminF@est202",
    },
]


class Command(BaseCommand):
    help = "Crée ou met à jour les antennes Ubiquiti airMAX dans la BD"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait fait sans modifier la BD.",
        )
        parser.add_argument(
            "--password",
            type=str,
            default="",
            help="Mot de passe SSH airOS à stocker (chiffré) sur chaque antenne.",
        )

    def handle(self, *args, **options):
        from apps.core.models import NetworkDevice, Site

        dry_run = options["dry_run"]
        password = options.get("password", "")

        # Trouver les MikroTik parents actifs
        mikrotiks = {}
        for dev in NetworkDevice.objects.filter(vendor="mikrotik", is_active=True).select_related("site"):
            mikrotiks[dev.site_id] = dev

        if not mikrotiks:
            self.stderr.write(self.style.ERROR("Aucun MikroTik actif trouvé en base !"))
            return

        self.stdout.write(self.style.SUCCESS(f"MikroTik trouvés : {len(mikrotiks)}"))
        for sid, mt in mikrotiks.items():
            self.stdout.write(f"  • {mt.name} (site_id={sid}, site={mt.site.name})")

        # Trouver les sites correspondants
        sites = {s.pk: s for s in Site.objects.all()}
        created = updated = skipped = 0

        for group in ANTENNA_MAP:
            match = group["site_match"].lower()
            parent = None
            for sid, mt in mikrotiks.items():
                site_name = sites.get(sid)
                if site_name and match in site_name.name.lower():
                    parent = mt
                    break

            if not parent:
                self.stderr.write(self.style.WARNING(
                    f"  ⚠ Pas de MikroTik pour site '{group['site_match']}' — ignoré"
                ))
                skipped += group["count"]
                continue

            for i in range(group["count"]):
                fwd_port = group["fwd_start"] + i
                ip = f"10.0.0.{group['ip_start'] + i}"
                name = f"Antenne {group['prefix']}-{i + 1}"

                if dry_run:
                    self.stdout.write(f"  [DRY-RUN] {name} | port={fwd_port} | ip={ip} | parent={parent.name}")
                    continue

                dev, is_new = NetworkDevice.objects.update_or_create(
                    site=parent.site,
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

                # Stocker le mot de passe chiffré si fourni
                pw = password or group.get("password_env", "")
                if pw and not dev.has_stored_password():
                    dev.set_password(pw)
                    dev.save(update_fields=["encrypted_password"])

                if is_new:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  + CRÉÉ  : {name} (port {fwd_port})"))
                else:
                    updated += 1
                    self.stdout.write(f"  ~ MAJ   : {name} (port {fwd_port})")

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode DRY-RUN — rien n'a été modifié."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Terminé : {created} créées, {updated} mises à jour, {skipped} ignorées"
            ))
            self.stdout.write(
                "→ Va sur https://faestfai.duckdns.org/monitoring/antennes/ pour vérifier."
            )
