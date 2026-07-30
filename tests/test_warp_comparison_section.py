"""Tests del WarpComparisonSection UI (Fase 12b.4).

Smoke tests que verifican:
- La sección se crea sin errores (con tkinter headless).
- update_state() con varios estados no lanza excepciones.
- Las secciones se agregan correctamente al MainWindow.
- El botón WARP aparece y se habilita/deshabilita según config.
- Backwards-compat: MainWindow sin kwargs WARP funciona igual.
"""

from __future__ import annotations

import pytest

skip_no_tk = pytest.mark.skipif(
    not pytest.importorskip("tkinter", reason="tkinter no disponible").__class__,
    reason="UI test requiere tkinter",
)


class TestWarpComparisonSection:
    @pytest.fixture(autouse=True)
    def _skip_if_no_tk(self):
        pytest.importorskip("tkinter", reason="tkinter no disponible")

    def test_se_crea_sin_errores(self):
        import tkinter as tk

        from gnd.ui.warp_comparison_section import WarpComparisonSection

        root = tk.Tk()
        try:
            sec = WarpComparisonSection(root)
            assert sec is not None
            sec.update_state({})
        finally:
            root.destroy()

    def test_update_state_sin_result(self):
        import tkinter as tk

        from gnd.ui.warp_comparison_section import WarpComparisonSection

        root = tk.Tk()
        try:
            sec = WarpComparisonSection(root)
            sec.update_state({})  # estado vacío inicial
            sec.update_state({"is_running": False})
        finally:
            root.destroy()

    def test_update_state_running(self):
        import tkinter as tk

        from gnd.ui.warp_comparison_section import WarpComparisonSection

        root = tk.Tk()
        try:
            sec = WarpComparisonSection(root)
            sec.update_state({"is_running": True})
        finally:
            root.destroy()

    def test_update_state_error(self):
        import tkinter as tk

        from gnd.ui.warp_comparison_section import WarpComparisonSection

        root = tk.Tk()
        try:
            sec = WarpComparisonSection(root)
            sec.update_state({"_error": "warp-cli no encontrado"})
        finally:
            root.destroy()

    def test_update_state_result_unavailable(self):
        import tkinter as tk

        from gnd.models.warp_comparison import WarpComparisonResult
        from gnd.ui.warp_comparison_section import WarpComparisonSection

        root = tk.Tk()
        try:
            sec = WarpComparisonSection(root)
            result = WarpComparisonResult(
                warp_off_run_id="",
                warp_on_run_id="",
                warp_off_score=0.0,
                warp_on_score=0.0,
                score_delta=0.0,
                overall_verdict="unavailable",
                verdict_explanation=["warp-cli no encontrado"],
                warp_controller_available=False,
            )
            sec.update_state({"result": result})
        finally:
            root.destroy()

    def test_update_state_result_improved(self):
        import tkinter as tk

        from gnd.models.warp_comparison import (
            WarpComparisonDelta,
            WarpComparisonResult,
        )
        from gnd.ui.warp_comparison_section import WarpComparisonSection

        root = tk.Tk()
        try:
            sec = WarpComparisonSection(root)
            delta = WarpComparisonDelta(
                metric_name="avg_latency_ms",
                warp_off_value=50.0,
                warp_on_value=40.0,
                delta=-10.0,
                delta_pct=-20.0,
            )
            result = WarpComparisonResult(
                warp_off_run_id="r1",
                warp_on_run_id="r2",
                warp_off_score=70.0,
                warp_on_score=85.0,
                score_delta=15.0,
                provider_deltas={"cloudflare": [delta]},
                overall_verdict="improved",
                verdict_explanation=["WARP mejora el score en 15 puntos"],
                warp_off_duration_ms=10000.0,
                warp_on_duration_ms=11000.0,
            )
            sec.update_state({"result": result})
        finally:
            root.destroy()


class TestMainWindowWarpBackwardsCompat:
    """Tests de backwards-compat: MainWindow sin kwargs WARP."""

    def test_mainwindow_sin_kwargs_warp(self):
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
        from gnd.ui.main_window import MainWindow

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
        # Pre-12b.4 callers: solo los 3 kwargs originales
        window = MainWindow(use_case=use_case, targets=targets, params=params)
        try:
            # El botón WARP existe pero está disabled
            assert window._warp_button is not None
            assert str(window._warp_button.cget("state")) == "disabled"
        finally:
            window._root.destroy()

    def test_mainwindow_con_warp_kwargs(self):
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.application.warp_comparison import (
            WarpComparisonUseCase,
        )
        from gnd.config import WarpComparison as WarpComparisonSettings
        from gnd.domain.fakes import (
            FakeConnectionInspector,
            FakeDiagnosticsRepository,
            FakePingRunner,
            FakeTracerouteRunner,
            FakeWarpController,
        )
        from gnd.ui.main_window import MainWindow

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
        warp_controller = FakeWarpController()
        warp_comparison = WarpComparisonUseCase(
            diagnostics_use_case=use_case,
            warp_controller=warp_controller,
        )
        warp_settings = WarpComparisonSettings(enabled=True)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            warp_controller=warp_controller,
            warp_comparison=warp_comparison,
            warp_settings=warp_settings,
        )
        try:
            # Botón habilitado porque settings.enabled=True y warp_controller.available
            assert str(window._warp_button.cget("state")) == "normal"
        finally:
            window._root.destroy()

    def test_mainwindow_boton_disabled_si_settings_disabled(self):
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.application.warp_comparison import (
            WarpComparisonUseCase,
        )
        from gnd.config import WarpComparison as WarpComparisonSettings
        from gnd.domain.fakes import (
            FakeConnectionInspector,
            FakeDiagnosticsRepository,
            FakePingRunner,
            FakeTracerouteRunner,
            FakeWarpController,
        )
        from gnd.ui.main_window import MainWindow

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
        warp_controller = FakeWarpController()
        warp_comparison = WarpComparisonUseCase(
            diagnostics_use_case=use_case,
            warp_controller=warp_controller,
        )
        # settings.enabled=False
        warp_settings = WarpComparisonSettings(enabled=False)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            warp_controller=warp_controller,
            warp_comparison=warp_comparison,
            warp_settings=warp_settings,
        )
        try:
            # Botón disabled porque settings.enabled=False
            assert str(window._warp_button.cget("state")) == "disabled"
        finally:
            window._root.destroy()
