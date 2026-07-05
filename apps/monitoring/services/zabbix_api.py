"""
Client JSON-RPC minimal pour Zabbix — récupération d'items SNMP (RSSI, trafic) pour hosts Ubiquiti.

Variables d'environnement : ZABBIX_API_URL, ZABBIX_API_USER, ZABBIX_API_PASSWORD
"""
from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings


def _rpc(method: str, params: Any = None, auth: str | None = None) -> dict[str, Any]:
    if params is None:
        params = {}
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    if auth is not None:
        payload["auth"] = auth

    headers = {"Content-Type": "application/json-rpc"}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(settings.ZABBIX_API_URL, json=payload, headers=headers)
        r.raise_for_status()
        body = r.json()
    if "error" in body:
        raise RuntimeError(str(body["error"]))
    return body.get("result", {})


def login() -> str:
    return str(
        _rpc(
            "user.login",
            {"username": settings.ZABBIX_API_USER, "password": settings.ZABBIX_API_PASSWORD},
        )
    )


def get_host_items_latest(
    auth: str,
    host_name: str,
    search_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Retourne les derniers enregistrements d'items dont le nom correspond aux motifs SNMP utiles.
    search_patterns : ex. ['rssi', 'ifHCInOctets', 'signal']
    """
    hosts = _rpc(
        "host.get",
        {
            "output": ["hostid", "host", "name"],
            "filter": {"host": [host_name]},
        },
        auth=auth,
    )
    if not hosts:
        return []

    hostids = [h["hostid"] for h in hosts]
    items = _rpc(
        "item.get",
        {
            "output": ["itemid", "name", "key_", "lastvalue", "units", "state"],
            "hostids": hostids,
            "sortfield": "name",
        },
        auth=auth,
    )

    patterns = [p.lower() for p in (search_patterns or ["rssi", "signal", "snmp", "octets", "traffic"])]

    def match(name: str, key_: str) -> bool:
        blob = f"{name} {key_}".lower()
        return any(p in blob for p in patterns)

    return [i for i in items if match(i.get("name", ""), i.get("key_", ""))]


def fetch_ubiquiti_snmp_snapshot(host_name: str) -> dict[str, Any]:
    """Connexion + extraction simplifiée pour affichage dashboard."""
    try:
        token = login()
        items = get_host_items_latest(
            token,
            host_name,
            search_patterns=["rssi", "signal", "hcinoctets", "hcoutoctets", "traffic", "snmp"],
        )
        _rpc("user.logout", params=[], auth=token)
        return {"host": host_name, "items": items}
    except Exception as exc:  # noqa: BLE001
        return {"host": host_name, "items": [], "error": str(exc)}
