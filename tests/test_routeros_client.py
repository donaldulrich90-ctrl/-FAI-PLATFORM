"""Tests unitaires pour RouterOSClient et fonctions utilitaires."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.core.services.routeros_client import (
    RouterOSClient,
    RouterOSError,
    _effective_api_port,
    _ros_remove_ok,
    resolve_device_credential,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_device(
    *,
    pk: int = 1,
    management_host: str = "192.168.88.1",
    api_port: int = 8728,
    ssh_port: int = 22,
    username: str = "admin",
    password_hint: str = "env:MIKROTIK_TEST_PASS",
    encrypted_password: str = "",
    vendor: str = "mikrotik",
    is_active: bool = True,
    mikrotik_bridge_name: str = "",
):
    dev = MagicMock()
    dev.pk = pk
    dev.management_host = management_host
    dev.api_port = api_port
    dev.ssh_port = ssh_port
    dev.username = username
    dev.password_hint = password_hint
    dev.encrypted_password = encrypted_password
    dev.vendor = vendor
    dev.is_active = is_active
    dev.mikrotik_bridge_name = mikrotik_bridge_name
    return dev


# ── tests _effective_api_port ─────────────────────────────────────────────────

def test_effective_api_port_default():
    dev = _make_device(api_port=443)
    assert _effective_api_port(dev) == 8728


def test_effective_api_port_zero():
    dev = _make_device(api_port=0)
    assert _effective_api_port(dev) == 8728


def test_effective_api_port_custom():
    dev = _make_device(api_port=8729)
    assert _effective_api_port(dev) == 8729


def test_effective_api_port_8728():
    dev = _make_device(api_port=8728)
    assert _effective_api_port(dev) == 8728


# ── tests resolve_device_credential ──────────────────────────────────────────

def test_resolve_env_prefix(monkeypatch):
    monkeypatch.setenv("MIKROTIK_TEST_PASS", "secret123")
    dev = _make_device(password_hint="env:MIKROTIK_TEST_PASS")
    assert resolve_device_credential(dev) == "secret123"


def test_resolve_legacy_var(monkeypatch):
    monkeypatch.setenv("MY_PASS", "legacy")
    dev = _make_device(password_hint="MY_PASS")
    assert resolve_device_credential(dev) == "legacy"


def test_resolve_missing_returns_none(monkeypatch):
    monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
    dev = _make_device(password_hint="env:NONEXISTENT_VAR")
    assert resolve_device_credential(dev) is None


def test_resolve_enc_prefix_no_key(monkeypatch):
    monkeypatch.setattr("django.conf.settings.ENCRYPTION_KEY", "", raising=False)
    dev = _make_device(password_hint="enc:sometoken")
    result = resolve_device_credential(dev)
    assert result is None


# ── tests _ros_remove_ok ──────────────────────────────────────────────────────

def test_ros_remove_ok_exit_zero():
    assert _ros_remove_ok(0, "", "") is True


def test_ros_remove_ok_no_such_item():
    assert _ros_remove_ok(1, "", "no such item") is True


def test_ros_remove_ok_no_entries():
    assert _ros_remove_ok(1, "no entries found", "") is True


def test_ros_remove_ok_real_error():
    assert _ros_remove_ok(1, "internal error", "connection refused") is False


# ── tests RouterOSClient dry_run ──────────────────────────────────────────────

@pytest.fixture
def dry_run_client(settings):
    settings.ROUTER_CONTROL_DRY_RUN = True
    dev = _make_device()
    client = RouterOSClient(dev)
    client.connect()
    return client


def test_dry_run_mode(dry_run_client):
    assert dry_run_client.transport_mode == "dry_run"


def test_dry_run_hotspot_upsert(dry_run_client):
    ok, err = dry_run_client.hotspot_user_upsert(
        name="TEST123", password="TEST123",
        profile="default", limit_uptime="3h", comment="test",
    )
    assert ok is True
    assert err == ""


def test_dry_run_hotspot_remove(dry_run_client):
    assert dry_run_client.hotspot_user_remove("TEST123") is True


def test_dry_run_bridge_filter_remove(dry_run_client):
    assert dry_run_client.bridge_filter_remove("some-comment") is True


def test_dry_run_bridge_filter_drop(dry_run_client):
    assert dry_run_client.bridge_filter_drop_by_mac(
        "AA:BB:CC:DD:EE:FF", "bridge", "faso-isp-AABBCCDDEEFF"
    ) is True


def test_dry_run_hotspot_active_users(dry_run_client):
    assert dry_run_client.hotspot_active_users() == set()


def test_dry_run_hotspot_all_users(dry_run_client):
    assert dry_run_client.hotspot_all_users() == []


# ── tests RouterOSClient connexion échouée ────────────────────────────────────

def test_connect_fails_without_password(settings):
    settings.ROUTER_CONTROL_DRY_RUN = False
    settings.MIKROTIK_FALLBACK_SSH_PASSWORD_ENV = ""
    dev = _make_device(password_hint="")
    client = RouterOSClient(dev)
    with pytest.raises(RouterOSError, match="Mot de passe manquant"):
        client.connect()


def test_connect_tries_api_then_ssh(settings, monkeypatch):
    """Vérifie que l'API est tentée avant SSH lors d'une connexion."""
    settings.ROUTER_CONTROL_DRY_RUN = False
    monkeypatch.setenv("MIKROTIK_TEST_PASS", "pass")
    dev = _make_device(password_hint="env:MIKROTIK_TEST_PASS")
    client = RouterOSClient(dev)

    api_call_order = []

    def fake_librouteros_connect(**kwargs):
        api_call_order.append("api")
        raise ConnectionRefusedError("port fermé")

    fake_ssh = MagicMock()
    fake_ssh.connect.side_effect = lambda **kw: api_call_order.append("ssh") or None
    fake_ssh.exec_command.return_value = (MagicMock(), MagicMock(), MagicMock())

    with patch("librouteros.connect", side_effect=fake_librouteros_connect):
        with patch(
            "apps.core.services.routeros_client._build_ssh_client",
            return_value=fake_ssh,
        ):
            mode = client.connect()

    assert api_call_order[0] == "api"
    assert api_call_order[1] == "ssh"
    assert mode == "ssh"
    client.close()


# ── tests opérations via API mock ─────────────────────────────────────────────

@pytest.fixture
def api_client(settings, monkeypatch):
    settings.ROUTER_CONTROL_DRY_RUN = False
    monkeypatch.setenv("MIKROTIK_TEST_PASS", "pass")
    dev = _make_device(password_hint="env:MIKROTIK_TEST_PASS", api_port=8728)
    client = RouterOSClient(dev)
    client._mode = "api"

    mock_conn = MagicMock()
    mock_conn.return_value = iter([])
    client._conn = mock_conn
    return client, mock_conn


def test_hotspot_upsert_via_api(api_client):
    client, mock_conn = api_client
    mock_conn.return_value = iter([])  # print retourne vide (pas d'existant)

    ok, err = client.hotspot_user_upsert(
        name="VOUCHER01",
        password="VOUCHER01",
        profile="Profil-24H",
        limit_uptime="1d",
        comment="faso-wifi-zone-ticket-42",
    )
    assert ok is True
    assert err == ""
    assert mock_conn.called


def test_hotspot_active_users_via_api(api_client):
    client, mock_conn = api_client
    mock_conn.return_value = iter([{"user": "ABC"}, {"user": "DEF"}])
    users = client.hotspot_active_users()
    assert users == {"ABC", "DEF"}


def test_hotspot_all_users_via_api(api_client):
    client, mock_conn = api_client
    mock_conn.return_value = iter([
        {"name": "ABC", "profile": "default", "comment": "test"},
    ])
    users = client.hotspot_all_users()
    assert len(users) == 1
    assert users[0]["name"] == "ABC"
