"""Implementacion real de DiagnosticsRepository sobre SQLite.

TECHNICAL_SPEC.md §3. Solo implementa save_run() — la escritura.
Las queries de lectura (baseline, get_by_provider, etc.) son
responsabilidad de analysis/ (Fase 4) y se ejecutan directamente
contra SQLite, no a traves de este repositorio.
"""

import json
import sqlite3
from typing import Any

from gnd.database.schema import ensure_schema
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.traceroute import TracerouteHop


class SqliteDiagnosticsRepository:
    """Persiste DiagnosticRun completo en SQLite.

    Unica responsabilidad: guardar corridas de diagnostico.
    No expone metodos de lectura — analysis/ (Fase 4) accede
    directamente a la conexion SQLite para las queries historicas.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.row_factory = sqlite3.Row
        ensure_schema(self._conn)

    def save_run(self, run: DiagnosticRun) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO diagnostic_runs
               (run_id, started_at, finished_at,
                recommendation_verdict, recommendation_headline,
                recommendation_explanation, recommendation_score,
                responsible_component)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.started_at.isoformat(),
                run.finished_at.isoformat(),
                run.recommendation.verdict,
                run.recommendation.headline,
                json.dumps(run.recommendation.explanation),
                run.recommendation.score,
                run.recommendation.responsible_component,
            ),
        )

        probe_sql = """INSERT INTO probe_results
            (run_id, target_name, target_ip, provider, outcome,
             avg_ms, min_ms, max_ms, jitter_ms, packet_loss_pct,
             samples, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        for p in run.probes:
            self._conn.execute(
                probe_sql,
                (
                    run.run_id,
                    p.target_name,
                    p.target_ip,
                    p.provider,
                    p.outcome.name,
                    p.stats.avg_ms if p.stats else None,
                    p.stats.min_ms if p.stats else None,
                    p.stats.max_ms if p.stats else None,
                    p.stats.jitter_ms if p.stats else None,
                    p.stats.packet_loss_pct if p.stats else None,
                    p.stats.samples if p.stats else None,
                    p.timestamp.isoformat(),
                ),
            )

        traceroute_sql = """INSERT INTO traceroute_results
            (run_id, target_provider, culprit_hop_index, hops_json)
            VALUES (?, ?, ?, ?)"""
        for t in run.traceroutes:
            self._conn.execute(
                traceroute_sql,
                (
                    run.run_id,
                    t.target_provider,
                    t.culprit_hop_index,
                    json.dumps([_hop_to_dict(h) for h in t.hops]),
                ),
            )

        if run.active_game_server is not None:
            ags = run.active_game_server
            self._conn.execute(
                """INSERT INTO active_game_servers
                   (run_id, ip, port, protocol, detected_via, process_name)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    ags.ip,
                    ags.port,
                    ags.protocol,
                    ags.detected_via,
                    ags.process_name,
                ),
            )

        self._conn.commit()


def _hop_to_dict(hop: TracerouteHop) -> dict[str, Any]:
    return {
        "hop_number": hop.hop_number,
        "ip": hop.ip,
        "hostname": hop.hostname,
        "rtt_ms": hop.rtt_ms,
        "responded": hop.responded,
    }


def _dict_to_hop(d: dict[str, Any]) -> TracerouteHop:
    return TracerouteHop(
        hop_number=d["hop_number"],
        ip=d["ip"],
        hostname=d["hostname"],
        rtt_ms=d["rtt_ms"],
        responded=d["responded"],
    )
