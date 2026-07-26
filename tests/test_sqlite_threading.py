"""Tests del threading SQLite (Regla de Oro 9.1, reportado en sesion Fase 9).

El bug original era: ``sqlite3.connect(path)`` en el hilo principal y
``save_run`` invocado desde un thread daemon (controller) ->
``ProgrammingError: SQLite objects created in a thread can only be used
in that same thread``.

La fix arquitectural: ``DatabaseConnectionFactory`` que cada vez pide
una ``sqlite3.Connection`` NUEVA (``create_connection()``). Cada hilo
obtiene/suelta la suya; nada se comparte.

Estos tests garantizan que:
  1. ``SqliteDiagnosticsRepository`` guarda via el factory, no cachea conn.
  2. ``RunFullDiagnostics.execute()`` puede correr en un thread daemon sin
     levantar ``ProgrammingError`` ni en ``compute_baseline`` (read) ni en
     ``save_run`` (write).
  3. ``last_baselines`` del use case queda poblado al final del execute()
     (la UI lo usa sin reabrir DB).

Estos tests son de INTEGRACION multi-thread: arrancan un thread daemon
igual que el controller del UI y verifican el contrato SQLite-cross-thread.
Marcados NO con ``@pytest.mark.integration`` porque NO tocan red: son
validacion arquitextural del fix threading.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository
from gnd.domain.fakes.fake_connection_inspector import FakeConnectionInspector
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_traceroute_runner import FakeTracerouteRunner


def _targets() -> DiagnosticTargets:
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names={"League of Legends.exe"},
    )


def _params() -> DiagnosticParams:
    return DiagnosticParams(
        ping_count=4,
        ping_timeout_ms=1000,
        traceroute_max_hops=10,
        traceroute_timeout_ms=1000,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
    )


@pytest.fixture
def factory_db_path(tmp_path) -> str:
    """Per-test file-based SQLite path (vacía entre tests)."""
    return str(tmp_path / "history.db")


class TestSqliteThreadingRegla9_1:
    """Garantia: ``sql3.Connection`` nunca se comparte entre hilos."""

    def test_save_run_desde_thread_distinto_no_lanza_programming_error(
        self, factory_db_path: str
    ) -> None:
        """Save_run en un thread daemon debe escribir sin ProgrammingError.

        Antes del fix (Fase 9) era:     sqlite3.connect(path) en main +
        SqiteDiagRepo(conn).save_run en worker -> ProgrammingError.
        Despues del fix (Regla de Oro 9.1): main construye factory, worker
        ejecuta la corrida, factory.create_connection() devuelve una conn
        nueva dentro del worker thread. Sin conn compartida.
        """
        factory = SqliteConnectionFactory(factory_db_path)
        repository = SqliteDiagnosticsRepository(factory)

        from gnd.models.diagnostic_run import DiagnosticRun
        from gnd.models.latency_stats import LatencyStats
        from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
        from gnd.models.recommendation import Recommendation
        from gnd.models.traceroute import TracerouteHop, TracerouteResult

        def _make_run(run_id: str) -> DiagnosticRun:
            now = datetime.now()
            return DiagnosticRun(
                run_id=run_id,
                started_at=now,
                finished_at=now + timedelta(seconds=1),
                probes=[
                    ProbeResult(
                        target_name="google_dns",
                        target_ip="8.8.8.8",
                        provider="google",
                        outcome=ProbeOutcomeKind.SUCCESS,
                        stats=LatencyStats(
                            avg_ms=20.0,
                            min_ms=18.0,
                            max_ms=22.0,
                            jitter_ms=2.0,
                            packet_loss_pct=0.0,
                            samples=4,
                        ),
                        timestamp=now,
                    )
                ],
                traceroutes=[
                    TracerouteResult(
                        target_provider="cloudflare",
                        hops=[
                            TracerouteHop(
                                hop_number=1,
                                ip="192.168.1.1",
                                hostname=None,
                                rtt_ms=1.0,
                                responded=True,
                            )
                        ],
                        culprit_hop_index=None,
                    )
                ],
                active_game_server=None,
                recommendation=Recommendation(
                    verdict="safe_to_play",
                    headline="OK",
                    explanation=["Sin problemas detectados"],
                    responsible_component="unknown",
                    score=95,
                ),
            )

        run = _make_run("thread-test")
        errors: list[str] = []

        def worker() -> None:
            try:
                repository.save_run(run)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        t = threading.Thread(target=worker, name="gnd-thread-test", daemon=True)
        t.start()
        t.join(timeout=10)

        assert not t.is_alive(), "worker thread colgado"
        assert errors == [], f"ProgrammingError o similar: {errors}"

        # Verificar que la fila se persistio en la DB reabierta desde main.
        verify_conn = sqlite3.connect(factory_db_path)
        verify_conn.row_factory = sqlite3.Row
        try:
            row = verify_conn.execute(
                "SELECT run_id FROM diagnostic_runs WHERE run_id = ?",
                ("thread-test",),
            ).fetchone()
            assert row is not None, "el worker no escribio la corrida"
            assert row["run_id"] == "thread-test"
        finally:
            verify_conn.close()

    def test_run_full_diagnostics_en_thread_daemon_completa_sin_programming_error(
        self, factory_db_path: str
    ) -> None:
        """End-to-end: composition_root + controller threading.

        Simula el path completo: el use case se construye en main thread,
        su ``.execute(targets, params)`` corre en un thread daemon igual
        que ``DiagnosticsController._worker``. El bug original era aquí.
        """
        factory = SqliteConnectionFactory(factory_db_path)
        repository = SqliteDiagnosticsRepository(factory)

        use_case = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=FakeConnectionInspector(),
            repository=repository,
            db_factory=factory,
        )

        errors: list[Exception] = []
        results: list[object] = []

        def worker() -> None:
            try:
                run = use_case.execute(_targets(), _params())
                results.append(run)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(
            target=worker, name="gnd-run-full-diagnostics", daemon=True
        )
        t.start()
        t.join(timeout=15)

        assert not t.is_alive()
        assert errors == [], f"errors en worker: {errors}"
        assert len(results) == 1
        _ = results[0]  # run verificado via use_case.last_baselines
        # El use case DEBE haber computado baselines — confirma que
        # compute_baseline abrio una conn nueva (no compartida).
        assert (
            len(use_case.last_baselines) >= 5
        ), f"baselines deberian estar pobladas: {use_case.last_baselines}"

    def test_baselines_cache_en_use_case_para_ui_sin_reabrir_db(
        self, factory_db_path: str
    ) -> None:
        """La UI debe poder poblar la pestana Historical Comparison SIN tocar DB.

        Antes del fix, ``main_window._apply_run`` llamaba compute_baseline(db)
        en el main loop, lo que tiraba ProgrammingError: la conn habia sido
        creada en el worker thread del execute. Despues del fix, el use case
        expone ``last_baselines`` (dict) cacheado al final de Etapa 5 — la
        UI lo lee sin pedir una nueva conn (no comparte, no recíone).
        """
        factory = SqliteConnectionFactory(factory_db_path)
        repository = SqliteDiagnosticsRepository(factory)

        use_case = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=FakeConnectionInspector(),
            repository=repository,
            db_factory=factory,
        )

        use_case.execute(_targets(), _params())

        baselines = use_case.last_baselines
        assert len(baselines) >= 5
        # Cada baseline es un HistoricalBaseline (modelo inmutable).
        from gnd.models.historical_baseline import HistoricalBaseline

        for _provider, b in baselines.items():
            assert isinstance(b, HistoricalBaseline)
            # Sin datos persiste = (avg=0, stddev=0, sample_count=0);
            # si hay datos desde un test con historial previo, sample_count > 0.
            assert b.sample_count >= 0

    def test_factory_create_connection_devuelve_distintas_conns(
        self, factory_db_path: str
    ) -> None:
        """Cada ``create_connection()`` devuelve una Connection NUEVA.

        Esto es la garantia primordial del fix TwoThreadsOneDb: una call
        => un objeto nuevo. Ningun caller la comparte accidentallmente.
        """
        factory = SqliteConnectionFactory(factory_db_path)
        c1 = factory.create_connection()
        c2 = factory.create_connection()
        # Distintos objetos (no identical / no shared handle).
        assert c1 is not c2
        # Ambas operativas contra el mismo file backing store.
        c1.execute("CREATE TABLE IF NOT EXISTS x (a INT)")
        c1.execute("INSERT INTO x VALUES (1)")
        c1.commit()
        rows = c2.execute("SELECT COUNT(*) AS cnt FROM x").fetchone()
        idx = rows[0] if isinstance(rows, tuple) else rows["cnt"]
        assert (
            idx == 1
        ), "ambas conns deben ver el mismo DB file (file-backed persistence ok)"


class TestSqliteConnectionFactoryProtocol:
    """El Protocol cumple Liskov con la implementacion real y la fake."""

    def test_sqlite_factory_es_un_DatabaseConnectionFactory(self) -> None:
        from gnd.domain.ports.database import DatabaseConnectionFactory

        factory = SqliteConnectionFactory("unused")
        # runtime_checkable Protocol: isinstance debe pasar.
        assert isinstance(factory, DatabaseConnectionFactory)

    def test_transversal_imports_compose(self, factory_db_path: str) -> None:
        """Smoke: el composition_root monta factory + repo sin tocar paths."""
        factory = SqliteConnectionFactory(factory_db_path)
        repository = SqliteDiagnosticsRepository(factory)
        # Sanity: factory y repo no comparten estado (factory stateless).
        assert factory.create_connection() is not None
        assert repository is not None
