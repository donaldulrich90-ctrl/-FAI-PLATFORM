"""
Sonde SNMP pour métriques airMAX / IF-MIB (PySNMP 7 — API asyncio).

Zabbix reste la source recommandée en production ; ce module complète par une sonde directe.
"""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
from dataclasses import dataclass, field
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


@dataclass
class UbiquitiFullMetrics:
    online: bool = False
    freq_mhz: int | None = None
    tx_power_dbm: int | None = None
    client_count: int | None = None
    avg_signal_dbm: int | None = None
    throughput_in_mbps: float | None = None
    throughput_out_mbps: float | None = None
    uptime_seconds: int | None = None
    rssi_dbm: int | None = None
    noise_floor_dbm: int | None = None
    error: str | None = None


def ping_host(host: str, timeout: int = 2) -> bool:
    """Retourne True si l'hôte répond au ping."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout), host]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 3)
        return result.returncode == 0
    except Exception:
        return False


class UbiquitiAirMAXSnmpService:
    """Interroge un équipement Ubiquiti airMAX via SNMPv2c (asyncio sous le capot)."""

    # OIDs Ubiquiti airMAX-MIB
    OID_RSSI       = "1.3.6.1.4.1.41112.1.4.5.1.5.1.2.1"
    OID_NOISE      = "1.3.6.1.4.1.41112.1.4.5.1.5.1.3.1"
    OID_FREQ       = "1.3.6.1.4.1.41112.1.4.1.1.3.1"
    OID_TX_POWER   = "1.3.6.1.4.1.41112.1.4.1.1.4.1"
    OID_STA_COUNT  = "1.3.6.1.4.1.41112.1.4.7.1.10.1"
    # IF-MIB / sysUpTime
    OID_IF_IN_OCT  = "1.3.6.1.2.1.31.1.1.1.6.1"
    OID_IF_OUT_OCT = "1.3.6.1.2.1.31.1.1.1.10.1"
    OID_SYSUPTIME  = "1.3.6.1.2.1.1.3.0"

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

    def _get_many(self, oid_map: dict[str, str]) -> dict[str, str | None]:
        """Interroge plusieurs OIDs en une seule passe asyncio."""
        async def _run() -> dict[str, str | None]:
            eng = SnmpEngine()
            results: dict[str, str | None] = {}
            try:
                for label, oid in oid_map.items():
                    results[label] = await self._get_one_async(eng, oid)
            finally:
                eng.close_dispatcher()
            return results

        try:
            return asyncio.run(_run())
        except Exception:
            return {k: None for k in oid_map}

    def fetch_metrics(self) -> AirMAXMetrics:
        raw: dict[str, Any] = self._get_many({
            "rssi": self.OID_RSSI,
            "noise": self.OID_NOISE,
            "ifhcinoctets": self.OID_IF_IN_OCT,
            "ifhcoutoctets": self.OID_IF_OUT_OCT,
        })

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

    def fetch_full_metrics(self, check_ping: bool = True) -> UbiquitiFullMetrics:
        """Retourne les métriques complètes pour l'affichage antenne."""
        m = UbiquitiFullMetrics()

        if check_ping:
            m.online = ping_host(self.host)
            if not m.online:
                return m
        else:
            m.online = True

        if get_cmd is None:
            m.error = "pysnmp non disponible"
            return m

        try:
            raw = self._get_many({
                "rssi":    self.OID_RSSI,
                "noise":   self.OID_NOISE,
                "freq":    self.OID_FREQ,
                "txpower": self.OID_TX_POWER,
                "stacnt":  self.OID_STA_COUNT,
                "inoct":   self.OID_IF_IN_OCT,
                "outoct":  self.OID_IF_OUT_OCT,
                "uptime":  self.OID_SYSUPTIME,
            })
        except Exception as exc:
            m.error = str(exc)[:120]
            return m

        def _int(v: str | None) -> int | None:
            if v is None:
                return None
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return None

        def _float(v: str | None) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        m.rssi_dbm          = _int(raw.get("rssi"))
        m.noise_floor_dbm   = _int(raw.get("noise"))
        m.avg_signal_dbm    = m.rssi_dbm
        m.freq_mhz          = _int(raw.get("freq"))
        m.tx_power_dbm      = _int(raw.get("txpower"))
        m.client_count      = _int(raw.get("stacnt"))

        inoct  = _int(raw.get("inoct"))
        outoct = _int(raw.get("outoct"))
        if inoct is not None:
            m.throughput_in_mbps  = round(inoct / 1_000_000, 2)
        if outoct is not None:
            m.throughput_out_mbps = round(outoct / 1_000_000, 2)

        uptime_raw = raw.get("uptime")
        if uptime_raw:
            try:
                ticks = int(float(uptime_raw))
                m.uptime_seconds = ticks // 100
            except (ValueError, TypeError):
                pass

        if all(v is None for v in [m.freq_mhz, m.tx_power_dbm, m.rssi_dbm, m.client_count]):
            m.error = "Données SNMP indisponibles"

        return m
