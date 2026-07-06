"""
Chiffrement Fernet des credentials équipements réseau.

Clé : variable d'environnement ENCRYPTION_KEY (Fernet URL-safe base64, 32 octets).
Génération : python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Format stocké en base : préfixe "enc:" + token Fernet (ex. enc:gAAAAA...)
Format "env:" = référence à une variable d'environnement (non chiffré, toujours supporté).
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_fernet_instance = None
_fernet_key_loaded: str | None = None


def _get_fernet():
    global _fernet_instance, _fernet_key_loaded
    key = getattr(settings, "ENCRYPTION_KEY", "") or ""
    if not key:
        return None
    if key != _fernet_key_loaded:
        from cryptography.fernet import Fernet
        _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
        _fernet_key_loaded = key
    return _fernet_instance


def encrypt_credential(plaintext: str) -> str:
    """Chiffre un mot de passe. Retourne le token Fernet (sans préfixe 'enc:')."""
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError(
            "ENCRYPTION_KEY non configurée. "
            "Générez une clé : python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    token = fernet.encrypt(plaintext.encode()).decode()
    return token


def decrypt_credential(token: str) -> str | None:
    """Déchiffre un token Fernet. Retourne None si la clé est absente ou le token invalide."""
    fernet = _get_fernet()
    if fernet is None:
        logger.error(
            "ENCRYPTION_KEY non configurée — impossible de déchiffrer le credential. "
            "Définissez ENCRYPTION_KEY dans l'environnement."
        )
        return None
    try:
        return fernet.decrypt(token.encode()).decode()
    except Exception as exc:
        logger.error("Échec déchiffrement credential : %s", exc)
        return None


def is_encryption_available() -> bool:
    return _get_fernet() is not None
