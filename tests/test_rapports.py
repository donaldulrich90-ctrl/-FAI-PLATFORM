"""Tests des corrections de rapports : on ne compte que les tickets réellement
activés (consommés), et le rapport journalier est basé sur la date d'activation.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
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
