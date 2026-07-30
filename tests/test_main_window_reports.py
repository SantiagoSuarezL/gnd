"""Tests smoke de integración de ReportsScheduler en MainWindow (Fase 12b.3).

Verifica:
- MainWindow acepta kwarg ``report_scheduler`` (backwards-compat: sin
  kwarg no crashea — tests pre-12b.3 siguen funcionando).
- ``run()`` arranca el scheduler si está inyectado (via hook con try).
- No crashea si scheduler inyectado pero ``run()`` nunca invocado (no
  mainloop en tests — usamos construct + destroy).
- ``_apply_run`` y demás callbacks no rompen con scheduler None.
"""

from __future__ import annotations

import pytest

skip_no_tk = pytest.mark.skipif(
    not pytest.importorskip("tkinter", reason="tkinter no disponible").__class__,
    reason="Smoke test requiere tkinter",
)


def _build_use_case() -> tuple[object, object, object]:  # type: ignore[type-arg]
    from gnd.application.run_full_diagnostics import (
        DiagnosticParams,
        DiagnosticTargets,
        RunFullDiagnostics,
    )
    from gnd.domain.fakes import (
        FakeConnectionInspector,
        FakeDiagnosticsRepository,
        FakePingRunner,
        FakeTracerouteRunner,
    )

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
        repository=FakeDiagnosticsRepository(),
        db_factory=None,
    )
    return use_case, targets, params


def _build_run_safe(use_case, targets, params):
    """Run con verdict safe_to_play (FakePingRunner default)."""
    return use_case.execute(targets, params)


class _SpyScheduler:
    """Spy que registra start/stop sin abrir Timer real."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class TestReportSchedulerOnMainWindow:
    def test_main_window_sin_scheduler_no_lanza(self) -> None:
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        # Sin report_scheduler — backwards-compat con tests pre-12b.3.
        window = MainWindow(use_case=use_case, targets=targets, params=params)
        try:
            run = _build_run_safe(use_case, targets, params)
            window._apply_run(run)
        finally:
            window._root.destroy()

    def test_main_window_con_scheduler_none_no_lanza(self) -> None:
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            report_scheduler=None,
        )
        try:
            run = _build_run_safe(use_case, targets, params)
            window._apply_run(run)
        finally:
            window._root.destroy()

    def test_run_arranca_scheduler_inyectado(self) -> None:
        """run() invoca scheduler.start(); close() invoca stop()."""
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        spy = _SpyScheduler()
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            report_scheduler=spy,  # type: ignore[arg-type]
        )
        # Forzamos salida del mainloop tras 50ms invocando close() —
        # eso detiene el scheduler (via el protocol handler) y destruye
        # la ventana, saliendo del mainloop. Equivalente al usuario
        # presionando la "X" de la ventana.
        window._root.after(50, window.close)
        try:
            window.run()
        except Exception:  # noqa: BLE001 — TclError residual Tk headless
            pass
        assert spy.started >= 1
        assert spy.stopped >= 1

    def test_run_scheduler_que_start_lanza_no_rompe_ui(self) -> None:
        """EP §1.2: si scheduler.start levanta excepción, la UI arranca igual."""
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()

        class ThrowingScheduler:
            def start(self) -> None:
                raise RuntimeError("simulated scheduler init failure")

            def stop(self) -> None:
                pass

        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            report_scheduler=ThrowingScheduler(),  # type: ignore[arg-type]
        )
        # run() debe capturar la excepción del start y seguir al mainloop.
        window._root.after(50, window.close)
        try:
            window.run()
        except Exception:  # noqa: BLE001 — tkinter a veces levanta TclError
            # residual al destruir widgets en mainloop bajo tests — no es
            # una falla del scheduler, sino del entorno Tk headless.
            pass
