"""Tests smoke de integracion de notificaciones en MainWindow (Fase 12b.2).

Verifica:
- ``_apply_run`` invoca ``notifier.notify`` cuando ``notify_settings.enabled=True``.
- No invoca cuando ``enabled=False``.
- No invoca cuando ``notifier`` es None (caller no inyectó ninguno).
- ``notify_only_on_issues=True`` suprime la notif cuando verdict=safe_to_play.
- ``notify_only_on_issues=True`` no suprime cuando verdict=serious_issue.
- Backwards-compat: ``MainWindow`` sin `notifier` ni `notify_settings` no crashea.
"""

from __future__ import annotations

import pytest

skip_no_tk = pytest.mark.skipif(
    not pytest.importorskip("tkinter", reason="tkinter no disponible").__class__,
    reason="Smoke test requiere tkinter",
)


def _build_use_case() -> tuple[object, object, object]:  # type: ignore[type-arg]
    """Construye (use_case, targets, params) con fakes — patrón en todos los smoke."""
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


def _build_run_safe_to_play(
    use_case, targets, params
) -> tuple[object, object]:  # type: ignore[type-arg]
    """Ejecuta un run (con FakePingRunner) que termina con verdict safe_to_play."""
    run = use_case.execute(targets, params)
    # FakePingRunner default devuelve probes success — verdict debería ser
    # safe_to_play con score alto.
    return run, run.recommendation


class TestNotificacionOnApplyRun:
    def test_apply_run_con_enabled_true_dispara_notificacion(self) -> None:
        from gnd.config import Notifications
        from gnd.domain.fakes import FakeDesktopNotifier
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        fake_notifier = FakeDesktopNotifier()
        notify_settings = Notifications(enabled=True)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            notifier=fake_notifier,
            notify_settings=notify_settings,
        )
        try:
            run, _rec = _build_run_safe_to_play(use_case, targets, params)
            window._apply_run(run)
            # setEnabled=True: una notificacion debe aparecer.
            assert len(fake_notifier.notifications) == 1
            n = fake_notifier.notifications[0]
            assert n.title.startswith("GND — ")
            assert "Score: " in n.message
        finally:
            window._root.destroy()

    def test_apply_run_con_enabled_false_no_dispara(self) -> None:
        from gnd.config import Notifications
        from gnd.domain.fakes import FakeDesktopNotifier
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        fake_notifier = FakeDesktopNotifier()
        notify_settings = Notifications(enabled=False)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            notifier=fake_notifier,
            notify_settings=notify_settings,
        )
        try:
            run, _ = _build_run_safe_to_play(use_case, targets, params)
            window._apply_run(run)
            assert fake_notifier.notifications == []
        finally:
            window._root.destroy()

    def test_apply_run_sin_notifier_no_lanza(self) -> None:
        """Backwards-compat: MainWindow sin kwargs de notif no rompe."""
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        # Sin `notifier` ni `notify_settings` — defaults None/None.
        window = MainWindow(use_case=use_case, targets=targets, params=params)
        try:
            run, _ = _build_run_safe_to_play(use_case, targets, params)
            # No debe lanzar aunque notifier/notify_settings falten.
            window._apply_run(run)
        finally:
            window._root.destroy()

    def test_apply_run_con_notifier_none_y_settings_set_no_lanza(self) -> None:
        """notifier=None pero notify_settings seteado — no-op silencioso."""
        from gnd.config import Notifications
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        notify_settings = Notifications(enabled=True)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            notifier=None,
            notify_settings=notify_settings,
        )
        try:
            run, _ = _build_run_safe_to_play(use_case, targets, params)
            window._apply_run(run)
        finally:
            window._root.destroy()

    def test_only_issues_true_suprime_safe_to_play(self) -> None:
        from gnd.config import Notifications
        from gnd.domain.fakes import FakeDesktopNotifier
        from gnd.ui.main_window import MainWindow

        use_case, targets, params = _build_use_case()
        fake_notifier = FakeDesktopNotifier()
        notify_settings = Notifications(enabled=True, notify_only_on_issues=True)
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            notifier=fake_notifier,
            notify_settings=notify_settings,
        )
        try:
            run, rec = _build_run_safe_to_play(use_case, targets, params)
            window._apply_run(run)
            # Si el run salió safe_to_play, notif suprimida.
            assert rec.verdict == "safe_to_play"
            assert fake_notifier.notifications == []
        finally:
            window._root.destroy()

    def test_only_issues_true_no_suprime_serious_issue(self) -> None:
        """Un run con verdict serious_issue debe notificar pese a only_issues=True."""
        from datetime import datetime

        # Reusamos el patron del test de anomalias: FakePingRunner custom
        # que devuelve un probe degradado — consiguiendo verdict != safe.
        from gnd.application.run_full_diagnostics import (
            DiagnosticParams,
            DiagnosticTargets,
            RunFullDiagnostics,
        )
        from gnd.config import Notifications
        from gnd.domain.fakes import (
            FakeConnectionInspector,
            FakeDesktopNotifier,
            FakeDiagnosticsRepository,
            FakePingRunner,
            FakeTracerouteRunner,
        )
        from gnd.models.latency_stats import LatencyStats
        from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
        from gnd.ui.main_window import MainWindow

        degraded_runner = FakePingRunner()
        degraded_runner.set_result(
            "1.1.1.1",
            ProbeResult(
                target_name="cloudflare",
                target_ip="1.1.1.1",
                provider="cloudflare",
                outcome=ProbeOutcomeKind.SUCCESS,
                stats=LatencyStats(
                    avg_ms=250.0,
                    min_ms=200.0,
                    max_ms=300.0,
                    jitter_ms=80.0,
                    packet_loss_pct=15.0,  # anomalia critica
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
            ping_runner=degraded_runner,
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=FakeConnectionInspector(),
            repository=FakeDiagnosticsRepository(),
            db_factory=None,
        )
        fake_notifier = FakeDesktopNotifier()
        window = MainWindow(
            use_case=use_case,
            targets=targets,
            params=params,
            notifier=fake_notifier,
            notify_settings=Notifications(enabled=True, notify_only_on_issues=True),
        )
        try:
            run = use_case.execute(targets, params)
            # Sanity check: el verdict no es safe_to_play (algo falló).
            assert run.recommendation.verdict != "safe_to_play"
            window._apply_run(run)
            # only_issues=True + verdict != safe → se notifica.
            assert len(fake_notifier.notifications) == 1
            assert "GND — " in fake_notifier.notifications[0].title
        finally:
            window._root.destroy()
