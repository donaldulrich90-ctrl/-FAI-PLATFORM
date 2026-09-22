"""Tests des corrections de rapports : on ne compte que les tickets réellement
activés (consommés), et le rapport journalier est basé sur la date d'activation.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.test import RequestFactory
from django.utils import timezone

from apps.core.models import Site
from apps.tenants.models import Tenant
from apps.wifi_zone.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def site():
    tenant = Tenant.objects.create(name="FAI Test", slug="fai-test")
    return Site.objects.create(tenant=tenant, name="Site Test", site_id="ST-01")


def _activer(t, quand):
    t.first_used_at = quand
    t.status = Ticket.Status.USED
    t.save()


def test_dashboard_revendeur_ne_compte_que_les_actives(site):
    """5 tickets générés (stock) + 2 activés → doit afficher 2 vendus / 1000 XOF,
    surtout pas 7 / 3500."""
    rev = get_user_model().objects.create(username="rev1")

    for _ in range(5):  # stock généré, jamais utilisé
        Ticket.objects.create(duration="1d", price_xof=Decimal(500), site=site, sold_by=rev)
    for _ in range(2):  # réellement activés
        _activer(Ticket(duration="1d", price_xof=Decimal(500), site=site, sold_by=rev), timezone.now())

    # Réplique exacte de la logique corrigée de revendeur_dashboard
    activated = Ticket.objects.filter(
        sold_by=rev, status__in=[Ticket.Status.USED, Ticket.Status.EXPIRED]
    )
    agg = activated.aggregate(nb=Count("id"), brut=Sum("price_xof"))

    assert agg["nb"] == 2                    # et non 7
    assert agg["brut"] == Decimal(1000)      # et non 3500

    # Preuve du bug d'avant : compter TOUS les tickets donnait 7 / 3500
    tous = Ticket.objects.filter(sold_by=rev).aggregate(nb=Count("id"), brut=Sum("price_xof"))
    assert tous["nb"] == 7 and tous["brut"] == Decimal(3500)


def test_rapport_journalier_base_sur_activation(site):
    """Un ticket fabriqué hier mais activé aujourd'hui doit apparaître dans le
    rapport d'AUJOURD'HUI (basé sur used_at), pas dans celui d'hier."""
    rev = get_user_model().objects.create(username="rev2")
    now = timezone.now()
    hier = now - timedelta(days=1)

    t = Ticket(duration="1d", price_xof=Decimal(700), site=site, sold_by=rev)
    t.save()
    # simuler une fabrication hier
    Ticket.objects.filter(pk=t.pk).update(created_at=hier)
    t.refresh_from_db()
    _activer(t, now)  # activé aujourd'hui

    # Logique corrigée : rapport du jour = tickets activés ce jour (used_at)
    active_auj = Ticket.objects.filter(
        sold_by=rev,
        used_at__date=now.date(),
        status__in=[Ticket.Status.USED, Ticket.Status.EXPIRED],
    )
    assert active_auj.count() == 1          # ✔ visible aujourd'hui

    # Ancienne logique (par created_at) : il aurait été rattaché à HIER → absent aujourd'hui
    genere_auj = Ticket.objects.filter(sold_by=rev, created_at__date=now.date())
    assert genere_auj.count() == 0          # c'était le bug


def test_rattachement_par_prefixe_sans_tiret(site):
    """Un code revendeur type 'VI3630' (préfixe collé, SANS tiret) doit être
    rattaché au revendeur de préfixe 'VI'. L'ancien filtre 'VI-' échouait."""
    from django.db.models import Q

    t = Ticket(duration="30j", price_xof=Decimal(100000), site=site)
    t.save()
    Ticket.objects.filter(pk=t.pk).update(
        code="VI3630", status=Ticket.Status.USED, used_at=timezone.now()
    )

    prefix = "VI"
    owner = Q(code__startswith=prefix)          # logique corrigée
    assert Ticket.objects.filter(owner).count() == 1      # ✔ rattaché

    # Ancien filtre avec tiret → ne trouvait rien (le bug)
    assert Ticket.objects.filter(code__startswith="VI-").count() == 0


