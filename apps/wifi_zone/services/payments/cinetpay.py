"""Client CinetPay (guichet Mobile Money : Orange Money, Moov, Wave, carte).

Deux appels sont utilisés :
  • INIT  (POST /payment)        → ouvre un guichet et renvoie payment_token + payment_url
  • CHECK (POST /payment/check)  → statut faisant autorité d'une transaction

Bonne pratique CinetPay : ne JAMAIS faire confiance au corps du webhook de
notification ; à sa réception, on rappelle CHECK pour obtenir le statut réel.

Les identifiants proviennent des réglages Django (variables d'environnement) :
    CINETPAY_API_KEY, CINETPAY_SITE_ID, CINETPAY_MODE (TEST|PRODUCTION),
    CINETPAY_API_BASE (optionnel).

Aucune clé n'est écrite dans le code ; en l'absence de configuration, les
fonctions lèvent CinetPayError plutôt que d'échouer silencieusement.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api-checkout.cinetpay.com/v2"
TIMEOUT_SECONDS = 20

# Codes de succès renvoyés par CinetPay (paiement accepté).
_SUCCESS_CODES = {"00"}
# Codes signifiant « en attente du client » (paiement pas encore abouti).
_PENDING_CODES = {"662", "627", "623"}


class CinetPayError(Exception):
    """Erreur de configuration ou de communication avec CinetPay."""


def _config() -> dict:
    api_key = (getattr(settings, "CINETPAY_API_KEY", "") or "").strip()
    site_id = (getattr(settings, "CINETPAY_SITE_ID", "") or "").strip()
    base = (getattr(settings, "CINETPAY_API_BASE", "") or DEFAULT_API_BASE).rstrip("/")
    mode = (getattr(settings, "CINETPAY_MODE", "TEST") or "TEST").upper()
    return {"api_key": api_key, "site_id": site_id, "base": base, "mode": mode}


def is_configured() -> bool:
    cfg = _config()
    return bool(cfg["api_key"] and cfg["site_id"])


def _require_config() -> dict:
    cfg = _config()
    if not (cfg["api_key"] and cfg["site_id"]):
        raise CinetPayError(
            "CinetPay non configuré : renseignez CINETPAY_API_KEY et CINETPAY_SITE_ID "
            "dans les variables d'environnement."
        )
    return cfg


def normalize_amount(amount) -> int:
    """Montant entier en XOF, arrondi au multiple de 5 (contrainte Mobile Money)."""
    value = int(Decimal(amount))
    if value % 5 != 0:
        value = value - (value % 5)
    return max(0, value)


def initiate_payment(
    *,
    transaction_id: str,
    amount,
    description: str,
    notify_url: str,
    return_url: str,
    customer_name: str = "Client WiFi Zone",
    customer_phone: str = "",
    channels: str = "ALL",
    currency: str = "XOF",
    metadata: str = "",
) -> dict:
    """Ouvre un guichet de paiement CinetPay.

    Renvoie {"payment_token", "payment_url", "raw"}.
    Lève CinetPayError en cas d'échec.
    """
    cfg = _require_config()
    payload = {
        "apikey": cfg["api_key"],
        "site_id": cfg["site_id"],
        "transaction_id": transaction_id,
        "amount": normalize_amount(amount),
        "currency": currency,
        "description": (description or "Ticket WiFi Zone")[:255],
        "notify_url": notify_url,
        "return_url": return_url,
        "channels": channels or "ALL",
        "lang": "fr",
        "customer_name": (customer_name or "Client")[:100],
        "customer_phone_number": customer_phone or "",
        "metadata": (metadata or "")[:255],
    }
    url = f"{cfg['base']}/payment"
    try:
        resp = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.error("CinetPay init : échec réseau tx=%s : %s", transaction_id, exc)
        raise CinetPayError(f"Impossible de contacter CinetPay : {exc}") from exc

    try:
        body = resp.json()
    except ValueError:
        raise CinetPayError(f"Réponse CinetPay illisible (HTTP {resp.status_code}).")

    code = str(body.get("code", ""))
    data = body.get("data") or {}
    token = data.get("payment_token") or ""
    pay_url = data.get("payment_url") or ""
    if code in {"201", "00"} and token and pay_url:
        return {"payment_token": token, "payment_url": pay_url, "raw": body}

    message = body.get("message") or body.get("description") or f"HTTP {resp.status_code}"
    logger.error("CinetPay init refusé tx=%s code=%s : %s", transaction_id, code, message)
    raise CinetPayError(f"CinetPay a refusé l'initialisation ({code}) : {message}")


def check_payment(transaction_id: str) -> dict:
    """Interroge le statut faisant autorité d'une transaction.

    Renvoie {"status": "ACCEPTED"|"REFUSED"|"PENDING"|"UNKNOWN",
             "code", "payment_method", "operator_id", "amount", "raw"}.
    """
    cfg = _require_config()
    payload = {
        "apikey": cfg["api_key"],
        "site_id": cfg["site_id"],
        "transaction_id": transaction_id,
    }
    url = f"{cfg['base']}/payment/check"
    try:
        resp = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS)
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("CinetPay check : échec tx=%s : %s", transaction_id, exc)
        raise CinetPayError(f"Vérification CinetPay impossible : {exc}") from exc

    code = str(body.get("code", ""))
    data = body.get("data") or {}
    raw_status = str(data.get("status", "")).upper()

    if code in _SUCCESS_CODES or raw_status == "ACCEPTED":
        status = "ACCEPTED"
    elif raw_status == "REFUSED" or code in {"600", "602"}:
        status = "REFUSED"
    elif code in _PENDING_CODES or raw_status in {"PENDING", "WAITING", "WAITING_FOR_CUSTOMER"}:
        status = "PENDING"
    else:
        status = "UNKNOWN"

    return {
        "status": status,
        "code": code,
        "payment_method": data.get("payment_method", ""),
        "operator_id": data.get("operator_id", ""),
        "amount": data.get("amount", ""),
        "raw": body,
    }


def map_payment_method(cinetpay_method: str) -> str:
    """Traduit le payment_method CinetPay vers nos codes de moyen de paiement."""
    m = (cinetpay_method or "").upper()
    if m.startswith("OM") or "ORANGE" in m:
        return "orange_money"
    if "MOOV" in m or m in {"FLOOZ", "MOMO"}:
        return "moov_money"
    if "WAVE" in m:
        return "wave"
    if "TELECEL" in m:
        return "telecel_money"
    if "CARD" in m or "VISA" in m or "MASTERCARD" in m or m == "CREDIT_CARD":
        return "card"
    return "unknown"
