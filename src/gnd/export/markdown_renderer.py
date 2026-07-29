"""Render de un DiagnosticRun a Markdown (Fase 12b.1).

PRD §7 nice-to-have + IMPLEMENTATION_PLAN.md 12b.1: el usuario puede exportar
la corrida mas reciente a un ``.md`` autoexplicativo, sin dependencias
externas nuevas (stdlib ``datetime`` para timestamps; sin ``reportlab`` /
``weasyprint`` — PDF queda fuera de scope 12b por YAGNI).

Decision de diseno: el renderer es una **funcion pura libre**, no una clase.
Motivos:
  - El input (``DiagnosticRun``) es inmutable (Protocolo 5).
  - No hay dependencias a inyectar (no hace IO, no consulta DB, no llama a
    subprocess). Un Protocol ``RunRenderer`` con multiples implementaciones
    seria YAGNI — solo Markdown por ahora.
  - Maximiza testabilidad: in (DiagnosticRun) -> out (str), sin fixtures
    de IO ni mocks de file dialogs.

El caller (UI / tests / scripts) es responsable de abrir el path y escribir
el string retornado. Eso mantiene el renderer bidimensional y predecible.

Reglas transversales respetadas:
  - Protocolo 1 (separacion models/domain): este modulo solo importa de
    ``models/`` — no toca psutil/sqlite3/subprocess.
  - Regla 11.3 (eventos estructurados): el renderer NO loguea (no es su
    responsabilidad); el caller (UI) emite export.start/finish/error.
  - Protocolo 4 (explicacion obligatoria): el renderer siempre imprime la
    explanation del motor de recomendacion (nunca vacia por invariante del
    modelo).
"""

from __future__ import annotations

from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.dns_measurement import DnsOutcome
from gnd.models.network_interface import InterfaceType
from gnd.models.probe_result import ProbeOutcomeKind
from gnd.models.traceroute import TracerouteResult

__all__ = ["render_run_to_markdown"]


# ── Helpers de formateo (puros, sin estado) ─────────────────────────────


def _fmt_ms(v: float | None) -> str:
    return f"{v:.1f} ms" if v is not None else "N/A"


def _fmt_outcome(o: ProbeOutcomeKind) -> str:
    return {
        ProbeOutcomeKind.SUCCESS: "OK",
        ProbeOutcomeKind.FILTERED: "filtrado (ICMP bloqueado)",
        ProbeOutcomeKind.UNREACHABLE: "inalcanzable",
        ProbeOutcomeKind.TIMEOUT: "timeout",
    }.get(o, o.name)


def _fmt_dns_outcome(o: DnsOutcome) -> str:
    return {
        DnsOutcome.SUCCESS: "OK",
        DnsOutcome.TIMEOUT: "timeout",
        DnsOutcome.ERROR: "error",
    }.get(o, o.name)


def _fmt_interface_type(t: InterfaceType) -> str:
    return {
        InterfaceType.WIFI: "Wi-Fi",
        InterfaceType.ETHERNET: "Ethernet",
        InterfaceType.OTHER: "otra",
    }.get(t, t.name)


def _fmt_duration_ms(ms: float) -> str:
    if ms < 1000.0:
        return f"{ms:.0f} ms"
    return f"{ms / 1000.0:.2f} s"


def _fmt_dt(dt) -> str:  # type: ignore[no-untyped-def]
    # ISO 8601 sin microsegundos — tight, ordenable lexicograficamente,
    # legible para un humano que abre el .md.
    return dt.replace(microsecond=0).isoformat()


# ── Seccion: header + metadatos del run ─────────────────────────────────


def _render_header(run: DiagnosticRun) -> list[str]:
    duration_ms = (run.finished_at - run.started_at).total_seconds() * 1000.0
    return [
        "# GND — Reporte de diagnóstico",
        "",
        f"- **Run ID:** `{run.run_id}`",
        f"- **Inicio:** {_fmt_dt(run.started_at)}",
        f"- **Fin:** {_fmt_dt(run.finished_at)}",
        f"- **Duración:** {_fmt_duration_ms(duration_ms)}",
        "",
    ]


