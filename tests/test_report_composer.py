"""Tests del composer de reportes periódicos (Fase 12b.3).

``compose_period_report`` es función pura: in (list[DiagnosticRun],
ReportConfig, period_start, period_end) -> out (str Markdown | None).
Tests cubren:
- Período vacío → devuelve None (Regla 12b.2.2: omite > payload degenerada).
- Header del reporte: título con período, rango y count.
- Agregados: avg/min/max score, distribución de verdicts, componente más
  frecuente.
- Lista compacta: tabla con timestamp/score/verdict/headline, escapado
  de pipes en headline (Regla 12b.1.2).
- Top-K: los K runs con menor score se renderizan completos con
  ``render_run_to_markdown`` de 12b.1 (footer hay separador `---`).
- top_runs=0 deshabilita la sección top-K (solo agregado + lista compacta).
- ReportPeriod.WEEKLY vs MONTHLY solo cambia la etiqueta del título.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.recommendation import Recommendation
from gnd.models.report_config import ReportConfig, ReportPeriod
from gnd.reports.composer import compose_period_report, period_to_label

# ── Factory helpers ────────────────────────────────────────────────────


def _rec(
    *, verdict: str = "safe_to_play", score: int = 90, responsible: str = "unknown"
) -> Recommendation:
    return Recommendation(
        verdict=verdict,
        headline="Headline de prueba",
        explanation=["Sin anomalías", "Score normal"],
        responsible_component=responsible,
        score=score,
    )


def _run(
    *,
    started: datetime | None = None,
    verdict: str = "safe_to_play",
    score: int = 90,
    responsible: str = "unknown",
    run_id: str = "r-x",
) -> DiagnosticRun:
    now = started or datetime.now()
    return DiagnosticRun(
        run_id=run_id,
        started_at=now,
        finished_at=now + timedelta(seconds=5),
        probes=[],
        traceroutes=[],
        active_game_server=None,
        recommendation=_rec(verdict=verdict, score=score, responsible=responsible),
    )


def _config(
    *,
    period: ReportPeriod = ReportPeriod.WEEKLY,
    top_runs: int = 3,
) -> ReportConfig:
    return ReportConfig(
        period=period,
        top_runs=top_runs,
        reports_dir="/tmp/irrelevant",
        notify_on_generated=False,
        notify_only_on_clean_period=False,
    )


# ── period_to_label ────────────────────────────────────────────────────


def test_period_to_label_weekly() -> None:
    label, days = period_to_label(ReportPeriod.WEEKLY)
    assert label == "semanal"
    assert days == 7


def test_period_to_label_monthly() -> None:
    label, days = period_to_label(ReportPeriod.MONTHLY)
    assert label == "mensual"
    assert days == 30


# ── Período vacío ──────────────────────────────────────────────────────


def test_compose_empty_returns_none() -> None:
    """Regla 12b.2.2: omitir > emitir payload degenerada."""
    out = compose_period_report(
        runs=[],
        config=_config(),
        period_start=datetime.now() - timedelta(days=7),
        period_end=datetime.now(),
    )
    assert out is None


# ── Header ────────────────────────────────────────────────────────────


def test_compose_header_weekly_contains_label_period_and_count() -> None:
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = start + timedelta(days=7)
    run = _run(started=start + timedelta(days=1), run_id="run-1")
    out = compose_period_report(
        [run], _config(period=ReportPeriod.WEEKLY), period_start=start, period_end=end
    )
    assert out is not None
    assert "# GND — Reporte semanal" in out
    assert start.isoformat() in out
    assert end.isoformat() in out
    assert "1" in out  # count


def test_compose_header_monthly_label_differs_from_weekly() -> None:
    start = datetime(2026, 1, 1)
    end = start + timedelta(days=30)
    run = _run(started=start + timedelta(days=1), run_id="run-1")
    weekly = compose_period_report(
        [run], _config(period=ReportPeriod.WEEKLY), period_start=start, period_end=end
    )
    monthly = compose_period_report(
        [run], _config(period=ReportPeriod.MONTHLY), period_start=start, period_end=end
    )
    assert weekly is not None
    assert monthly is not None
    assert "Reporte semanal" in weekly
    assert "Reporte mensual" in monthly


# ── Agregados ─────────────────────────────────────────────────────────


def test_compose_aggregates_avg_min_max_score() -> None:
    now = datetime.now()
    runs = [
        _run(started=now, score=80),
        _run(started=now + timedelta(hours=1), score=60),
        _run(started=now + timedelta(hours=2), score=40, run_id="r-low"),
    ]
    out = compose_period_report(
        runs,
        _config(),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(hours=3),
    )
    assert out is not None
    # avg = (80+60+40)/3 = 60.0
    assert "60.0/100" in out
    assert "40/100" in out  # min
    assert "80/100" in out  # max


def test_compose_aggregates_verdict_distribution_sorted_alphabetically() -> None:
    now = datetime.now()
    runs = [
        _run(started=now, verdict="playable"),
        _run(started=now + timedelta(hours=1), verdict="serious_issue", run_id="r-2"),
        _run(started=now + timedelta(hours=2), verdict="playable", run_id="r-3"),
    ]
    out = compose_period_report(
        runs,
        _config(),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    # Orden alfabético: playable antes que serious_issue.
    idx_playable = out.index("playable")
    idx_serious = out.index("serious_issue")
    assert idx_playable < idx_serious
    assert "playable**: 2" in out
    assert "serious_issue**: 1" in out


def test_compose_aggregates_most_common_responsible_component() -> None:
    now = datetime.now()
    runs = [
        _run(started=now, responsible="isp"),
        _run(started=now + timedelta(hours=1), responsible="isp", run_id="r-2"),
        _run(started=now + timedelta(hours=2), responsible="riot", run_id="r-3"),
    ]
    out = compose_period_report(
        runs,
        _config(),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    assert "**isp** (2/3 corridas)" in out


# ── Lista compacta ────────────────────────────────────────────────────


def test_compose_runs_compact_table_contains_all_runs() -> None:
    now = datetime.now()
    runs = [
        _run(started=now, score=80, run_id="r-0"),
        _run(
            started=now + timedelta(hours=1), score=70, verdict="playable", run_id="r-1"
        ),
    ]
    out = compose_period_report(
        runs,
        _config(),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    assert "## Corridas del período" in out
    assert "80/100" in out
    assert "70/100" in out
    assert "safe_to_play" in out
    assert "playable" in out


def test_compose_runs_compact_escapes_pipe_in_headline() -> None:
    """Regla 12b.1.2: escapar pipes en celdas de tabla."""
    now = datetime.now()
    run = DiagnosticRun(
        run_id="r-pipe",
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        probes=[],
        traceroutes=[],
        active_game_server=None,
        recommendation=Recommendation(
            verdict="safe_to_play",
            headline="algo | otra cosa",
            explanation=["ok"],
            responsible_component="unknown",
            score=90,
        ),
    )
    out = compose_period_report(
        [run],
        _config(),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    assert "algo \\| otra cosa" in out
    assert "| algo | otra cosa |" not in out  # sin escapado rompería la tabla


# ── Top-K ─────────────────────────────────────────────────────────────


def test_compose_top_runs_includes_only_lowest_score_runs() -> None:
    now = datetime.now()
    runs = [
        _run(started=now, score=90, run_id="r-90"),
        _run(started=now + timedelta(hours=1), score=80, run_id="r-80"),
        _run(started=now + timedelta(hours=2), score=70, run_id="r-70"),
        _run(started=now + timedelta(hours=3), score=60, run_id="r-60"),
    ]
    out = compose_period_report(
        runs,
        _config(top_runs=2),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    assert "## Top 2 corridas destacadas" in out
    # Los top-2 = los 2 con menor score: r-60 (60) y r-70 (70). NO r-80/90.
    assert "r-60" in out
    assert "r-70" in out
    assert "r-80" not in out
    assert "r-90" not in out


def test_compose_top_runs_zero_omits_top_section() -> None:
    now = datetime.now()
    runs = [_run(started=now, score=80)]
    out = compose_period_report(
        runs,
        _config(top_runs=0),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    assert "Top" not in out
    assert "corridas destacadas" not in out


def test_compose_top_runs_chronological_order_in_output() -> None:
    """El top-K se elige por score pero se muestra cronológico."""
    now = datetime.now()
    # r-late con score peor (más bajo) que r-early, para asegurar que
    # ambos quedan en top-2 pero aparecen en orden cronológico en el output.
    runs = [
        _run(started=now, score=70, run_id="r-early"),
        _run(started=now + timedelta(hours=1), score=60, run_id="r-late"),
    ]
    out = compose_period_report(
        runs,
        _config(top_runs=2),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    idx_early = out.index("r-early")
    idx_late = out.index("r-late")
    assert idx_early < idx_late  # cronológico


# ── Reuso del renderer 12b.1 ──────────────────────────────────────────


def test_compose_top_runs_reuses_render_run_to_markdown() -> None:
    """Top-K content debe contener el output del renderer de 12b.1
    (header `# GND — Reporte de diagnóstico` del run individual)."""
    now = datetime.now()
    run = _run(started=now, score=80)
    out = compose_period_report(
        [run],
        _config(top_runs=1),
        period_start=now - timedelta(days=7),
        period_end=now + timedelta(days=1),
    )
    assert out is not None
    assert "# GND — Reporte de diagnóstico" in out  # header del renderer individual


# ── ReportConfig invariantes ──────────────────────────────────────────


def test_report_config_rejects_negative_top_runs() -> None:
    with pytest.raises(ValueError, match="top_runs"):
        ReportConfig(period=ReportPeriod.WEEKLY, top_runs=-1)


def test_report_config_rejects_invalid_period_type() -> None:
    with pytest.raises(ValueError, match="period debe ser ReportPeriod"):
        ReportConfig(period="weekly")  # type: ignore[arg-type]


def test_report_config_rejects_empty_reports_dir() -> None:
    with pytest.raises(ValueError, match="reports_dir"):
        ReportConfig(period=ReportPeriod.WEEKLY, reports_dir="")


def test_report_config_accepts_defaults() -> None:
    c = ReportConfig(period=ReportPeriod.MONTHLY)
    assert c.top_runs == 3
    assert c.reports_dir == "%APPDATA%/GND/reports"
    assert c.notify_on_generated is True
    assert c.notify_only_on_clean_period is False


def test_report_config_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    c = ReportConfig(period=ReportPeriod.WEEKLY)
    with pytest.raises(FrozenInstanceError):
        c.top_runs = 5  # type: ignore[misc]
