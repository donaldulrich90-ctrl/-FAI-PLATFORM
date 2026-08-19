"""
Génère les rapports journaliers par revendeur.

Utilisation :
    python manage.py generate_daily_revendeur_reports          # hier
    python manage.py generate_daily_revendeur_reports --date 2026-05-20
    python manage.py generate_daily_revendeur_reports --today  # jour courant

À planifier à 23h59 via le Planificateur de tâches Windows :
    Action : python manage.py generate_daily_revendeur_reports
    Déclencheur : quotidien à 23:59
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum
from django.utils import timezone


class Command(BaseCommand):
    help = "Génère ou régénère les rapports journaliers par revendeur (basés sur le préfixe ticket)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            metavar="YYYY-MM-DD",
            help="Date du rapport (défaut : hier).",
        )
        parser.add_argument(
            "--today",
            action="store_true",
            help="Utiliser la date du jour plutôt qu'hier.",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            metavar="SLUG",
            help="Limiter à une organisation (slug).",
        )

    def handle(self, *args, **options):
        from apps.accounts.models import User
        from apps.finance.models import RevendeurDailyReport
        from apps.wifi_zone.models import Ticket

        tz = timezone.get_current_timezone()

        if options["date"]:
            report_date = datetime.date.fromisoformat(options["date"])
        elif options["today"]:
            report_date = timezone.localdate()
        else:
            report_date = timezone.localdate() - datetime.timedelta(days=1)

        day_start = timezone.make_aware(
            datetime.datetime.combine(report_date, datetime.time.min), tz
        )
        day_end = timezone.make_aware(
            datetime.datetime.combine(report_date, datetime.time(23, 59, 59, 999999)), tz
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Génération des rapports pour le {report_date} "
                f"({day_start.strftime('%H:%M')} → {day_end.strftime('%H:%M')} {tz})"
            )
        )

        # TOUS les revendeurs actifs (préfixe optionnel) : ceux sans préfixe sont
        # rattachés à leurs tickets uniquement via sold_by.
        revendeurs_qs = User.objects.filter(
            role=User.Role.REVENDEUR,
            is_active=True,
        ).select_related("tenant")

        if options["tenant"]:
            revendeurs_qs = revendeurs_qs.filter(tenant__slug=options["tenant"])

        if not revendeurs_qs.exists():
            self.stdout.write(self.style.WARNING("Aucun revendeur actif trouvé."))
            return

        created_count = 0
        updated_count = 0

        for rev in revendeurs_qs:
            prefix = (rev.ticket_prefix or "").strip().upper()

            # Recette comptée à l'ACTIVATION : tickets activés ce jour (used_at dans
            # la plage), rattachés au revendeur (sold_by) ou à son préfixe de code.
            # NB : les codes revendeurs sont de la forme "VI3630" (préfixe collé,
            # SANS tiret), donc on filtre sur le préfixe seul.
            owner = Q(sold_by=rev)
            if prefix:
                owner |= Q(code__startswith=prefix)
            activated_qs = Ticket.objects.filter(
                owner,
                used_at__gte=day_start,
                used_at__lte=day_end,
                status__in=[Ticket.Status.USED, Ticket.Status.EXPIRED],
            ).select_related("site", "sold_by").order_by("used_at")

            agg = activated_qs.aggregate(
                gross=Sum("price_xof"),
                comm=Sum("commission_amount_xof"),
                net=Sum("net_to_isp_xof"),
            )

            def _d(v):
                return v if isinstance(v, Decimal) else Decimal(v or 0)

            gross = _d(agg["gross"])
            comm = _d(agg["comm"])
            net = _d(agg["net"])
            used_count = activated_qs.count()

            # Nombre de tickets vendus/générés ce jour (informatif, distinct de la
            # recette) — rattachés par sold_by OU par préfixe de code.
            sold_count = Ticket.objects.filter(owner).filter(
                Q(sold_at__gte=day_start, sold_at__lte=day_end) |
                Q(created_at__gte=day_start, created_at__lte=day_end, sold_at__isnull=True),
            ).count()

            detail = []
            for t in activated_qs:
                detail.append({
                    "code": t.code,
                    "duration": t.duration,
                    "price_xof": str(t.price_xof),
                    "commission_xof": str(t.commission_amount_xof),
                    "net_isp_xof": str(t.net_to_isp_xof),
                    "status": t.status,
                    "site": t.site.site_id if t.site else "",
                    "site_name": t.site.name if t.site else "",
                    "activated_at": t.used_at.isoformat() if t.used_at else "",
                    "sold_at": t.sold_at.isoformat() if t.sold_at else "",
                    "hotspot_synced": t.hotspot_synced_at is not None,
                    "hotspot_error": t.hotspot_sync_error or "",
                })

            obj, created = RevendeurDailyReport.objects.update_or_create(
                revendeur=rev,
                report_date=report_date,
                defaults={
                    "tenant": rev.tenant,
                    "prefix": prefix,
                    "tickets_sold_count": sold_count,
                    "tickets_used_count": used_count,
                    "gross_xof": gross,
                    "commission_xof": comm,
                    "net_isp_xof": net,
                    "detail_json": detail,
                },
            )

            if created:
                created_count += 1
                status_str = self.style.SUCCESS("créé")
            else:
                updated_count += 1
                status_str = self.style.WARNING("mis à jour")

            self.stdout.write(
                f"  [{prefix}] {rev.get_full_name() or rev.username} — "
                f"{used_count} activés / {gross} XOF brut / "
                f"{comm} XOF commission → {status_str}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTerminé : {created_count} créés, {updated_count} mis à jour."
            )
        )