# ── Seccion: veredicto + score + explanation ────────────────────────────


def _render_recommendation(run: DiagnosticRun) -> list[str]:
    rec = run.recommendation
    lines = [
        "## Veredicto",
        "",
        f"**Score:** {rec.score}/100",
        "",
        f"**Veredicto:** {rec.verdict}",
        "",
        f"**Resumen:** {rec.headline}",
        "",
        f"**Componente responsable:** {rec.responsible_component}",
        "",
        "### Explicación del motor de recomendación",
        "",
    ]
    # Protocolo 4: explanation nunca es vacia (invariante del modelo).
    for i, line in enumerate(rec.explanation, start=1):
        lines.append(f"{i}. {line}")
    lines.append("")
    return lines


# ── Seccion: probes ────────────────────────────────────────────────────


def _render_probes(run: DiagnosticRun) -> list[str]:
    if not run.probes:
        return ["## Probes", "", "_(sin probes en esta corrida)_", ""]
    lines = ["## Probes", ""]
    # Tabla compacta. Columnas alineadas por Markdown puro (sin ancho fijo —
    # cada viewer lo acomoda suyo). family al final para que columns
    # core (target/provider/outcome/stats) queden a la izquierda.
    lines.append(
        "| Target | Provider | Outcome | Avg | Min | Max | "
        "Jitter | Loss | Samples | Family |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for p in run.probes:
        stats = p.stats
        lines.append(
            "| "
            f"{_md_escape(p.target_name)} | "
            f"{_md_escape(p.provider)} | "
            f"{_fmt_outcome(p.outcome)} | "
            f"{_fmt_ms(stats.avg_ms) if stats else 'N/A'} | "
            f"{_fmt_ms(stats.min_ms) if stats else 'N/A'} | "
            f"{_fmt_ms(stats.max_ms) if stats else 'N/A'} | "
            f"{_fmt_ms(stats.jitter_ms) if stats else 'N/A'} | "
            f"{(f'{stats.packet_loss_pct:.1f}%') if stats else 'N/A'} | "
            f"{stats.samples if stats else 'N/A'} | "
            f"{p.family} |"
        )
    lines.append("")
    return lines


# ── Seccion: traceroutes ───────────────────────────────────────────────


def _render_traceroutes(run: DiagnosticRun) -> list[str]:
    if not run.traceroutes:
        return ["## Traceroutes", "", "_(sin traceroutes en esta corrida)_", ""]
    lines = ["## Traceroutes", ""]
    for t in run.traceroutes:
        lines.extend(_render_one_traceroute(t))
    return lines


def _render_one_traceroute(t: TracerouteResult) -> list[str]:
    culprit = (
        f" — **hop culpable:** #{t.hops[t.culprit_hop_index].hop_number}"
        if t.culprit_hop_index is not None
        else " — sin hop culpable identificado"
    )
    lines = [
        f"### {t.target_provider} ({t.family}){culprit}",
        "",
        "| Hop | IP | Hostname | RTT | Respondió |",
        "|---:|---|---|---:|:---:|",
    ]
    for h in t.hops:
        ip = h.ip or "—"
        hostname = _md_escape(h.hostname) if h.hostname else "—"
        rtt = _fmt_ms(h.rtt_ms) if h.rtt_ms is not None else "—"
        responded = "sí" if h.responded else "no"
        lines.append(
            f"| {h.hop_number} | {_md_escape(ip)} | {hostname} | {rtt} | {responded} |"
        )
    lines.append("")
    return lines


# ── Seccion: DNS (Fase 12a.2, opcional) ────────────────────────────────


def _render_dns(run: DiagnosticRun) -> list[str]:
    if not run.dns_results:
        return []
    lines = ["## Resolución DNS", ""]
    lines.append("| Hostname | Family | Outcome | IP resuelta | Tiempo | Error |")
    lines.append("|---|---|---|---|---:|---|")
    for d in run.dns_results:
        ip = d.resolved_ip or "—"
        elapsed = _fmt_ms(d.elapsed_ms) if d.elapsed_ms is not None else "—"
        err = _md_escape(d.error) if d.error else "—"
        lines.append(
            f"| {_md_escape(d.hostname)} | {d.family} | "
            f"{_fmt_dns_outcome(d.outcome)} | {_md_escape(ip)} | "
            f"{elapsed} | {err} |"
        )
    lines.append("")
    return lines


# ── Seccion: interfaz de red (Fase 12a.3, opcional) ────────────────────


def _render_interface(run: DiagnosticRun) -> list[str]:
    s = run.interface_snapshot
    if s is None:
        return []
    lines = ["## Interfaz de red activa", ""]
    lines.append(f"- **Tipo:** {_fmt_interface_type(s.type)}")
    lines.append(f"- **Nombre:** {_md_escape(s.name)}")
    lines.append(f"- **Default route:** {'sí' if s.is_default_route else 'no'}")
    if s.type is InterfaceType.WIFI:
        ssid = _md_escape(s.wifi_ssid) if s.wifi_ssid else "(no expuesto)"
        signal = (
            f"{s.wifi_signal_dbm:.0f} dBm"
            if s.wifi_signal_dbm is not None
            else "(no expuesto)"
        )
        lines.append(f"- **SSID:** {ssid}")
        lines.append(f"- **Señal:** {signal}")
    if s.error:
        lines.append(f"- **Nota:** {_md_escape(s.error)}")
    lines.append("")
    return lines


# ── Seccion: game server activo (Fase 6, opcional) ─────────────────────


def _render_game_server(run: DiagnosticRun) -> list[str]:
    ags = run.active_game_server
    if ags is None:
        return []
    lines = ["## Servidor de partida activo", ""]
    lines.append(f"- **IP:** `{ags.ip}`")
    lines.append(f"- **Puerto:** {ags.port}")
    lines.append(f"- **Protocolo:** {ags.protocol}")
    lines.append(f"- **Detección:** {ags.detected_via}")
    lines.append(f"- **Proceso:** {_md_escape(ags.process_name)}")
    lines.append("")
    return lines


# ── Helper: escapado de caracteres que rompen tablas Markdown ──────────


def _md_escape(s: str | None) -> str:
    """Escapa pipe y backticks en campos libres para que no rompan tablas."""
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")


# ── Funcion publica: orquesta todas las secciones ───────────────────────


def render_run_to_markdown(run: DiagnosticRun) -> str:
    """Renderiza un ``DiagnosticRun`` a un string Markdown autoexplicativo.

    El output contiene (en orden):
      1. Header con metadatos del run (run_id, timestamps, duracion).
      2. Veredicto: score, veredicto, headline, componente responsable,
         explanation del motor (Protocolo 4: nunca vacia).
      3. Tabla de probes (target/provider/outcome/latencias/loss/jitter/
         samples/family).
      4. Seccion por traceroute (hops + culprit marcado si lo hay).
      5. Seccion DNS (solo si ``dns_results`` no vacio — Fase 12a.2).
      6. Seccion interfaz de red (solo si ``interface_snapshot`` no None
         — Fase 12a.3).
      7. Seccion game server activo (solo si ``active_game_server`` no None
         — Fase 6).

    Secciones opcionales (5/6/7) se omiten si no aplican — el output queda
    tight sin secciones vacias (Regla 11.2 volcada a Markdown: omite > null).

    Args:
        run: la corrida a renderizar.

    Returns:
        String Markdown multilinea. Nunca devuelve cadena vacia.
    """
    lines: list[str] = []
    lines.extend(_render_header(run))
    lines.extend(_render_recommendation(run))
    lines.extend(_render_probes(run))
    lines.extend(_render_traceroutes(run))
    lines.extend(_render_dns(run))
    lines.extend(_render_interface(run))
    lines.extend(_render_game_server(run))
    return "\n".join(lines).rstrip() + "\n"
