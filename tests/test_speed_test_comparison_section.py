"""Tests del SpeedTestComparisonSection UI (Fase 12b.5).

Smoke tests que verifican:
- La sección se crea sin errores (con tkinter headless).
- update_state() con varios estados no lanza excepciones.
- Backwards-compat: MainWindow sin kwargs Speed Test funciona igual.

# FLAKYKNOWN (lesson 12b.4.2): estos tests abren `tk.Tk()` real. Bajo
# carga (suite completa corrida desde PowerShell en Windows), `tk.Tk()`
# ocasionalmente falla con `_tkinter.TclError: Can't find a usable
# init.tcl` — race en el directory scan de Tcl/Tk. Pasa aislado o en
# corridas cortas; falla ~10% en suite completa. NO es bug del producto.
# Ver lessons_learned.md #12b.4.2 para workaround.
"""

from __future__ import annotations

import pytest


class TestSpeedTestComparisonSection:
    @pytest.fixture(autouse=True)
    def _skip_if_no_tk(self):
        pytest.importorskip("tkinter", reason="tkinter no disponible")

    def test_se_crea_sin_errores(self):
        import tkinter as tk

        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)
            assert sec is not None
            sec.update_state({})
        finally:
            root.destroy()

    def test_update_state_sin_result(self):
        import tkinter as tk

        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)
            sec.update_state({})  # estado vacío inicial
            sec.update_state({"is_running": False})
        finally:
            root.destroy()

    def test_update_state_running(self):
        import tkinter as tk

        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)
            sec.update_state({"is_running": True})
        finally:
            root.destroy()

    def test_update_state_error(self):
        import tkinter as tk

        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)
            sec.update_state({"_error": "speedtest no encontrado"})
        finally:
            root.destroy()

    def test_update_state_result_unavailable(self):
        import tkinter as tk

        from gnd.models.speed_test import SpeedTestComparisonResult, SpeedTestResult
        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)
            unavailable = SpeedTestResult(
                latency_ms=0.0,
                jitter_ms=0.0,
                download_mbps=0.0,
                upload_mbps=0.0,
                packet_loss_pct=0.0,
                server_name="Unavailable",
                server_country="Unknown",
                isp="Unknown",
            )
            result = SpeedTestComparisonResult(
                baseline=unavailable,
                comparison=unavailable,
                deltas=[],
                overall_verdict="unavailable",
                verdict_explanation=["speedtest no encontrado"],
                speed_test_controller_available=False,
            )
            sec.update_state({"result": result})
        finally:
            root.destroy()

    def test_update_state_result_improved(self):
        import tkinter as tk

        from gnd.models.speed_test import (
            SpeedTestComparisonResult,
            SpeedTestDelta,
            SpeedTestResult,
        )
        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)
            baseline = SpeedTestResult(
                latency_ms=15.0,
                jitter_ms=2.0,
                download_mbps=100.0,
                upload_mbps=50.0,
                packet_loss_pct=0.0,
                server_name="Server A",
                server_country="Country",
                isp="ISP",
            )
            comparison = SpeedTestResult(
                latency_ms=20.0,
                jitter_ms=3.0,
                download_mbps=90.0,
                upload_mbps=45.0,
                packet_loss_pct=0.5,
                server_name="Server B",
                server_country="Country",
                isp="ISP",
            )
            delta = SpeedTestDelta(
                metric_name="latency_ms",
                baseline_value=15.0,
                comparison_value=20.0,
                delta=5.0,
                delta_pct=33.3,
            )
            result = SpeedTestComparisonResult(
                baseline=baseline,
                comparison=comparison,
                deltas=[delta],
                overall_verdict="improved",
                verdict_explanation=["Speed test completado"],
            )
            sec.update_state({"result": result})
        finally:
            root.destroy()

    # ── Test de regresión: bug 2 (template con variable cruzada) ──

    def test_bug2_score_label_muestra_score_no_server_name(self):
        """REGRESIÓN bug 2: la línea 'Diagnóstico: score=...' estaba usando
        `result.baseline.server_name` (nombre del servidor de speed test,
        ej. 'Movistar Colombia') en lugar del score numérico del diagnóstico.

        El template roto mostraba: 'Diagnóstico: score=Movistar'
        El template correcto muestra: 'Diagnóstico: score=86/100,
        verdict=safe_to_play'.

        Validación: el label muestra el score del diagnóstico (int 0-100)
        y el verdict textual, NO el nombre del servidor de speed test.
        """
        import tkinter as tk

        from gnd.models.speed_test import (
            SpeedTestComparisonResult,
            SpeedTestResult,
        )
        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)

            # Speed test con server_name distintivo para detectar el bug.
            speed_result = SpeedTestResult(
                latency_ms=10.0,
                jitter_ms=1.0,
                download_mbps=500.0,
                upload_mbps=50.0,
                packet_loss_pct=0.0,
                server_name="ServidorEngañoso Colombia",
                server_country="Colombia",
                isp="ISP Test",
            )

            result = SpeedTestComparisonResult(
                baseline=speed_result,
                comparison=speed_result,
                deltas=[],
                overall_verdict="improved",
                verdict_explanation=["Speed test completado"],
                diagnostic_score=86,
                diagnostic_verdict="safe_to_play",
            )
            sec.update_state({"result": result})

            # El label DEBE contener el score numérico, no el server_name.
            score_text = sec._score_label.cget("text")
            assert (
                "score=86/100" in score_text
            ), f"el label debe mostrar score=86/100, got: {score_text!r}"
            assert (
                "verdict=safe_to_play" in score_text
            ), f"el label debe mostrar verdict=safe_to_play, got: {score_text!r}"
            # NEGATIVO: no debe contener el nombre del server de speed test.
            assert "ServidorEngañoso" not in score_text, (
                f"REGRESIÓN bug 2: el label usa server_name en lugar del score: "
                f"{score_text!r}"
            )
            assert "Colombia" not in score_text, (
                f"REGRESIÓN bug 2: el label usa server_country en lugar del score: "
                f"{score_text!r}"
            )
        finally:
            root.destroy()

    def test_bug2_score_label_vacio_si_diagnostic_score_es_none(self):
        """Caso unavailable: si el resultado no trae score del diagnóstico
        (no se corrió), el label queda vacío en lugar de mostrar basura.
        """
        import tkinter as tk

        from gnd.models.speed_test import (
            SpeedTestComparisonResult,
            SpeedTestResult,
        )
        from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection

        root = tk.Tk()
        try:
            sec = SpeedTestComparisonSection(root)

            unavailable_result = SpeedTestResult(
                latency_ms=0.0,
                jitter_ms=0.0,
                download_mbps=0.0,
                upload_mbps=0.0,
                packet_loss_pct=0.0,
                server_name="Unavailable",
                server_country="Unknown",
                isp="Unknown",
            )
            # NOTE: no pasamos diagnostic_score ni diagnostic_verdict → None
            result = SpeedTestComparisonResult(
                baseline=unavailable_result,
                comparison=unavailable_result,
                deltas=[],
                overall_verdict="unavailable",
                verdict_explanation=["speedtest no encontrado"],
                speed_test_controller_available=False,
            )
            sec.update_state({"result": result})

            score_text = sec._score_label.cget("text")
            assert score_text == "", (
                f"label debe ser vacío cuando no hay score de diagnóstico, "
                f"got: {score_text!r}"
            )
        finally:
            root.destroy()


