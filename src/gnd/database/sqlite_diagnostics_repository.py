"""Implementacion real de DiagnosticsRepository sobre SQLite.

TECHNICAL_SPEC.md §3. Solo implementa save_run() — la escritura.
Las queries de lectura (baseline, get_by_provider, etc.) son
responsabilidad de analysis/ (Fase 4) y se ejecutan directamente
contra SQLite, no a traves de este repositorio.

Regla de Oro 9.1 (threading SQLite): en lugar de recibir una
``sqlite3.Connection`` compartida (prohibida cross-thread por sqlite3),
recibe una ``DatabaseConnectionFactory`` y pide una conn nueva por
``save_run``. Cada conn vive y muere dentro del hilo que la pidio.
"""

import json
import sqlite3
from typing import Any

from gnd.database.schema import ensure_schema
from gnd.domain.ports.database import DatabaseConnectionFactory
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.traceroute import TracerouteHop


class SqliteDiagnosticsRepository:
    """Persiste DiagnosticRun completo en SQLite.

    Unica responsabilidad: guardar corridas de diagnostico.
    No expone metodos de lectura — analysis/ (Fase 4) accede
    directamente a una conexion SQLite (pedida via la misma factory)
    para las queries historicas.

    La factory se prove por constructor (DI). ``save_run`` pide una
    conn nueva, ejecuta los INSERTs y la cierra. Multiples calls =
    multiples conns (todas del mismo hilo — no hay bug cross-thread).
    """

    def __init__(self, db_factory: DatabaseConnectionFactory) -> None:
        """
        Args:
            db_factory: provee ``sqlite3.Connection`` por call. En un
                hilo worker (UI controller) cada ``save_run`` pide una
                nueva conn de la factory; esa conn vive y muere en el
                mismo hilo. Nunca compartirla entre hilos (Regla de Oro 9.1).

        Pre-warm: pide una conn al construir y deja que el GC la cierre.
        ``ensure_schema`` usa ``CREATE TABLE IF NOT EXISTS`` para que un
        primer arranque cree las tablas antes de cualquier save_run o
        compute_baseline. Idempotente.
        """
        self._factory = db_factory
        ensure_schema(db_factory.create_connection())

    def save_run(self, run: DiagnosticRun) -> None:
        # Regla de Oro 9.1: pedir conn nueva del factory. No se cierra
        # explicitamente (sqlite3.Connection cierra la DB file handle al
        # GC). En tests FakeDatabaseConnectionFactory puede devolver una
        # conn compartida — si la cerrasemos aqui, los asserts posteriores
        # del test fallarian ("Cannot operate on a closed database").
        # En prod, SqliteConnectionFactory crea conn nueva por call y el
        # GC libera el handle sin leak.
        conn = self._factory.create_connection()
        try:
            self._save_run_in_conn(run, conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _save_run_in_conn(self, run: DiagnosticRun, conn: sqlite3.Connection) -> None:
        conn.execute(
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
             samples, timestamp, family)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        for p in run.probes:
            conn.execute(
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
                    # Fase 12a.4: familia IP (default 'ipv4' en el modelo).
                    p.family,
                ),
            )

        traceroute_sql = """INSERT INTO traceroute_results
            (run_id, target_provider, culprit_hop_index, hops_json, family)
            VALUES (?, ?, ?, ?, ?)"""
        for t in run.traceroutes:
            conn.execute(
                traceroute_sql,
                (
                    run.run_id,
                    t.target_provider,
                    t.culprit_hop_index,
                    json.dumps([_hop_to_dict(h) for h in t.hops]),
                    # Fase 12a.4: familia IP (default 'ipv4' en el modelo).
                    t.family,
                ),
            )

        if run.active_game_server is not None:
            ags = run.active_game_server
            conn.execute(
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

        # Fase 12a.2: mediciones DNS (opcionales, vacio si la feature off o
        # todos los hosts fallaron). Atomicidad: persistidas en la misma
        # transaccion que el resto del run (Regla 8.4 — sin partial writes).
        dns_sql = """INSERT INTO dns_results
            (run_id, hostname, resolved_ip, outcome, elapsed_ms,
             family, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        # timestamp compartido: el finished_at del run (no hay marca de
        # tiempo por medicion DNS en el modelo; la etapa DNS corre dentro
        # de la corrida y el corte temporal relevante es el fin de run).
        finished_iso = run.finished_at.isoformat()
        for d in run.dns_results:
            conn.execute(
                dns_sql,
                (
                    run.run_id,
                    d.hostname,
                    d.resolved_ip,
                    d.outcome.name,
                    d.elapsed_ms,
                    d.family,
                    d.error,
                    finished_iso,
                ),
            )

        # Fase 12a.3: snapshot de interfaz de red (opcional). Mismo
        # patron atomico (Regla 8.4) — una fila por run si la feature
        # inspec_interface estaba habilitada y el inspector devolvio un
        # snapshot (contrato del inspector: nunca devuelve None).
        snap = run.interface_snapshot
        if snap is not None:
            conn.execute(
                """INSERT INTO interface_snapshots
                   (run_id, type, name, is_default_route, wifi_ssid,
                    wifi_signal_dbm, error, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    snap.type.name,
                    snap.name,
                    1 if snap.is_default_route else 0,
                    snap.wifi_ssid,
                    snap.wifi_signal_dbm,
                    snap.error,
                    finished_iso,
                ),
            )


def _hop_to_dict(hop: TracerouteHop) -> dict[str, Any]:
    return {
        "hop_number": hop.hop_number,
        "ip": hop.ip,
        "hostname": hop.hostname,
        "rtt_ms": hop.rtt_ms,
        "responded": hop.responded,
    }
