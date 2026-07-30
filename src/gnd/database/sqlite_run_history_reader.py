"""Implementación real de RunHistoryReader sobre SQLite (Fase 12b.3).

Lee runs persistidos en un rango [start, end) y los reconstruye como
``DiagnosticRun`` completos (con probes, traceroutes, game server, DNS e
interfaz opcionales). Es la operación inversa de
``SqliteDiagnosticsRepository._save_run_in_conn`` — misma estructura de
tablas, mismo orden de columnas.

Regla de Oro 9.1 (threading SQLite): recibe ``DatabaseConnectionFactory``
y pide una conn nueva por ``get_runs_in_period``. La conn vive y muere en
el hilo que la pidio (el hilo daemon del scheduler de reportes, no el
main loop de tkinter — el scheduler nunca comparte conn con la UI).

El reader solo lee. No modifica la DB, no invoca ``ensure_schema`` aquí
(el ``SqliteDiagnosticsRepository`` ya invocó ``ensure_schema`` al
construirse en el composition_root; si el reader se construye contra
una DB recién creada sin writer, el composition_root invoca
``ensure_schema`` explícitamente — ver ``build_report_pipeline``).
"""

import json
import sqlite3
from datetime import datetime
from typing import Any

from gnd.database.schema import ensure_schema
from gnd.domain.ports.database import DatabaseConnectionFactory
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.dns_measurement import DnsOutcome, DnsResolution
from gnd.models.latency_stats import LatencyStats
from gnd.models.network_interface import InterfaceType, NetworkInterfaceSnapshot
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult

__all__ = ["SqliteRunHistoryReader"]


# Mapeo string → Enum, inverso al ``.name`` usado en escritura. Centralizado
# para soportar DBs con rows pre-Enum (los primeros runs se persistieron
# con la misma convención .name — estable desde Fase 2).
_OUTCOMES = {
    "SUCCESS": ProbeOutcomeKind.SUCCESS,
    "FILTERED": ProbeOutcomeKind.FILTERED,
    "UNREACHABLE": ProbeOutcomeKind.UNREACHABLE,
    "TIMEOUT": ProbeOutcomeKind.TIMEOUT,
}
_DNS_OUTCOMES = {
    "SUCCESS": DnsOutcome.SUCCESS,
    "TIMEOUT": DnsOutcome.TIMEOUT,
    "ERROR": DnsOutcome.ERROR,
}
_INTERFACE_TYPES = {
    "WIFI": InterfaceType.WIFI,
    "ETHERNET": InterfaceType.ETHERNET,
    "OTHER": InterfaceType.OTHER,
}


def _parse_dt(s: str) -> datetime:
    """Parser ISO 8601 — tolera microsegundos o no (sqlitestore usa isoformat)."""
    # fromisoformat maneja ambos formatos en 3.11+. 3.12 garantizado.
    return datetime.fromisoformat(s)


