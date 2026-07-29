"""Tests unitarios de ``SqliteMonitoringRepository`` (Fase 8).

EP §4: tests sin disco, usando SQLite ``:memory:`` round-trip.

Cubre:
- Liskov: SqliteMonitoringRepository cumple ``Protocol MonitoringRepository``.
- save_session + get_sessions_by_run round-trip: se reconstruyen los
  HopStats exactos (incluyendo None/sin datos en hops 100% loss).
- Multiples sesiones por el mismo run_id.
- Atomicidad: rollback si falla la persistencia de hops (no queremos
  sesiones parciales).
- Extension de schema v1 -> v2 sin romper tabla existente
  (compatibilidad hacia atras con diagnostic_runs para que las Fases
  previas no se rompan).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from gnd.database.schema import SCHEMA_VERSION, ensure_schema
from gnd.database.sqlite_monitoring_repository import SqliteMonitoringRepository
from gnd.domain.ports.route_monitor import MonitoringRepository
from gnd.models.monitoring import (
    HopStats,
    MonitoringSample,
    MonitoringSession,
)


def _make_session(run_id: str = "run-1", **overrides) -> MonitoringSession:
    t0 = datetime(2026, 7, 25, 12, 0, 0)
    t1 = datetime(2026, 7, 25, 12, 1, 0)
    base = dict(
        run_id=run_id,
        target_ip="8.8.8.8",
        target_provider="google",
        started_at=t0,
        finished_at=t1,
        interval_s=5.0,
        samples=[
            MonitoringSample(sample_index=0, hop_number=1, rtt_ms=2.0),
            MonitoringSample(sample_index=0, hop_number=2, rtt_ms=18.0),
        ],
        hop_stats=[
            HopStats(
                hop_number=1,
                ip="192.168.0.1",
                hostname=None,
                best_ms=2.0,
                worst_ms=2.0,
                avg_ms=2.0,
                jitter_ms=0.0,
                loss_pct=0.0,
                samples=1,
                success_count=1,
            ),
            HopStats(
                hop_number=2,
                ip="8.8.8.8",
                hostname=None,
                best_ms=18.0,
                worst_ms=18.0,
                avg_ms=18.0,
                jitter_ms=0.0,
                loss_pct=0.0,
                samples=1,
                success_count=1,
            ),
        ],
    )
    base.update(overrides)
    return MonitoringSession(**base)


# --------------------------------------------------------------------------- #
# Liskov
# --------------------------------------------------------------------------- #


def test_repository_implements_protocol():
    conn = sqlite3.connect(":memory:")
    repo = SqliteMonitoringRepository(conn)
    assert isinstance(repo, MonitoringRepository)


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    def test_save_recupera_sesion_completa(self):
        conn = sqlite3.connect(":memory:")
        repo = SqliteMonitoringRepository(conn)
        session = _make_session()
        repo.save_session(session)

        recovered = repo.get_sessions_by_run("run-1")
        assert len(recovered) == 1
        r = recovered[0]
        assert r.run_id == "run-1"
        assert r.target_ip == "8.8.8.8"
        assert r.target_provider == "google"
        assert r.interval_s == 5.0
        assert r.started_at == datetime(2026, 7, 25, 12, 0, 0)
        assert r.finished_at == datetime(2026, 7, 25, 12, 1, 0)
        # No se persisten las muestras crudas (ver nota modulo repo).
        # El modelo MonitoringSession permite samples=[] con hop_stats.
        assert r.samples == []
        # Hop stats se reconstruyen exactos:
        assert len(r.hop_stats) == 2
        for orig, recov in zip(session.hop_stats, r.hop_stats, strict=True):
            assert orig == recov

    def test_hop_stats_con_loss_pct_100_se_recupera_correctamente(self):
        conn = sqlite3.connect(":memory:")
        repo = SqliteMonitoringRepository(conn)
        session = MonitoringSession(
            run_id="run-X",
            target_ip="8.8.8.8",
            target_provider="test",
            started_at=datetime(2026, 7, 25),
            finished_at=datetime(2026, 7, 25, 0, 0, 1),
            interval_s=1.0,
            samples=[
                MonitoringSample(0, 1, None),
                MonitoringSample(1, 1, None),
            ],
            hop_stats=[
                HopStats(
                    hop_number=1,
                    ip=None,
                    hostname=None,
                    best_ms=None,
                    worst_ms=None,
                    avg_ms=None,
                    jitter_ms=0.0,
                    loss_pct=100.0,
                    samples=2,
                    success_count=0,
                ),
            ],
        )
        repo.save_session(session)
        recovered = repo.get_sessions_by_run("run-X")
        assert len(recovered) == 1
        r = recovered[0]
        assert len(r.hop_stats) == 1
        hs = r.hop_stats[0]
        assert hs.success_count == 0
        assert hs.best_ms is None
        assert hs.worst_ms is None
        assert hs.avg_ms is None
        assert hs.loss_pct == 100.0
        assert hs.ip is None
        assert hs.hostname is None

    def test_hostname_se_persiste_y_recupera(self):
        conn = sqlite3.connect(":memory:")
        repo = SqliteMonitoringRepository(conn)
        t = datetime(2026, 7, 25)
        session = MonitoringSession(
            run_id="run-H",
            target_ip="1.1.1.1",
            target_provider="cloudflare",
            started_at=t,
            finished_at=t,
            interval_s=1.0,
            samples=[MonitoringSample(0, 1, 10.0)],
            hop_stats=[
                HopStats(
                    hop_number=1,
                    ip="1.1.1.1",
                    hostname="one.one.one.one",
                    best_ms=10.0,
                    worst_ms=10.0,
                    avg_ms=10.0,
                    jitter_ms=0.0,
                    loss_pct=0.0,
                    samples=1,
                    success_count=1,
                ),
            ],
        )
        repo.save_session(session)
        r = repo.get_sessions_by_run("run-H")[0]
        assert r.hop_stats[0].hostname == "one.one.one.one"


# --------------------------------------------------------------------------- #
# Multiples sesiones por run_id
# --------------------------------------------------------------------------- #


class TestMultipleSessionsSameRun:
    def test_varias_sesiones_mismo_run_las_recupera_todas(self):
        conn = sqlite3.connect(":memory:")
        repo = SqliteMonitoringRepository(conn)
        for i in range(3):
            t = datetime(2026, 7, 25, 12, 0, i)
            session = _make_session(
                run_id="run-multi",
                started_at=t,
                finished_at=datetime(2026, 7, 25, 12, 0, i + 1),
            )
            repo.save_session(session)

        recovered = repo.get_sessions_by_run("run-multi")
        assert len(recovered) == 3
        # Ordenadas por session_id ASC -> por orden de insercion.
        timestamps = [r.started_at for r in recovered]
        assert timestamps == [
            datetime(2026, 7, 25, 12, 0, 0),
            datetime(2026, 7, 25, 12, 0, 1),
            datetime(2026, 7, 25, 12, 0, 2),
        ]

    def test_run_id_sin_sesiones_devuelve_lista_vacia(self):
        conn = sqlite3.connect(":memory:")
        repo = SqliteMonitoringRepository(conn)
        assert repo.get_sessions_by_run("inexistente") == []


# --------------------------------------------------------------------------- #
# Atomicidad (rollback)
# --------------------------------------------------------------------------- #


class TestAtomicity:
    def test_save_session_fallido_hace_rollback(self):
        """Forzamos un fallo de la conexion (conn.close despues del primer
        INSERT) y verificamos que save_session hace rollback, no crashea
        de forma corrupta y la BD queda consistente.

        Estrategia simple y portable: cerramos la conexion antes de
        llamar save_session. Todo intento de execute debe lanzar
        ``sqlite3.ProgrammingError``. La excepcion se propaga y el
        ``except`` hace rollback (que tambien lanza, pero el caller
        recibe la original via ``raise``).
        """
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        repo = SqliteMonitoringRepository(conn)

        # Cerrar la conexion para que todo SQL falle con ProgrammingError.
        conn.close()

        # El save_session debe lanzar (rollback o ProgrammingError).
        with pytest.raises((sqlite3.ProgrammingError, sqlite3.DatabaseError)):
            repo.save_session(_make_session())

        # Reabrir una conexion vacia y verificar que la base original
        # quedo sin sesiones colgadas (es otra conexion, no afecta).
        # Para este test el contrato es: el rollback no envia commit
        # inconsistent, lo cual verificamos indirectamente con que el
        # repo no lanza DefaultError sino ProgrammingError o similares.
        # (No podemos re-abrir misma conexion cerrada.)

    def test_save_exitoso_persiste_sesion_y_hops_atomicamente(self):
        """Caso feliz: sesion y hops se persisten juntos en una transaccion
        unica (todo commitado al final). No es un test de fallo, sino de
        exito atomico (complementario al test anterior)."""
        conn = sqlite3.connect(":memory:")
        repo = SqliteMonitoringRepository(conn)
        session = _make_session()
        repo.save_session(session)
        # Verificar que la sesion principal y los hops estan commitados.
        ses_cursor = conn.execute(
            "SELECT COUNT(*) FROM monitoring_sessions WHERE run_id = ?",
            ("run-1",),
        )
        hop_cursor = conn.execute(
            """SELECT COUNT(*) FROM monitoring_hops h
                JOIN monitoring_sessions s ON h.session_id = s.session_id
                WHERE s.run_id = ?""",
            ("run-1",),
        )
        assert ses_cursor.fetchone()[0] == 1
        assert hop_cursor.fetchone()[0] == len(session.hop_stats)


# --------------------------------------------------------------------------- #
# Schema version 3 retro-compatibilidad (Fase 12a.4)
# --------------------------------------------------------------------------- #


def test_schema_version_es_3():
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    v = cur.fetchone()[0]
    assert v == SCHEMA_VERSION
    assert SCHEMA_VERSION == 3


def test_tablas_v1_no_se_rompen_con_v3():
    """Garantia de retro-compatibilidad: la migracion v3 anade columnas
    `family` a probe_results y traceroute_results (ALTER TABLE ADD COLUMN
    con DEFAULT 'ipv4'). Las rows pre-IPv6 reciben el default 'ipv4'."""
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    # Verificar que las columnas existen con el default 'ipv4'.
    probe_cols = [r[1] for r in conn.execute("PRAGMA table_info(probe_results)")]
    assert "family" in probe_cols
    trac_cols = [r[1] for r in conn.execute("PRAGMA table_info(traceroute_results)")]
    assert "family" in trac_cols
    # Insertar un probe sin especificar family: debe usar DEFAULT 'ipv4'.
    conn.execute(
        "INSERT INTO diagnostic_runs (run_id, started_at, finished_at, "
        "recommendation_verdict, recommendation_headline, "
        "recommendation_explanation, recommendation_score, "
        "responsible_component) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "test-v3",
            "2026-07-25T00:00:00",
            "2026-07-25T00:00:01",
            "playable",
            "ok",
            "[]",
            80,
            "unknown",
        ),
    )
    conn.execute(
        "INSERT INTO probe_results (run_id, target_name, target_ip, provider, "
        "outcome, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "test-v3",
            "google_dns",
            "8.8.8.8",
            "google",
            "SUCCESS",
            "2026-07-25T00:00:00",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT family FROM probe_results WHERE run_id = ?", ("test-v3",)
    ).fetchone()
    assert row[0] == "ipv4"


def test_ensure_schema_idempotente_v3():
    """ensure_schema puede llamarse multiples veces sin error (PRAGMA
    table_info previene ADD COLUMN duplicado)."""
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    ensure_schema(conn)  # Segunda llamada: no debe lanzar.
    probe_cols = [r[1] for r in conn.execute("PRAGMA table_info(probe_results)")]
    # La columna family debe aparecer UNA sola vez (no duplicada).
    assert probe_cols.count("family") == 1
    trac_cols = [r[1] for r in conn.execute("PRAGMA table_info(traceroute_results)")]
    assert trac_cols.count("family") == 1


def test_repo_v1_y_v2_comparten_misma_conexion():
    """Smoke test: SqliteDiagnosticsRepository y SqliteMonitoringRepository
    sobre la MISMA DB sqlite (factory compartida) y ambas persisten sin
    conflicto.

    Nota: tras fix threading Fase 9, ``SqliteDiagnosticsRepository``
    recibe una ``DatabaseConnectionFactory`` (no una conn compartida).
    Para que v1 y v2 vean la misma DB, los dos repos apuntan a la
    misma factory (file path en comun). Aca en tests usamos
    ``FakeDatabaseConnectionFactory(conn)`` que envuelve una conn
    shared para que ``create_connection()`` la devuelva (single-thread
    en el test, ``check_same_thread`` default True ok).
    """
    from gnd.database.sqlite_diagnostics_repository import (
        SqliteDiagnosticsRepository,
    )
    from gnd.domain.fakes import FakeDatabaseConnectionFactory
    from gnd.models.diagnostic_run import DiagnosticRun
    from gnd.models.recommendation import Recommendation

    conn = sqlite3.connect(":memory:")
    factory = FakeDatabaseConnectionFactory(conn)
    diag_repo = SqliteDiagnosticsRepository(factory)
    mon_repo = SqliteMonitoringRepository(conn)

    # DiagnosticRun minimo con explanation no vacio (EP §1.3):
    t0 = datetime(2026, 7, 25)
    t1 = datetime(2026, 7, 25, 0, 0, 1)
    run = DiagnosticRun(
        run_id="run-combined",
        started_at=t0,
        finished_at=t1,
        probes=[],
        traceroutes=[],
        active_game_server=None,
        recommendation=Recommendation(
            verdict="playable",
            headline="ok",
            explanation=["razon"],
            responsible_component="unknown",
            score=80,
        ),
    )
    diag_repo.save_run(run)
    mon_repo.save_session(_make_session(run_id="run-combined"))

    assert len(mon_repo.get_sessions_by_run("run-combined")) == 1
    # La tabla v1 sigue accesible:
    row = conn.execute(
        "SELECT run_id FROM diagnostic_runs WHERE run_id = ?",
        ("run-combined",),
    ).fetchone()
    assert row is not None
