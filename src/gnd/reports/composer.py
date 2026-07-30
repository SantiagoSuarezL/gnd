"""Composición de reportes periódicos (Fase 12b.3).

Paquete presentation nuevo. Hermano de ``export/`` (12b.1) — ambos son
serializadores sobre ``DiagnosticRun`` / conjuntos de éstos. Reusa el
renderer de 12b.1 (**função pura libre**) para los top-K runs destacados
del período; lo nuevo de 12b.3 es el agregado del período (header +
estadísticas + lista compacta + top-K).

Decisión de diseño (mismo molde que 12b.1, Regla 11.2 omitir > null):
- Composer como **función pura libre** ``compose_period_report``.
  No hay deps a inyectar (no IO, no DB, no scheduler). El caller
  (scheduler / UI / tests) es responsable de escribir el archivo str
  retornado y de leer los runs del histórico (DI via ``RunHistoryReader``).
- Sin Protocol ``ReportRenderer`` multi-formato — YAGNI mientras solo
  Markdown. Misma lógica que Regla 9.5 / 12b.1.1.
- Secciones opcionales: si ``period`` tuvo 0 runs, el composer devuelve
  ``None`` (signal explícita — Regla 12b.2.2: omitir > emitir payload
  degenerada). El caller decide no-op con log ``report.skip``.
- Si ``top_runs=0``, no se renderiza ningún run completo — solo
  agregado + lista compacta (utile para reportes mensuales largos).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from gnd.export import render_run_to_markdown
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.report_config import ReportConfig, ReportPeriod

__all__ = ["compose_period_report", "period_to_label"]


# ── Mapeo período → (etiqueta, días numéricos) ──────────────────────────
# Los días son informativos para el header del reporte (texto humano),
# no para cálculo de rango — eso lo hace el scheduler en base a
# ReportPeriod y al Clock inyectado.

_PERIOD_LABELS = {
    ReportPeriod.WEEKLY: ("semanal", 7),
    ReportPeriod.MONTHLY: ("mensual", 30),
}


def period_to_label(period: ReportPeriod) -> tuple[str, int]:
    """Devuelve (etiqueta_humana, días) para un ReportPeriod.

    Centralizado acá (no en ``models/``) para no acoplar el VO
    ``ReportConfig`` a strings de humanos ni a ``timedelta`` (Protocolo 1
    blando: models/ sin datetime-only-imports sería OK, pero preferimos
    que el VO quede puro — la traducción a humano/timedelta es presentation).
    """
    return _PERIOD_LABELS[period]


# ── Helpers de formateo (puros) ────────────────────────────────────────


def _fmt_dt(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# ── Sección: header ────────────────────────────────────────────────────


def _render_header(
    runs: list[DiagnosticRun],
    *,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
) -> list[str]:
    return [
        f"# GND — Reporte {period_label}",
        "",
        f"- **Período:** {_fmt_dt(period_start)} → {_fmt_dt(period_end)}",
        f"- **Corridas en el período:** {len(runs)}",
        "",
    ]


# ── Sección: agregados ─────────────────────────────────────────────────


def _render_aggregates(runs: list[DiagnosticRun]) -> list[str]:
    if not runs:
        return []

    scores = [r.recommendation.score for r in runs]
    verdicts = [r.recommendation.verdict for r in runs]
    components = [r.recommendation.responsible_component for r in runs]

    avg_score = sum(scores) / len(scores)
    verdict_counts = Counter(verdicts)
    component_counts = Counter(components)
    most_common_component, most_common_component_count = (
        component_counts.most_common(1)[0] if component_counts else ("unknown", 0)
    )

    lines = [
        "## Agregados del período",
        "",
        f"- **Score promedio:** {avg_score:.1f}/100",
        f"- **Score mínimo:** {min(scores)}/100",
        f"- **Score máximo:** {max(scores)}/100",
        "",
        "### Distribución de veredictos",
        "",
    ]
    # Render determinista: orden alfabético del verdict para que dos
    # reportes con el mismo set de runs produzcan el mismo output (tests
    # estables; también los reportes son diffs más legibles).
    for v in sorted(verdict_counts.keys()):
        lines.append(f"- **{v}**: {verdict_counts[v]}")
    lines.append("")
    lines.append("### Componente responsable más frecuente")
    lines.append("")
    lines.append(
        f"- **{most_common_component}** "
        f"({most_common_component_count}/{len(runs)} corridas)"
    )
    lines.append("")
    return lines


# ── Sección: lista compacta ────────────────────────────────────────────


def _render_runs_compact(runs: list[DiagnosticRun]) -> list[str]:
    if not runs:
        return []
    lines = [
        "## Corridas del período",
        "",
        "| Timestamp | Score | Veredicto | Headline |",
        "|---|---:|---|---|",
    ]
    for r in runs:
        ts = _fmt_dt(r.started_at)
        # Escapar pipes/backticks en celdas de tabla (Regla 12b.1.2).
        headline = _md_escape(r.recommendation.headline)
        lines.append(
            f"| {ts} | {r.recommendation.score}/100 | "
            f"{r.recommendation.verdict} | {headline} |"
        )
    lines.append("")
    return lines


# ── Sección: top-K runs renderizados con 12b.1 ─────────────────────────


def _render_top_runs(runs: list[DiagnosticRun], top_k: int) -> list[str]:
    if top_k <= 0 or not runs:
        return []
    # Top-K = los runs con menor score (más problemáticos primero) —
    # YAGNI personalizar criterio; si el período no tuvo issues, tomamos
    # los primeros cronológicamente (top_k peores = los K primeros con
    # score menor, ex-aequos resueltos por started_at ASC).
    ranked = sorted(runs, key=lambda r: (r.recommendation.score, r.started_at))
    selected = ranked[:top_k]
    lines = [f"## Top {len(selected)} corridas destacadas", ""]
    # Orden de aparición: cronológico (más legible para el usuario que
    # recorre el reporte). El ranking se usó solo para escoger.
    selected_chrono = sorted(selected, key=lambda r: r.started_at)
    for r in selected_chrono:
        lines.append(render_run_to_markdown(r))
        lines.append("---")
        lines.append("")
    # Quitar el último "---" separador extra.
    while lines and lines[-1] in ("", "---"):
        lines.pop()
    lines.append("")
    return lines


# ── Helper: escapado de celdas Markdown (mirror de 12b.1) ──────────────


def _md_escape(s: str | None) -> str:
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")


# ── Función pública: orquesta las secciones ────────────────────────────


def compose_period_report(
    runs: list[DiagnosticRun],
    config: ReportConfig,
    *,
    period_start: datetime,
    period_end: datetime,
) -> str | None:
    """Compone el reporte Markdown de un período a partir de los runs.

    Args:
        runs: lista de ``DiagnosticRun`` persistidos en el período,
            ordenados por ``started_at`` ASC (lo que devuelve
            ``RunHistoryReader.get_runs_in_period``).
        config: snapshot inmutable de la configuración (top_runs,
            período, etc.).
        period_start: inicio del período reportado (inclusivo).
        period_end: fin del período reportado (exclusivo — half-open).

    Returns:
        ``str`` Markdown autoexplicativo, o ``None`` si ``runs`` es
        vacío (Regla 12b.2.2: omitir > emitir payload degenerada —
        el caller decide no-op con log ``report.skip``).
    """
    if not runs:
        return None

    period_label, _days = period_to_label(config.period)
    lines: list[str] = []
    lines.extend(
        _render_header(
            runs,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
        )
    )
    lines.extend(_render_aggregates(runs))
    lines.extend(_render_runs_compact(runs))
    lines.extend(_render_top_runs(runs, config.top_runs))
    return "\n".join(lines).rstrip() + "\n"
