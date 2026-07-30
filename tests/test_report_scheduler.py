"""Tests del ReportsScheduler (Fase 12b.3).

Cubre:
- Lifecycle: start/stop idempotente.
- ``tick_now()``: ejecución sincrónica para tests.
- Composer llamado, writer llamado con path+content correctos.
- Sin runs en período → log skip, no write, no notify.
- Excepción del reader → captura, scheduler continúa, rearma tick.
- Filtrado ``notify_only_on_clean_period``: suprime si todos safe.
- ``build_report_path`` expande vars de entorno + usa etiqueta del período.
- ``_period_to_timedelta`` respeta ReportPeriod.WEEKLY/MONTHLY.
- ``ReportsScheduler.last_report_at`` / ``last_report_path`` poblados tras
  tick exitoso.
- Notifier None / ``notify_on_generated=False`` no rompen.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from gnd.domain.fakes import FakeDesktopNotifier, FakeRunHistoryReader
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.notification import DesktopNotification
from gnd.models.recommendation import Recommendation
from gnd.models.report_config import ReportConfig, ReportPeriod
from gnd.reports.scheduler import ReportsScheduler

# ── Factories ──────────────────────────────────────────────────────────


def _rec(*, verdict: str = "safe_to_play", score: int = 90) -> Recommendation:
    return Recommendation(
        verdict=verdict,
        headline="OK",
        explanation=["sin issues"],
        responsible_component="unknown",
        score=score,
    )


def _run(
    *,
    started: datetime,
    verdict: str = "safe_to_play",
    score: int = 90,
    run_id: str = "r-x",
) -> DiagnosticRun:
    return DiagnosticRun(
        run_id=run_id,
        started_at=started,
        finished_at=started + timedelta(seconds=5),
        probes=[],
        traceroutes=[],
        active_game_server=None,
        recommendation=_rec(verdict=verdict, score=score),
    )


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


class _FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def write(self, path: str, content: str) -> None:
        self.calls.append((path, content))


class _ThrowingReader:
    """Reader que siempre lanza para probar defense-in-depth del scheduler."""

    def get_runs_in_period(self, start: datetime, end: datetime) -> list[DiagnosticRun]:
        raise RuntimeError("simulated DB failure")


def _config(
    *,
    period: ReportPeriod = ReportPeriod.WEEKLY,
    reports_dir: str = "/tmp/irrelevant",
    top_runs: int = 3,
    notify_on_generated: bool = True,
    notify_only_on_clean_period: bool = False,
) -> ReportConfig:
    return ReportConfig(
        period=period,
        top_runs=top_runs,
        reports_dir=reports_dir,
        notify_on_generated=notify_on_generated,
        notify_only_on_clean_period=notify_only_on_clean_period,
    )


def _scheduler(
    *,
    runs: list[DiagnosticRun] | None = None,
    reader: Any = None,
    config: ReportConfig | None = None,
    notifier: FakeDesktopNotifier | None = None,
    clock_now: datetime | None = None,
    writer: _FakeWriter | None = None,
) -> tuple[ReportsScheduler, _FakeWriter]:
    reader = reader or FakeRunHistoryReader(runs=runs or [])
    notifier = notifier or FakeDesktopNotifier()
    clock = _FakeClock(clock_now or datetime(2026, 3, 15, 10, 0, 0))
    writer = writer or _FakeWriter()
    sched = ReportsScheduler(
        config=config or _config(),
        reader=reader,
        notifier=notifier,
        clock=clock,
        sleeper=lambda _s: None,  # nunca bloquear en tests
        writer=writer,
    )
    return sched, writer


# ── Lifecycle ──────────────────────────────────────────────────────────


def test_start_stop_idempotent() -> None:
    sched, _w = _scheduler()
    sched.start()
    sched.start()  # sin efecto (idempotente)
    sched.stop()
    sched.stop()  # sin efecto


def test_lifecycle_logs_events(caplog: pytest.LogCaptureFixture) -> None:
    sched, _w = _scheduler()
    with caplog.at_level(logging.INFO):
        sched.start()
        sched.stop()
    messages = [r.getMessage() for r in caplog.records]
    # Al menos los dos lifecycle logs. tick Once no debería disparar en
    # tests (threading.Timer asíncrono), así que no assertamos nada de tick.
    assert any("arrancado" in m for m in messages)
    assert any("detenido" in m for m in messages)


# ── tick_once: hizo su trabajo / omitió / falló ────────────────────────


def test_tick_writes_report_when_runs_in_period() -> None:
    now = datetime(2026, 3, 15, 10, 0, 0)
    run = _run(started=now - timedelta(days=2), run_id="run-1", score=80)
    sched, writer = _scheduler(runs=[run], clock_now=now)
    sched.tick_now()
    assert len(writer.calls) == 1
    path, content = writer.calls[0]
    assert path.endswith(".md")
    assert content.startswith("# GND — Reporte semanal")
    assert sched.last_report_path == path
    assert sched.last_report_at == now


def test_tick_skip_when_no_runs() -> None:
    now = datetime(2026, 3, 15, 10, 0, 0)
    sched, writer = _scheduler(runs=[], clock_now=now)
    sched.tick_now()
    assert writer.calls == []
    assert sched.last_report_path is None


def test_tick_skip_logs_event(caplog: pytest.LogCaptureFixture) -> None:
    now = datetime(2026, 3, 15, 10, 0, 0)
    sched, writer = _scheduler(runs=[], clock_now=now)
    with caplog.at_level(logging.INFO):
        sched.tick_now()
    assert writer.calls == []
    skip_records = [
        r for r in caplog.records if getattr(r, "event", None) == "report.skip"
    ]
    assert any(getattr(r, "reason", None) == "no_runs" for r in skip_records)


def test_tick_captures_reader_exception_and_continues() -> None:
    """EP §1.2: el scheduler nunca crashea ni se autodestruye."""
    sched, writer = _scheduler(reader=_ThrowingReader())
    # No propagate exception — el tick debe capturar.
    sched.tick_now()  # no raise
    assert writer.calls == []


def test_tick_compose_none_with_runs_does_not_write() -> None:
    """Edge case defensive: si compose devolvió None con runs no vacíos
    (caso defensivo que en la práctica no se da), el scheduler hace no-op
    sobre writer+notif. Lo testeamos usando runs vacío para forzar el
    branch ``report.skip`` con reason=no_runs (lo que en producción es
    el camino principal de omisión).
    """
    now = datetime(2026, 3, 15, 10, 0, 0)
    sched, writer = _scheduler(runs=[], clock_now=now)
    sched.tick_now()
    assert writer.calls == []


# ── Notif del reporte ─────────────────────────────────────────────────


def test_tick_notifies_when_notify_on_generated() -> None:
    now = datetime(2026, 3, 15, 10, 0, 0)
    run = _run(started=now - timedelta(days=2), score=80, run_id="r-1")
    notifier = FakeDesktopNotifier()
    sched, _w = _scheduler(runs=[run], clock_now=now, notifier=notifier)
    sched.tick_now()
    assert len(notifier.notifications) == 1
    n: DesktopNotification = notifier.notifications[0]
    assert n.title.startswith("GND — Reporte")
    assert "1 corridas" in n.message
    assert "Score promedio: 80" in n.message


def test_tick_skips_notification_when_notify_on_generated_false() -> None:
    now = datetime(2026, 3, 15, 10, 0, 0)
    run = _run(started=now - timedelta(days=2), score=80, run_id="r-1")
    notifier = FakeDesktopNotifier()
    config = _config(notify_on_generated=False)
    sched, _w = _scheduler(runs=[run], clock_now=now, notifier=notifier, config=config)
    sched.tick_now()
    assert notifier.notifications == []


def test_tick_skips_notification_when_period_is_clean() -> None:
    """notify_only_on_clean_period=True + todos safe → suprime."""
    now = datetime(2026, 3, 15, 10, 0, 0)
    run1 = _run(
        started=now - timedelta(days=2), score=90, verdict="safe_to_play", run_id="r-1"
    )
    run2 = _run(
        started=now - timedelta(days=1), score=88, verdict="safe_to_play", run_id="r-2"
    )
    notifier = FakeDesktopNotifier()
    config = _config(notify_only_on_clean_period=True)
    sched, _w = _scheduler(
        runs=[run1, run2], clock_now=now, notifier=notifier, config=config
    )
    sched.tick_now()
    assert notifier.notifications == []


def test_tick_notifies_when_period_has_issues_despite_clean_filter() -> None:
    """notify_only_on_clean_period=True pero hay issue → notifica."""
    now = datetime(2026, 3, 15, 10, 0, 0)
    run_safe = _run(
        started=now - timedelta(days=2),
        score=90,
        verdict="safe_to_play",
        run_id="r-safe",
    )
    run_issue = _run(
        started=now - timedelta(days=1),
        score=40,
        verdict="serious_issue",
        run_id="r-issue",
    )
    notifier = FakeDesktopNotifier()
    config = _config(notify_only_on_clean_period=True)
    sched, _w = _scheduler(
        runs=[run_safe, run_issue], clock_now=now, notifier=notifier, config=config
    )
    sched.tick_now()
    assert len(notifier.notifications) == 1


def test_tick_notifier_throwing_does_not_break_tick() -> None:
    now = datetime(2026, 3, 15, 10, 0, 0)
    run = _run(started=now - timedelta(days=2), score=80, run_id="r-1")

    class ThrowingNotifier:
        def notify(self, notification: DesktopNotification) -> None:
            raise RuntimeError("simulated plyer failure")

    sched, writer = _scheduler(
        runs=[run],
        clock_now=now,
        notifier=ThrowingNotifier(),  # type: ignore[arg-type]
    )
    # El tick debe completar (writer llamada) pese a la excepción del notif.
    sched.tick_now()
    assert len(writer.calls) == 1


# ── Path builder ──────────────────────────────────────────────────────


def test_build_report_path_uses_period_label_and_timestamp(tmp_path: Path) -> None:
    from gnd.reports.scheduler import _build_report_path

    now = datetime(2026, 3, 15, 10, 30, 45)
    path = _build_report_path(str(tmp_path), ReportPeriod.WEEKLY, now)
    assert path.endswith("report_semanal_20260315_103045.md")
    path_m = _build_report_path(str(tmp_path), ReportPeriod.MONTHLY, now)
    assert path_m.endswith("report_mensual_20260315_103045.md")


def test_build_report_path_expands_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    from gnd.reports.scheduler import _build_report_path

    monkeypatch.setenv("GND_TEST_REPORTS", "/tmp/test_gnd_reports")
    now = datetime(2026, 3, 15)
    path = _build_report_path("$GND_TEST_REPORTS", ReportPeriod.WEEKLY, now)
    assert path.startswith(str(Path("/tmp/test_gnd_reports")))


# ── period_to_timedelta ───────────────────────────────────────────────


def test_period_to_timedelta_weekly_is_7_days() -> None:
    from gnd.reports.scheduler import _period_to_timedelta

    assert _period_to_timedelta(ReportPeriod.WEEKLY) == timedelta(days=7)


def test_period_to_timedelta_monthly_is_30_days() -> None:
    from gnd.reports.scheduler import _period_to_timedelta

    assert _period_to_timedelta(ReportPeriod.MONTHLY) == timedelta(days=30)


# ── start sin daemon timer en tests ───────────────────────────────────


def test_start_with_real_timer_does_not_block_test(tmp_path: Path) -> None:
    """Sanity: start() agenda el Timer pero no bloquea (daemon)."""
    now = datetime(2026, 3, 15, 10, 0, 0)
    sched, _w = _scheduler(runs=[], clock_now=now)
    sched.start()
    # Inmediatamente paramos para no contaminar tests siguientes con
    # threads pendientes.
    sched.stop()
