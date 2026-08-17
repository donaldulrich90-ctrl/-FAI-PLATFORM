"""Tests de l'expiration calendaire et de la comptabilisation à l'activation
des tickets Wi-Fi Zone.

Lancer :  pytest tests/test_ticket_expiration.py -v
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Site
from apps.finance.models import CashJournalEntry
from apps.tenants.models import Tenant
from apps.wifi_zone.models import (
    Ticket,
    TicketConsommation,
    compute_ticket_expiry,
    ticket_duration_delta,
)
from apps.wifi_zone.services.ticket_activation import (
    expire_due_tickets,
    record_ticket_activation,
)

pytestmark = pytest.mark.django_db


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tenant():
    return Tenant.objects.create(name="FAI Test", slug="fai-test")


@pytest.fixture
def site(tenant):
    return Site.objects.create(tenant=tenant, name="Site Test", site_id="ST-01")


def _activer(site, *, duration="1d", price=500, activated_at=None):
    """Crée un ticket puis l'active (statut Utilisé) à la date donnée."""
    activated_at = activated_at or timezone.now()
    t = Ticket(duration=duration, price_xof=Decimal(price), site=site)
    t.save()  # statut « Disponible » par défaut
    t.first_used_at = activated_at
    t.status = Ticket.Status.USED
    t.save()  # → déclenche l'enregistrement recette + archive
    return t


def _proche(dt_a, dt_b, secondes=2):
    return abs((dt_a - dt_b).total_seconds()) < secondes


# ── 1. Mapping des durées → délai calendaire ──────────────────────────────────
def test_mapping_durees():
    assert ticket_duration_delta("2h") == timedelta(hours=2)
    assert ticket_duration_delta("3h") == timedelta(hours=3)
    assert ticket_duration_delta("4h") == timedelta(hours=4)
    assert ticket_duration_delta("1d") == timedelta(days=1)
    assert ticket_duration_delta("5j") == timedelta(days=5)
    assert ticket_duration_delta("1w") == timedelta(days=7)
    assert ticket_duration_delta("30j") == timedelta(days=30)
    assert ticket_duration_delta("illimite") is None

    now = timezone.now()
    assert compute_ticket_expiry(now, "1d") == now + timedelta(days=1)
    assert compute_ticket_expiry(now, "illimite") is None
    assert compute_ticket_expiry(None, "1d") is None


# ── 2. L'activation crée la recette + l'archive-preuve ────────────────────────
def test_activation_cree_recette_et_archive(site):
    now = timezone.now()
    t = _activer(site, duration="1d", price=500, activated_at=now)

    # net FAI = prix (pas de revendeur)
    assert t.net_to_isp_xof == Decimal(500)

    archive = TicketConsommation.objects.get(ticket=t)
    assert archive.code == t.code
    assert archive.price_xof == Decimal(500)
    assert archive.net_to_isp_xof == Decimal(500)
    assert _proche(archive.activated_at, now)
    assert _proche(archive.expires_at, now + timedelta(days=1))

    # écriture de caisse = recette (net FAI)
    assert archive.cash_entry_id is not None
    entry = CashJournalEntry.objects.get(pk=archive.cash_entry_id)
    assert entry.entry_type == CashJournalEntry.EntryType.INCOME
    assert entry.amount_xof == Decimal(500)
    assert entry.tenant_id == site.tenant_id


# ── 3. Idempotence : une seule recette / archive par ticket ───────────────────
def test_activation_idempotente(site):
    t = _activer(site, duration="1d", price=500)
    # nouvel appel explicite + nouvelle sauvegarde ne doivent rien dupliquer
    record_ticket_activation(t)
    t.save()

    assert TicketConsommation.objects.filter(ticket=t).count() == 1
    assert CashJournalEntry.objects.filter(category="Ticket Wi-Fi Zone").count() == 1


# ── 4. Un ticket dont la durée est écoulée passe à « Expiré » ─────────────────
def test_ticket_expire_apres_duree(site):
    past = timezone.now() - timedelta(days=2)
    t = _activer(site, duration="1d", price=500, activated_at=past)

    archive = TicketConsommation.objects.get(ticket=t)
    assert archive.expires_at < timezone.now()  # validité déjà dépassée

    n = expire_due_tickets()
    assert n == 1

    t.refresh_from_db()
    assert t.status == Ticket.Status.EXPIRED
    assert t.is_used is False

    archive.refresh_from_db()
    assert archive.expired_at is not None


# ── 5. Un ticket encore valide N'est PAS expiré ───────────────────────────────
def test_ticket_encore_valide_non_expire(site):
    t = _activer(site, duration="1d", price=500, activated_at=timezone.now())

    assert expire_due_tickets() == 0

    t.refresh_from_db()
    assert t.status == Ticket.Status.USED


# ── 6. Un ticket « Illimité » n'expire jamais ─────────────────────────────────
def test_illimite_n_expire_jamais(site):
    past = timezone.now() - timedelta(days=400)
    t = _activer(site, duration="illimite", price=1000, activated_at=past)

    archive = TicketConsommation.objects.get(ticket=t)
    assert archive.expires_at is None

    assert expire_due_tickets() == 0
    t.refresh_from_db()
    assert t.status == Ticket.Status.USED
