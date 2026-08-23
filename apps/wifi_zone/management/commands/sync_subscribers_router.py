"""Réconcilie l'accès routeur (ip-binding hotspot) pour TOUS les abonnés domicile.

Pour chaque abonné ayant un routeur assigné et une MAC :
  • statut Actif / Nouveau  → ip-binding "bypassed"  (contourne le portail captif)
  • statut Suspendu / Expiré → ip-binding "blocked"   (coupe réellement l'accès)

À lancer UNE FOIS après déploiement pour aligner le routeur sur l'app (créer les
bypass manquants, corriger l'existant). Ensuite, les actions Activer / Suspendre
de la plateforme entretiennent l'état automatiquement.

Utilisation :
    python manage.py sync_subscribers_router --dry-run
    python manage.py sync_subscribers_router
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Pousse les ip-bindings hotspot (bypass/blocked) pour tous les abonnés domicile."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait poussé, sans contacter le routeur.",
        )

    def handle(self, *args, **options):
        from apps.wifi_zone.models import WiFiSimpleSubscriber
        from apps.wifi_zone.router_control import activate_subscriber, suspend_subscriber

        dry = options["dry_run"]
        S = WiFiSimpleSubscriber

        qs = (
            S.objects.filter(cpe_device__isnull=False)
            .exclude(mac_address="")
            .exclude(mac_address__isnull=True)
            .select_related("cpe_device", "site")
            .order_by("full_name")
        )

        total = qs.count()
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"{total} abonné(s) avec routeur + MAC"
                + (" — DRY-RUN (aucune commande envoyée)" if dry else "")
            )
        )

        bypass = blocked = errors = 0
        for sub in qs:
            # Suspendu ou expiré → bloqué ; sinon → bypass.
            to_block = sub.status in (S.Status.SUSPENDU, S.Status.EXPIRE)
            label = "BLOCKED" if to_block else "BYPASS"
            self.stdout.write(f"  [{label}] {sub.full_name} — {sub.mac_address}")
            if dry:
                continue
            try:
                if to_block:
                    ok, _ = suspend_subscriber(sub)
                    blocked += 1 if ok else 0
                else:
                    ok, _ = activate_subscriber(sub)
                    bypass += 1 if ok else 0
                if not ok:
                    errors += 1
            except Exception as exc:  # pragma: no cover
                errors += 1
                self.stdout.write(self.style.ERROR(f"      échec : {exc}"))

        if not dry:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nTerminé : {bypass} bypass, {blocked} bloqués, {errors} erreur(s)."
                )
            )
