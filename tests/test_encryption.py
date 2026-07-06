"""Tests unitaires pour le service de chiffrement Fernet."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from apps.core.services.encryption import (
    decrypt_credential,
    encrypt_credential,
    is_encryption_available,
)


@pytest.fixture
def encryption_key(settings):
    key = Fernet.generate_key().decode()
    settings.ENCRYPTION_KEY = key
    # Forcer le rechargement du singleton
    import apps.core.services.encryption as enc_module
    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None
    yield key
    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None


@pytest.fixture
def no_encryption_key(settings):
    settings.ENCRYPTION_KEY = ""
    import apps.core.services.encryption as enc_module
    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None
    yield
    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None


# ── tests is_encryption_available ────────────────────────────────────────────

def test_available_with_key(encryption_key):
    assert is_encryption_available() is True


def test_not_available_without_key(no_encryption_key):
    assert is_encryption_available() is False


# ── tests encrypt / decrypt ───────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip(encryption_key):
    plaintext = "monSuperMotDePasse123!"
    token = encrypt_credential(plaintext)
    assert token != plaintext
    assert decrypt_credential(token) == plaintext


def test_encrypt_produces_different_tokens(encryption_key):
    """Fernet utilise un IV aléatoire — deux chiffrements du même texte diffèrent."""
    t1 = encrypt_credential("pass")
    t2 = encrypt_credential("pass")
    assert t1 != t2
    assert decrypt_credential(t1) == "pass"
    assert decrypt_credential(t2) == "pass"


def test_encrypt_without_key_raises(no_encryption_key):
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        encrypt_credential("test")


def test_decrypt_without_key_returns_none(no_encryption_key):
    result = decrypt_credential("gAAAAA_fake_token")
    assert result is None


def test_decrypt_invalid_token_returns_none(encryption_key):
    result = decrypt_credential("not_a_valid_fernet_token")
    assert result is None


def test_decrypt_token_from_different_key_returns_none(settings):
    import apps.core.services.encryption as enc_module

    # Chiffrer avec clé A
    key_a = Fernet.generate_key().decode()
    settings.ENCRYPTION_KEY = key_a
    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None
    token = encrypt_credential("secret")

    # Déchiffrer avec clé B
    key_b = Fernet.generate_key().decode()
    settings.ENCRYPTION_KEY = key_b
    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None
    result = decrypt_credential(token)
    assert result is None

    enc_module._fernet_instance = None
    enc_module._fernet_key_loaded = None


# ── tests NetworkDevice.set_password ─────────────────────────────────────────

@pytest.mark.django_db
def test_network_device_set_password(encryption_key):
    from apps.core.models import NetworkDevice, Site
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.create(name="Test", slug="test")
    site = Site.objects.create(tenant=tenant, name="Site1", site_id="S1")
    dev = NetworkDevice.objects.create(site=site, name="Router1", management_host="10.0.0.1")

    dev.set_password("routerpass42")
    dev.save()

    dev.refresh_from_db()
    assert dev.has_stored_password() is True

    from apps.core.services.routeros_client import resolve_device_credential
    resolved = resolve_device_credential(dev)
    assert resolved == "routerpass42"


@pytest.mark.django_db
def test_network_device_env_var_credential(monkeypatch):
    from apps.core.models import NetworkDevice, Site
    from apps.tenants.models import Tenant

    monkeypatch.setenv("ROUTER_PASS_S2", "envpassword")
    tenant = Tenant.objects.create(name="Test2", slug="test2")
    site = Site.objects.create(tenant=tenant, name="Site2", site_id="S2")
    dev = NetworkDevice.objects.create(
        site=site,
        name="Router2",
        management_host="10.0.0.2",
        password_hint="env:ROUTER_PASS_S2",
    )

    from apps.core.services.routeros_client import resolve_device_credential
    assert resolve_device_credential(dev) == "envpassword"


@pytest.mark.django_db
def test_encrypted_password_takes_priority_over_hint(encryption_key, monkeypatch):
    """Le champ encrypted_password a la priorité sur password_hint."""
    from apps.core.models import NetworkDevice, Site
    from apps.tenants.models import Tenant

    monkeypatch.setenv("ROUTER_PASS_S3", "envpassword")
    tenant = Tenant.objects.create(name="Test3", slug="test3")
    site = Site.objects.create(tenant=tenant, name="Site3", site_id="S3")
    dev = NetworkDevice.objects.create(
        site=site,
        name="Router3",
        management_host="10.0.0.3",
        password_hint="env:ROUTER_PASS_S3",
    )
    dev.set_password("encryptedpassword")
    dev.save()

    from apps.core.services.routeros_client import resolve_device_credential
    assert resolve_device_credential(dev) == "encryptedpassword"