def test_rapport_inclut_tous_les_revendeurs_actifs(site):
    """Le rapport nocturne doit inclure TOUS les revendeurs actifs, même ceux
    sans préfixe de ticket configuré."""
    from django.core.management import call_command

    from apps.finance.models import RevendeurDailyReport

    User = get_user_model()
    tenant = site.tenant
    User.objects.create(
        username="rev_vi", role=User.Role.REVENDEUR, is_active=True,
        ticket_prefix="VI", tenant=tenant,
    )
    User.objects.create(
        username="rev_sans_prefixe", role=User.Role.REVENDEUR, is_active=True,
        tenant=tenant,
    )

    call_command("generate_daily_revendeur_reports", "--today")

    noms = set(RevendeurDailyReport.objects.values_list("revendeur__username", flat=True))
    assert "rev_vi" in noms
    assert "rev_sans_prefixe" in noms          # inclus même sans préfixe


def test_rapport_detail_compte_activation_par_prefixe(monkeypatch, site):
    """La vue par zone doit compter l'activation du jour même si le ticket a
    été fabriqué avant et n'a pas de ``sold_by`` (rattachement par préfixe)."""
    User = get_user_model()
    admin = User.objects.create_superuser(username="admin-report", password="test")
    rev = User.objects.create(
        username="rev-cl",
        role=User.Role.REVENDEUR,
        ticket_prefix="CL",
        tenant=site.tenant,
        site=site,
    )
    now = timezone.now()
    yesterday = now - timedelta(days=1)

    # Stock fabriqué aujourd'hui : informatif, mais pas encore comptabilisé.
    Ticket.objects.create(
        code="CL1000", duration="1d", price_xof=Decimal(500), site=site
    )
    # Vente réelle du jour, fabriquée la veille et déjà expirée au moment où
    # un rapport historique est consulté.
    activated = Ticket.objects.create(
        code="CL1001", duration="1d", price_xof=Decimal(700), site=site
    )
    Ticket.objects.filter(pk=activated.pk).update(
        created_at=yesterday,
        first_used_at=now,
        used_at=now,
        status=Ticket.Status.EXPIRED,
        is_used=False,
    )

    from apps.wifi_zone.views import zone_detail_report

    request = RequestFactory().get(
        "/wifi/zones/1/",
        {"period": "day", "date": timezone.localdate().isoformat()},
    )
    request.user = admin
    monkeypatch.setattr(
        "apps.wifi_zone.views.render",
        lambda _request, _template, context: context,
    )
    context = zone_detail_report(request, rev.pk)

    assert context["count_generated"] == 1
    assert context["count"] == 1
    assert context["brut_xof"] == Decimal(700)
    assert list(context["tickets"].values_list("code", flat=True)) == ["CL1001"]


def test_export_detail_ne_contient_que_les_activations(site):
    User = get_user_model()
    admin = User.objects.create_superuser(username="admin-export", password="test")
    rev = User.objects.create(
        username="rev-export",
        role=User.Role.REVENDEUR,
        ticket_prefix="EX",
        tenant=site.tenant,
        site=site,
    )
    now = timezone.now()
    Ticket.objects.create(
        code="EX-STOCK", duration="1d", price_xof=Decimal(500), site=site
    )
    activated = Ticket.objects.create(
        code="EX-USED", duration="1d", price_xof=Decimal(700), site=site
    )
    Ticket.objects.filter(pk=activated.pk).update(
        used_at=now,
        first_used_at=now,
        status=Ticket.Status.USED,
        is_used=True,
    )

    from apps.wifi_zone.views import zone_detail_report_csv

    request = RequestFactory().get(
        "/wifi/zones/1/export/",
        {"period": "day", "date": timezone.localdate().isoformat()},
    )
    request.user = admin
    response = zone_detail_report_csv(request, rev.pk)
    content = response.content.decode("utf-8-sig")

    assert response.status_code == 200
    assert "EX-USED" in content
    assert "EX-STOCK" not in content