class TestMainWindowSpeedTestBackwardsCompat:
    """Tests de backwards-compat: MainWindow sin kwargs Speed Test."""

    def test_mainwindow_sin_kwargs_speed_test(self):
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
        # Pre-12b.5 callers: solo los kwargs originales
        window = MainWindow(use_case=use_case, targets=targets, params=params)
        try:
            # El botón Speed Test existe pero está disabled
            assert window._speed_test_button is not None
            assert str(window._speed_test_button.cget("state")) == "disabled"
        finally:
            window._root.destroy()

    def test_mainwindow_con_speed_test_kwargs(self):
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.application.speed_test_comparison import (
            SpeedTestComparisonUseCase,
        )
        from gnd.config import SpeedTest as SpeedTestSettings
        from gnd.domain.fakes import (
            FakeConnectionInspector,
            FakeDiagnosticsRepository,
            FakePingRunner,
            FakeSpeedTestController,
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
        speed_test_controller = FakeSpeedTestController()
        speed_test_comparison = SpeedTestComparisonUseCase(
            diagnostics_use_case=use_case,
            speed_test_controller=speed_test_controller,
        )
        speed_test_settings = SpeedTestSettings(enabled=True)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            speed_test_controller=speed_test_controller,
            speed_test_comparison=speed_test_comparison,
            speed_test_settings=speed_test_settings,
        )
        try:
            # Botón habilitado porque settings.enabled=True y speed_test_controller.available
            assert str(window._speed_test_button.cget("state")) == "normal"
        finally:
            window._root.destroy()

    def test_mainwindow_boton_disabled_si_settings_disabled(self):
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.application.speed_test_comparison import (
            SpeedTestComparisonUseCase,
        )
        from gnd.config import SpeedTest as SpeedTestSettings
        from gnd.domain.fakes import (
            FakeConnectionInspector,
            FakeDiagnosticsRepository,
            FakePingRunner,
            FakeSpeedTestController,
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
        speed_test_controller = FakeSpeedTestController()
        speed_test_comparison = SpeedTestComparisonUseCase(
            diagnostics_use_case=use_case,
            speed_test_controller=speed_test_controller,
        )
        # settings.enabled=False
        speed_test_settings = SpeedTestSettings(enabled=False)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            speed_test_controller=speed_test_controller,
            speed_test_comparison=speed_test_comparison,
            speed_test_settings=speed_test_settings,
        )
        try:
            # Botón disabled porque settings.enabled=False
            assert str(window._speed_test_button.cget("state")) == "disabled"
        finally:
            window._root.destroy()
