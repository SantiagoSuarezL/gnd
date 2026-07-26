"""Repro del bug SQLite threading (corregido por Regla de Oro 9.1, Fase 9).

Simula el path de produccion EXACTO: composition_root construye el
wiring en el hilo principal, el controller lanza el ``execute()`` del
caso de uso en un thread daemon.

Este script SOLO prueba el camino post-fix (factory-based). Para reproducir
el bug original, ver ``scripts/repro_thread_bug_vulnerable.py`` (commit
pre-fix, archivado para referencia historica).

Verificaciones:
  1. ``compute_baseline`` (read, Etapa 5) corre en worker thread sin
     ``sqlite3.ProgrammingError``.
  2. ``save_run`` (write, Etapa 7) corre en worker thread sin
     ``sqlite3.ProgrammingError``.
  3. ``last_baselines`` del use case queda poblado para que ``main_window``
     pueda poblar la seccion 4 sin tocar DB en main loop.
  4. La conn del main thread nunca se usa en worker thread (cada hilo
     tiene la suya).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import traceback

sys.path.insert(0, "src")

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


def main() -> None:
    """Flux: main thread (composition_root) + worker thread (controller)."""
    factory_path = os.path.join(tempfile.gettempdir(), "gnd_repro_thread_fixed.db")
    if os.path.exists(factory_path):
        os.remove(factory_path)
    factory = SqliteConnectionFactory(factory_path)
    repository = SqliteDiagnosticsRepository(factory)

    targets = DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names={"League of Legends.exe"},
    )
    params = DiagnosticParams(
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

    use_case = RunFullDiagnostics(
        ping_runner=FakePingRunner(),
        traceroute_runner=FakeTracerouteRunner(),
        connection_inspector=FakeConnectionInspector(),
        repository=repository,
        db_factory=factory,
    )

    threads_seen: dict[str, str] = {}
    error_box: list[str] = []
    result_box: list[object] = []

    def worker() -> None:
        threads_seen["worker"] = (
            f"thread_id={threading.get_ident()} name={threading.current_thread().name}"
        )
        try:
            run = use_case.execute(targets, params)
            result_box.append(run)
        except Exception as exc:  # noqa: BLE001
            error_box.append(f"{type(exc).__name__}: {exc}")
            error_box.append(traceback.format_exc())

    threads_seen["main"] = (
        f"thread_id={threading.get_ident()} name={threading.current_thread().name}"
    )

    t = threading.Thread(target=worker, name="gnd-diagnostics-repro", daemon=True)
    t.start()
    t.join(timeout=15)

    if error_box:
        print("=== EXCEPCION EN THREAD DAEMON ===")
        print(error_box[0])
        print()
        print(error_box[1])
        sys.exit(1)

    if result_box:
        run = result_box[0]
        baselines = use_case.last_baselines

        print("=== OK: smoke threading post-fix ===")
        print(f"thread main         : {threads_seen['main']}")
        print(f"thread worker       : {threads_seen['worker']}")
        print(f"run_id              : {run.run_id}")
        print(f"probes              : {len(run.probes)}")
        print(f"traceroutes         : {len(run.traceroutes)}")
        print(f"baselines computed  : {len(baselines)}")
        print(
            f"recommendation      : verdict={run.recommendation.verdict} "
            f"score={run.recommendation.score}/100"
        )

        # Verificar persistencia: el worker thread escribio en la DB
        # via factory. Reabrimos la DB desde main y contamos los rows.
        verify_conn = sqlite3.connect(factory_path)
        verify_conn.row_factory = sqlite3.Row
        try:
            run_count = verify_conn.execute(
                "SELECT COUNT(*) AS cnt FROM diagnostic_runs"
            ).fetchone()["cnt"]
            probe_count = verify_conn.execute(
                "SELECT COUNT(*) AS cnt FROM probe_results"
            ).fetchone()["cnt"]
        finally:
            verify_conn.close()
        print(f"DB diagnostic_runs  : {run_count} (esperado >= 1)")
        print(f"DB probe_results    : {probe_count} (esperado >= 5)")

        # Cleanup
        try:
            os.remove(factory_path)
        except OSError:
            pass

        if run_count >= 1 and probe_count >= 5 and len(baselines) >= 5:
            print()
            print(
                ">>> FIX VERIFICADO: thread worker escribio en DB, "
                "main thread reabria limpia."
            )
            sys.exit(0)
        print()
        print(">>> Algo esta fuera de lo esperado.")
        sys.exit(2)

    print("TIMEOUT inesperado")
    sys.exit(3)


if __name__ == "__main__":
    main()
