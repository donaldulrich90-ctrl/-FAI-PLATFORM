"""
Client HTTP/WS pour Uptime Kuma (structure initiale).

L'API REST officielle est limitée ; l'UI utilise Socket.IO.
En prod : définir UPTIME_KUMA_URL et utiliser un jeton si votre version l'expose.

Réf. : https://github.com/louislam/uptime-kuma/wiki/API
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from django.conf import settings


def fetch_status_page_public_summary() -> dict[str, Any]:
    """
    Placeholder : appel HTTP vers une page de statut publique ou endpoint interne.
    Adapter selon votre déploiement (reverse proxy, API key).
    """
    base = settings.UPTIME_KUMA_URL.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            # Endpoint exemple — remplacer par l'URL réelle de votre instance
            r = client.get(f"{base}/api/status-page/heartbeat/default")
            if r.status_code == 200:
                return r.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        pass
    return {"monitors": [], "error": "Uptime Kuma non joignable ou endpoint à configurer."}


async def websocket_monitor_list_stub() -> list[dict[str, Any]]:
    """
    Point d'entrée pour une future connexion Socket.IO (auth par cookie/socket token).
    Ici : retour vide ; implémenter avec `python-socketio` ou appels REST selon version.
    """
    return []
