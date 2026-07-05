"""
Synchronise la santé des liaisons PtP depuis Zabbix API.

Pour chaque liaison PtP active ayant un host Zabbix configuré :
  1. Récupère les items SNMP (RSSI / signal)
  2. Déduit l'état de santé (UP / DEGRADED / DOWN / UNKNOWN)
  3. Met à jour PtPLink.cached_health et cached_health_at

Utilisation :
    python manage.py sync_ptp_health
    python manage.py sync_ptp_health --link "Lien-Ouaga-Nord"
    python manage.py sync_ptp_health --dry-run

Seuils RSSI configurables via variables d'environnement :
    ZABBIX_PTP_RSSI_UP_THRESHOLD       (défaut 65, i.e. -65 dBm)
    ZABBIX_PTP_RSSI_DEGRADED_THRESHOLD (défaut 75, i.e. -75 dBm)
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

# Priorité pour comparer les états de santé (plus bas = pire)
_HEALTH_PRIORITY: dict[str, int] = {
    "down": 0,
    "degraded": 1,
    "unknown": 2,
    "up": 3,
}


def _extract_rssi(items: list[dict]) -> int | None:
    """
    Cherche la valeur RSSI dans la liste d'items Zabbix.
    Retourne le RSSI en dBm négatif normalisé (ex. -65), ou None si absent.
    """
    for item in items:
        name = item.get("name", "").lower()
        key = item.get("key_", "").lower()
        if item.get("state", "0") == "1":  # item non supporté par Zabbix
            continue
        if not ("rssi" in name or "rssi" in key or "signal" in name):
            continue
        try:
            val = float(item.get("lastvalue", ""))
            if val == 0:
                continue  # 0 signifie généralement absence de donnée
            # Ubiquiti SNMP retourne parfois une valeur positive (65 → -65 dBm)
            return int(-abs(val))
        except (ValueError, TypeError):
            continue
    return None


def _rssi_to_health(rssi: int | None) -> str:
    """Convertit un RSSI en dBm négatif vers un HealthState."""
    from apps.core.models import PtPLink

    if rssi is None:
        return PtPLink.HealthState.UNKNOWN

    up_threshold = -getattr(settings, "ZABBIX_PTP_RSSI_UP_THRESHOLD", 65)
    degraded_threshold = -getattr(settings, "ZABBIX_PTP_RSSI_DEGRADED_THRESHOLD", 75)

    if rssi >= up_threshold:
        return PtPLink.HealthState.UP
    if rssi >= degraded_threshold:
        return PtPLink.HealthState.DEGRADED
    return PtPLink.HealthState.DOWN


def _worst_health(*states: str) -> str:
    """Retourne le pire état parmi une liste d'états de santé."""
    return min(states, key=lambda s: _HEALTH_PRIORITY.get(s, 2))


class Command(BaseCommand):
    help = "Synchronise la santé des liaisons PtP actives depuis Zabbix API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--link",
            type=str,
            metavar="NOM",
            help="Limiter à une liaison spécifique (nom exact).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les résultats sans modifier la base de données.",
        )

    def handle(self, *args, **options):
        from apps.core.models import PtPLink
        from apps.monitoring.services import zabbix_api

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode DRY-RUN activé — aucune modification."))

        qs = PtPLink.objects.filter(is_active=True).exclude(
            zabbix_host_a="",
            zabbix_host_b="",
        ).select_related("site_a", "site_b")

        if options["link"]:
            qs = qs.filter(name=options["link"])

        if not qs.exists():
            self.stdout.write(
                self.style.WARNING("Aucune liaison PtP active avec host Zabbix configuré.")
            )
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Synchronisation santé de {qs.count()} liaison(s) PtP…")
        )

        try:
            auth = zabbix_api.login()
        except Exception as exc:
            logger.error("Connexion Zabbix impossible : %s", exc)
            self.stderr.write(self.style.ERROR(f"Connexion Zabbix impossible : {exc}"))
            self.stderr.write("Aucune mise à jour effectuée (santé précédente conservée).")
            return

        now = timezone.now()
        updated = 0
        errors = 0

        for link in qs:
            try:
                host_states: list[str] = []

                for host in [link.zabbix_host_a, link.zabbix_host_b]:
                    if not host:
                        continue
                    try:
                        items = zabbix_api.get_host_items_latest(
                            auth, host, search_patterns=["rssi", "signal"]
                        )
                        rssi = _extract_rssi(items)
                        host_states.append(_rssi_to_health(rssi))
                    except Exception as host_exc:
                        logger.warning(
                            "Erreur items Zabbix pour host %s (liaison %s) : %s",
                            host, link.name, host_exc,
                        )
                        host_states.append(PtPLink.HealthState.UNKNOWN)

                new_health = _worst_health(*host_states) if host_states else PtPLink.HealthState.UNKNOWN
                old_health = link.cached_health

                symbol = "✓" if new_health == PtPLink.HealthState.UP else (
                    "⚠" if new_health == PtPLink.HealthState.DEGRADED else (
                        "✗" if new_health == PtPLink.HealthState.DOWN else "?"
                    )
                )
                changed = " (inchangé)" if new_health == old_health else f" ({old_health} → {new_health})"
                self.stdout.write(f"  {symbol} {link.name}{changed}")

                if not dry_run:
                    PtPLink.objects.filter(pk=link.pk).update(
                        cached_health=new_health,
                        cached_health_at=now,
                    )
                updated += 1

            except Exception as exc:
                errors += 1
                logger.error("Erreur synchronisation liaison %s : %s", link.name, exc)
                self.stderr.write(self.style.ERROR(f"  {link.name} : {exc}"))

        try:
            zabbix_api._rpc("user.logout", params=[], auth=auth)
        except Exception:
            pass

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTerminé : {updated} liaison(s) traitée(s), {errors} erreur(s)."
            )
        )
