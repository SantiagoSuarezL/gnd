"""Implementacion real de ``Protocol MonitoringRepository`` sobre SQLite.

TECHNICAL_SPEC.md §3 (Extension Fase 8): las sesiones de monitoreo tienen
sus propias tablas (``monitoring_sessions`` + ``monitoring_hops``) porque
son N muestras por hop, no una fila unica por run_id. Esto permite
reconstruir el骨架 de la ruta en el tiempo sin serializar todo el
``MonitoringSession`` a JSON.

NOTA sobre muestras individuales: el DoD Fase 8 exige que la sesion
producida tiene ``samples`` (lista de ``MonitoringSample``) coherentes
con las stats. La persistencia SNAPSHOTS las stats agregadas (un row por
hop) + una fila de sesion para no inflar el esquema. Las muestras
individuales no se persisten (son derivables de RouteMonitor re-ejecutando,
no aportan mas informacion que las agregadas). Si en el futuro se
quiere persistir muestras crudas para analisis temporal post-ips, se
agrega una tercera tabla ``monitoring_samples``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from gnd.database.schema import ensure_schema
from gnd.models.monitoring import HopStats, MonitoringSession


class SqliteMonitoringRepository:
    """Persiste y recupera ``MonitoringSession`` sobre SQLite.

    Una sola responsabilidad: guardar sesiones de monitoreo completas
    (stats agregadas por hop) y recuperarlas por ``run_id``. No contiene
    logica de negocio, no mezcla providers (las sesiones se identifican
    por run_id y target_provider, no por IP).

    Schema (ver ``database/schema.py`` SCHEMA_VERSION=2):
        monitoring_sessions(session_id PK auto, run_id, target_ip,
            target_provider, started_at, finished_at, interval_s)
        monitoring_hops(id PK auto, session_id FK, hop_number, ip, hostname,
            best_ms, worst_ms, avg_ms, jitter_ms, loss_pct, samples,
            success_count)
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.row_factory = sqlite3.Row
        ensure_schema(self._conn)

    def save_session(self, session: MonitoringSession) -> None:
        """Guarda una sesion de monitoreo completa (sesion + stats por hop).

        Aborta la transaccion entera si alguna insercion falla (atomico).
        """
        try:
            cur = self._conn.execute(
                """INSERT INTO monitoring_sessions
                   (run_id, target_ip, target_provider, started_at,
                    finished_at, interval_s)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session.run_id,
                    session.target_ip,
                    session.target_provider,
                    session.started_at.isoformat(),
                    session.finished_at.isoformat(),
                    session.interval_s,
                ),
            )
            session_id = cur.lastrowid
            assert session_id is not None

            for h in session.hop_stats:
                self._conn.execute(
                    """INSERT INTO monitoring_hops
                       (session_id, hop_number, ip, hostname,
                        best_ms, worst_ms, avg_ms, jitter_ms, loss_pct,
                        samples, success_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        h.hop_number,
                        h.ip,
                        h.hostname,
                        h.best_ms,
                        h.worst_ms,
                        h.avg_ms,
                        h.jitter_ms,
                        h.loss_pct,
                        h.samples,
                        h.success_count,
                    ),
                )
            self._conn.commit()
        except Exception:
            # Rollback para mantener atomicidad: o se guarda entera o nada.
            self._conn.rollback()
            raise

    def get_sessions_by_run(self, run_id: str) -> list[MonitoringSession]:
        """Recupera todas las sesiones vinculadas a ``run_id``.

        Devuelve una lista (posiblemente vacia). Las sesiones se
        reconstruyen sin las muestras individuales (ver nota de modulo).
        """
        rows = self._conn.execute(
            """SELECT session_id, run_id, target_ip, target_provider,
                      started_at, finished_at, interval_s
                 FROM monitoring_sessions
                WHERE run_id = ?
                ORDER BY session_id ASC""",
            (run_id,),
        ).fetchall()

        sessions: list[MonitoringSession] = []
        for r in rows:
            session_id = r["session_id"]
            hop_rows = self._conn.execute(
                """SELECT hop_number, ip, hostname, best_ms, worst_ms,
                          avg_ms, jitter_ms, loss_pct, samples,
                          success_count
                     FROM monitoring_hops
                    WHERE session_id = ?
                    ORDER BY hop_number ASC""",
                (session_id,),
            ).fetchall()

            hop_stats = [_row_to_hop_stats(h) for h in hop_rows]
            sessions.append(
                MonitoringSession(
                    run_id=r["run_id"],
                    target_ip=r["target_ip"],
                    target_provider=r["target_provider"],
                    started_at=datetime.fromisoformat(r["started_at"]),
                    finished_at=datetime.fromisoformat(r["finished_at"]),
                    interval_s=float(r["interval_s"]),
                    samples=[],  # ver nota de modulo: no se persisten crudas
                    hop_stats=hop_stats,
                )
            )
        return sessions


def _row_to_hop_stats(row: sqlite3.Row) -> HopStats:
    return HopStats(
        hop_number=row["hop_number"],
        ip=row["ip"],
        hostname=row["hostname"],
        best_ms=row["best_ms"],
        worst_ms=row["worst_ms"],
        avg_ms=row["avg_ms"],
        jitter_ms=float(row["jitter_ms"]),
        loss_pct=float(row["loss_pct"]),
        samples=int(row["samples"]),
        success_count=int(row["success_count"]),
    )
