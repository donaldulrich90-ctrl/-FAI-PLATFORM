"""
Sonde SNMP pour métriques airMAX / IF-MIB (PySNMP 7 — API asyncio).

Zabbix reste la source recommandée en production ; ce module complète par une sonde directe.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from django.conf import settings

try:
    from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore[import-untyped]
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        get_cmd,
    )
except ImportError:  # pragma: no cover
    get_cmd = None  # type: ignore[misc,assignment]


@dataclass
class AirMAXMetrics:
    rssi_dbm: int | None
    noise_floor_dbm: int | None
    throughput_in_bps: int | None
    throughput_out_bps: int | None
    raw: dict[str, Any]


class UbiquitiAirMAXSnmpService:
    """Interroge un équipement via SNMPv2c (asyncio sous le capot)."""

    def __init__(
        self,
        host: str,
        community: str | None = None,
        port: int = 161,
    ) -> None:
        self.host = host
        self.community = community or getattr(
            settings,
            "SNMP_COMMUNITY",
            os.environ.get("SNMP_COMMUNITY", "public"),
        )
        self.port = port

    async def _get_one_async(self, engine: SnmpEngine, oid: str) -> str | None:
        if get_cmd is None:
            return None
        error_indication, error_status, _error_index, var_binds = await get_cmd(
            engine,
            CommunityData(self.community),
            await UdpTransportTarget.create((self.host, self.port), timeout=2, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication or error_status:
            return None
        for _oid, val in var_binds:
            return val.prettyPrint()
        return None

    def _get_one(self, oid: str) -> str | None:
        async def _run() -> str | None:
            eng = SnmpEngine()
            try:
                return await self._get_one_async(eng, oid)
            finally:
                eng.close_dispatcher()

        return asyncio.run(_run())

    def fetch_metrics(self) -> AirMAXMetrics:
        rssi_oid = getattr(
            settings,
            "UBNT_SNMP_RSSI_OID",
            "1.3.6.1.4.1.41112.1.4.5.1.5.1.2.1",
        )
        noise_oid = getattr(
            settings,
            "UBNT_SNMP_NOISE_OID",
            "1.3.6.1.4.1.41112.1.4.5.1.5.1.3.1",
        )
        if_in_octets = "1.3.6.1.2.1.31.1.1.1.6.1"
        if_out_octets = "1.3.6.1.2.1.31.1.1.1.10.1"

        raw: dict[str, Any] = {}
        for label, oid in [
            ("rssi", rssi_oid),
            ("noise", noise_oid),
            ("ifhcinoctets", if_in_octets),
            ("ifhcoutoctets", if_out_octets),
        ]:
            raw[label] = self._get_one(oid)

        def _int(val: str | None) -> int | None:
            if val is None:
                return None
            try:
                return int(float(val))
            except ValueError:
                return None

        return AirMAXMetrics(
            rssi_dbm=_int(raw.get("rssi")),
            noise_floor_dbm=_int(raw.get("noise")),
            throughput_in_bps=_int(raw.get("ifhcinoctets")),
            throughput_out_bps=_int(raw.get("ifhcoutoctets")),
            raw=raw,
        )
