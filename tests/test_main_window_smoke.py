"""Smoke test del MainWindow (sin entrar a mainloop).

DoD Fase 9: el usuario debe poder ejecutar un diagnóstico y ver el
resultado sin que la ventana se congele, con las 5 secciones visibles
y pobladas. Este test simula ese flujo sin display bloqueante.
"""

from __future__ import annotations

from datetime import datetime

import pytest

skip_no_tk = pytest.mark.skipif(
    not pytest.importorskip("tkinter", reason="tkinter no disponible").__class__,
    reason="Smoke test requiere tkinter",
)


class TestMainWindowSmoke:
    def test_mainwindow_crea_las_5_secciones(self):
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
        )
        from gnd.domain.fakes.fake_connection_inspector import (
            FakeConnectionInspector,
        )
        from gnd.domain.fakes.fake_diagnostics_repository import (
            FakeDiagnosticsRepository,
        )
        from gnd.domain.fakes.fake_ping_runner import FakePingRunner
        from gnd.domain.fakes.fake_traceroute_runner import (
            FakeTracerouteRunner,
        )
        from gnd.ui.charts_section import ChartsSection
        from gnd.ui.main_window import MainWindow
        from gnd.ui.sections import (
            CurrentStatusSection,
            HistoricalComparisonSection,
            NetworkTestsSection,
            RecommendationsSection,
            RouteAnalysisSection,
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

        # Un caso de uso con fakes para que la UI no toque red.
        from gnd.application.run_full_diagnostics import RunFullDiagnostics

        use_case = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=FakeConnectionInspector(),
            repository=FakeDiagnosticsRepository(),
            db_factory=None,
        )

        window = MainWindow(use_case=use_case, targets=targets, params=params)

        # Las 5 secciones son instancias de las clases esperadas.
        assert isinstance(window._sec_current, CurrentStatusSection)
        assert isinstance(window._sec_tests, NetworkTestsSection)
        assert isinstance(window._sec_route, RouteAnalysisSection)
        assert isinstance(window._sec_hist, HistoricalComparisonSection)
        assert isinstance(window._sec_rec, RecommendationsSection)

        # Fase 10: la sexta pestaña ChartsSection también existe.
        assert isinstance(window._sec_charts, ChartsSection)

        # Las secciones son widgets (children del root).
        n_children = len(window._root.winfo_children())
        assert n_children >= 2  # al menos top frame + notebook

        # Cerrar limpiamente (sin mainloop).
        window._root.destroy()

    def test_charts_tab_refresh_renderiza_5_graficos_con_fake_source(self):
        """Fase 10: la pestaña Charts refresh renderiza los 5 gráficos
        con datos sintéticos via FakeSeriesDataSource (sin DB real).

        No valida visualmente los gráficos (eso cubre test_visualization_charts),
        solo que el widget ChartsSection cumple el contrato de refresh.
        """
        import matplotlib

        matplotlib.use("Agg")  # headless, no abre ventana

        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.domain.fakes import (
            FakeConnectionInspector,
            FakeDiagnosticsRepository,
            FakePingRunner,
            FakeSeriesDataSource,
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

        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            series_source=FakeSeriesDataSource(),
        )

        # Refresh directo: debe renderizar sin excepción y figures se
        # guardan internamente (uno por gráfico).
        window._sec_charts.refresh()
        assert len(window._sec_charts._figures) == 5

        # Refrescar de nuevo debe vaciar la lista previa (no acumular).
        window._sec_charts.refresh()
        assert len(window._sec_charts._figures) == 5

        window._root.destroy()

    def test_apply_run_pobla_todas_las_secciones_sin_excepcion(self):
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.domain.fakes.fake_connection_inspector import (
            FakeConnectionInspector,
        )
        from gnd.domain.fakes.fake_diagnostics_repository import (
            FakeDiagnosticsRepository,
        )
        from gnd.domain.fakes.fake_ping_runner import FakePingRunner
        from gnd.domain.fakes.fake_traceroute_runner import (
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
        window = MainWindow(use_case=use_case, targets=targets, params=params)

        try:
            run = use_case.execute(targets, params)
            # Aplica el resultado como lo haria el callback on_result.
            window._apply_run(run)
            # Si llegamos aca, las 5 secciones se actualizaron sin crashear.
            assert run.recommendation is not None
            assert run.recommendation.verdict
        finally:
            window._root.destroy()

    def test_anomalias_de_probes_y_hops_visibles_en_secciones(self):
        """Regla fija 2026-07-25: anomalias DEBEN aparecer en la UI."""

        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.domain.fakes.fake_connection_inspector import (
            FakeConnectionInspector,
        )
        from gnd.domain.fakes.fake_diagnostics_repository import (
            FakeDiagnosticsRepository,
        )
        from gnd.domain.fakes.fake_ping_runner import FakePingRunner
        from gnd.domain.fakes.fake_traceroute_runner import (
            FakeTracerouteRunner,
        )
        from gnd.ui.main_window import MainWindow

        # Probe con packet_loss > 0 — debe aparecer en NetworkTestsSection
        # y RecommendationsSection.
        pierdo_rtt_runner = FakePingRunner()
        from gnd.models.latency_stats import LatencyStats
        from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult

        pierdo_rtt_runner.set_result(
            "1.1.1.1",
            ProbeResult(
                target_name="cloudflare",
                target_ip="1.1.1.1",
                provider="cloudflare",
                outcome=ProbeOutcomeKind.SUCCESS,
                stats=LatencyStats(
                    avg_ms=20.0,
                    min_ms=18.0,
                    max_ms=22.0,
                    jitter_ms=2.0,
                    packet_loss_pct=5.0,  # anomalia: > 3% critico
                    samples=4,
                ),
                timestamp=datetime.now(),
            ),
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
            ping_runner=pierdo_rtt_runner,
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=FakeConnectionInspector(),
            repository=FakeDiagnosticsRepository(),
            db_factory=None,
        )
        window = MainWindow(use_case=use_case, targets=targets, params=params)
        try:
            run = use_case.execute(targets, params)
            window._apply_run(run)

            # Confirmar que la seccion NetworkTests contiene la string
            # de la anomalia (probe con 5% loss).
            network_tests_text = window._sec_tests._body.get("1.0", "end")
            assert (
                "anoma" in network_tests_text.lower()
                or "perdid" in network_tests_text.lower()
            )

            rec_text = window._sec_rec._body.get("1.0", "end")
            assert "perdid" in rec_text.lower() or "loss" in rec_text.lower()
        finally:
            window._root.destroy()