class SqliteRunHistoryReader:
    """Implementación SQLite de ``RunHistoryReader``.

    El rango es half-open [start, end). Orden de salida: started_at ASC.
    Reconstruye cada run con sus dependencias (probes, traceroutes, AGS,
    DNS, interfaz) en una sola conn por query (no N+1 conn por run).
    """

    def __init__(self, db_factory: DatabaseConnectionFactory) -> None:
        """
        Args:
            db_factory: provee ``sqlite3.Connection`` por call. Cada
                ``get_runs_in_period`` pide una conn nueva y vive en el
                hilo del scheduler (nunca el main loop tkinter — Regla 9.1).

        Pre-warm: invoca ``ensure_schema`` al construir. Si la DB no
        existe, la crea — esto permite que el reader funcione en un
        arranque limpio sin un writer previo (escenario: el usuario
        habilita reportes sin nunca haber corrido un diagnóstico).
        Idempotente (``CREATE TABLE IF NOT EXISTS``).
        """
        self._factory = db_factory
        ensure_schema(db_factory.create_connection())

    def get_runs_in_period(
        self,
        start: datetime,
        end: datetime,
    ) -> list[DiagnosticRun]:
        if end < start:
            raise ValueError(
                f"end no puede ser anterior a start (start={start} end={end})"
            )
        # Regla de Oro 9.1: la factory es dueña del lifecycle de la conn.
        # El reader NO la cierra (mismo patrón que SqliteDiagnosticsRepository
        # en save_run — el GC libera el file handle en prod; en tests con
        # FakeDatabaseConnectionFactory, cerrarla rompería las asserts
        # posteriores del test sobre la conn compartida).
        conn = self._factory.create_connection()
        return self._read_in_conn(conn, start, end)

    # ------------------------------------------------------------------
    # Lectura por tabla — privado
    # ------------------------------------------------------------------

    def _read_in_conn(
        self,
        conn: sqlite3.Connection,
        start: datetime,
        end: datetime,
    ) -> list[DiagnosticRun]:
        cur = conn.execute(
            """SELECT run_id, started_at, finished_at,
                      recommendation_verdict, recommendation_headline,
                      recommendation_explanation, recommendation_score,
                      responsible_component
                 FROM diagnostic_runs
                WHERE started_at >= ? AND started_at < ?
                ORDER BY started_at ASC""",
            (start.isoformat(), end.isoformat()),
        )
        run_rows = cur.fetchall()
        if not run_rows:
            return []

        # Recolectar run_ids para queries hijas bulk (1 query por tabla
        # en vez de N queries — evita N+1 sobre runs grandes).
        run_ids = [r[0] for r in run_rows]
        probes_by_run = self._read_probes(conn, run_ids)
        traceroutes_by_run = self._read_traceroutes(conn, run_ids)
        ags_by_run = self._read_active_game_servers(conn, run_ids)
        dns_by_run = self._read_dns(conn, run_ids)
        iface_by_run = self._read_interfaces(conn, run_ids)

        runs: list[DiagnosticRun] = []
        for row in run_rows:
            (
                run_id,
                started_iso,
                finished_iso,
                verdict,
                headline,
                explanation_json,
                score,
                responsible,
            ) = row
            rec = Recommendation(
                verdict=verdict,
                headline=headline,
                explanation=json.loads(explanation_json),
                responsible_component=responsible,
                score=score,
            )
            runs.append(
                DiagnosticRun(
                    run_id=run_id,
                    started_at=_parse_dt(started_iso),
                    finished_at=_parse_dt(finished_iso),
                    probes=probes_by_run.get(run_id, []),
                    traceroutes=traceroutes_by_run.get(run_id, []),
                    active_game_server=ags_by_run.get(run_id),
                    recommendation=rec,
                    dns_results=tuple(dns_by_run.get(run_id, ())),
                    interface_snapshot=iface_by_run.get(run_id),
                )
            )
        return runs

    def _read_probes(
        self, conn: sqlite3.Connection, run_ids: list[str]
    ) -> dict[str, list[ProbeResult]]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" * len(run_ids))
        cur = conn.execute(
            f"""SELECT run_id, target_name, target_ip, provider, outcome,
                      avg_ms, min_ms, max_ms, jitter_ms, packet_loss_pct,
                      samples, timestamp, family
                 FROM probe_results
                WHERE run_id IN ({placeholders})""",  # noqa: S608
            run_ids,
        )
        out: dict[str, list[ProbeResult]] = {}
        for row in cur.fetchall():
            (
                run_id,
                target_name,
                target_ip,
                provider,
                outcome_str,
                avg_ms,
                min_ms,
                max_ms,
                jitter_ms,
                packet_loss_pct,
                samples,
                timestamp_iso,
                family,
            ) = row
            outcome = _OUTCOMES[outcome_str]
            stats = None
            if outcome is ProbeOutcomeKind.SUCCESS:
                # Invariante del modelo: stats no es None cuando SUCCESS.
                # Si la DB estuviera corrupta (avg None + outcome SUCCESS),
                # el dataclass lanzaría ValueError — preferible a silenciar.
                stats = LatencyStats(
                    avg_ms=avg_ms,
                    min_ms=min_ms,
                    max_ms=max_ms,
                    jitter_ms=jitter_ms,
                    packet_loss_pct=packet_loss_pct,
                    samples=samples,
                )
            out.setdefault(run_id, []).append(
                ProbeResult(
                    target_name=target_name,
                    target_ip=target_ip,
                    provider=provider,
                    outcome=outcome,
                    stats=stats,
                    timestamp=_parse_dt(timestamp_iso),
                    family=family,
                )
            )
        return out

    def _read_traceroutes(
        self, conn: sqlite3.Connection, run_ids: list[str]
    ) -> dict[str, list[TracerouteResult]]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" * len(run_ids))
        cur = conn.execute(
            f"""SELECT run_id, target_provider, culprit_hop_index, hops_json, family
                 FROM traceroute_results
                WHERE run_id IN ({placeholders})""",  # noqa: S608
            run_ids,
        )
        out: dict[str, list[TracerouteResult]] = {}
        for row in cur.fetchall():
            run_id, target_provider, culprit_idx, hops_json, family = row
            hops_data: list[dict[str, Any]] = json.loads(hops_json)
            hops = [
                TracerouteHop(
                    hop_number=int(h["hop_number"]),
                    ip=h.get("ip"),
                    hostname=h.get("hostname"),
                    rtt_ms=h.get("rtt_ms"),
                    responded=bool(h.get("responded", False)),
                )
                for h in hops_data
            ]
            out.setdefault(run_id, []).append(
                TracerouteResult(
                    target_provider=target_provider,
                    hops=hops,
                    culprit_hop_index=culprit_idx,
                    family=family,
                )
            )
        return out

    def _read_active_game_servers(
        self, conn: sqlite3.Connection, run_ids: list[str]
    ) -> dict[str, ActiveGameServerInfo]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" * len(run_ids))
        cur = conn.execute(
            f"""SELECT run_id, ip, port, protocol, detected_via, process_name
                 FROM active_game_servers
                WHERE run_id IN ({placeholders})""",  # noqa: S608
            run_ids,
        )
        out: dict[str, ActiveGameServerInfo] = {}
        for row in cur.fetchall():
            run_id, ip, port, protocol, detected_via, process_name = row
            out[run_id] = ActiveGameServerInfo(
                ip=ip,
                port=port,
                protocol=protocol,
                detected_via=detected_via,
                process_name=process_name,
            )
        return out

    def _read_dns(
        self, conn: sqlite3.Connection, run_ids: list[str]
    ) -> dict[str, list[DnsResolution]]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" * len(run_ids))
        cur = conn.execute(
            f"""SELECT run_id, hostname, resolved_ip, outcome, elapsed_ms,
                      family, error, timestamp
                 FROM dns_results
                WHERE run_id IN ({placeholders})""",  # noqa: S608
            run_ids,
        )
        out: dict[str, list[DnsResolution]] = {}
        for row in cur.fetchall():
            (
                run_id,
                hostname,
                resolved_ip,
                outcome_str,
                elapsed_ms,
                family,
                error,
                _timestamp_iso,
            ) = row
            out.setdefault(run_id, []).append(
                DnsResolution(
                    hostname=hostname,
                    resolved_ip=resolved_ip,
                    outcome=_DNS_OUTCOMES[outcome_str],
                    elapsed_ms=elapsed_ms,
                    family=family,
                    error=error,
                )
            )
        return out

    def _read_interfaces(
        self, conn: sqlite3.Connection, run_ids: list[str]
    ) -> dict[str, NetworkInterfaceSnapshot]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" * len(run_ids))
        cur = conn.execute(
            f"""SELECT run_id, type, name, is_default_route, wifi_ssid,
                      wifi_signal_dbm, error, timestamp
                 FROM interface_snapshots
                WHERE run_id IN ({placeholders})""",  # noqa: S608
            run_ids,
        )
        out: dict[str, NetworkInterfaceSnapshot] = {}
        for row in cur.fetchall():
            (
                run_id,
                type_str,
                name,
                is_default_route,
                wifi_ssid,
                wifi_signal_dbm,
                error,
                _timestamp_iso,
            ) = row
            out[run_id] = NetworkInterfaceSnapshot(
                type=_INTERFACE_TYPES[type_str],
                name=name,
                is_default_route=bool(is_default_route),
                wifi_ssid=wifi_ssid,
                wifi_signal_dbm=wifi_signal_dbm,
                error=error,
            )
        return out
