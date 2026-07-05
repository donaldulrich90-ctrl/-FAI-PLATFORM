"""Qui peut voir / gérer toutes les organisations (hors locataire unique)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser


def user_sees_all_tenants(user: AbstractBaseUser) -> bool:
    """Superuser ou gestionnaire plateforme : pas de filtre par organisation dans l’admin."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(getattr(user, "is_platform_operator", False)) and user.is_staff


def user_can_manage_tenant_records(user: AbstractBaseUser) -> bool:
    """Peut créer / modifier les modèles Tenant dans l’admin."""
    return user_sees_all_tenants(user)
