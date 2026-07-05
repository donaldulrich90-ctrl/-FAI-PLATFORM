"""Crée ou met à jour un compte superuser pour le développement / premier démarrage."""

from __future__ import annotations

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class Command(BaseCommand):
    help = (
        "Si DJANGO_BOOTSTRAP_ADMIN_PASSWORD est défini, crée ou met à jour un superuser "
        "(autorisé seulement avec DEBUG=1 ou DJANGO_ALLOW_BOOTSTRAP_ADMIN=1)."
    )

    def handle(self, *args, **options) -> None:
        password = (os.environ.get("DJANGO_BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
        if not password:
            self.stdout.write(
                self.style.WARNING(
                    "DJANGO_BOOTSTRAP_ADMIN_PASSWORD vide — aucun compte admin créé ou modifié."
                )
            )
            return

        if not settings.DEBUG and not _env_bool("DJANGO_ALLOW_BOOTSTRAP_ADMIN"):
            raise CommandError(
                "Bootstrap admin refusé : activer DEBUG=1 ou DJANGO_ALLOW_BOOTSTRAP_ADMIN=1."
            )

        username = (os.environ.get("DJANGO_BOOTSTRAP_ADMIN_USERNAME") or "demo").strip() or "demo"
        email = (os.environ.get("DJANGO_BOOTSTRAP_ADMIN_EMAIL") or "").strip()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "role": User.Role.ADMIN,
            },
        )
        if not created:
            if email:
                user.email = email
            user.is_staff = True
            user.is_superuser = True
            user.role = User.Role.ADMIN

        user.set_password(password)
        user.save()

        action = "Créé" if created else "Mot de passe mis à jour pour"
        self.stdout.write(self.style.SUCCESS(f"{action} l’utilisateur « {username} » (superuser, rôle admin)."))
