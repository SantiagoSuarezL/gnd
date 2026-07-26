"""Section widgets para la MainWindow — una subclase por seccion del PRD.

PRD §7: UI oscura con 5 secciones: Current Status, Network Tests,
Route Analysis, Historical Comparison, Recommendations.

Cada seccion es un ttk.Frame autónomo que expone `update_state(state)`
donde `state` es un dict estructurado que el controller le pasa via la
MainWindow. Las secciones NO conocen el caso de uso ni los adaptadores —
solo consumen los modelos de dominio (DiagnosticRun, ProbeResult, etc.).

Regla fija (2026-07-25): toda anomalia REAL (packet loss, jitter alto,
hop degradado) debe ser VISIBLE en la UI. Las secciones usan
`format_anomalies_text` del aggregator y `_format_probe_anomalies`
definido acá para garantizar esto determinísticamente.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any

from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteResult
from gnd.monitoring.aggregator import format_anomalies_text

# ---------------------------------------------------------------------------
# Helpers de formateo
# ---------------------------------------------------------------------------


_VERDICT_COLORS = {
    "safe_to_play": "#2e7d32",
    "playable": "#f9a825",
    "not_recommended_ranked": "#ef6c00",
    "serious_issue": "#c62828",
}


_VERDICT_LABELS = {
    "safe_to_play": "● Seguro para ranked",
    "playable": "● Jugable con precaución",
    "not_recommended_ranked": "● No recomendado para ranked",
    "serious_issue": "● Problema serio de conexión",
}


_OUTCOME_LABELS = {
    ProbeOutcomeKind.SUCCESS: "OK",
    ProbeOutcomeKind.FILTERED: "filtrado (ICMP bloqueado)",
    ProbeOutcomeKind.UNREACHABLE: "inalcanzable",
    ProbeOutcomeKind.TIMEOUT: "timeout",
}


def _fmt_ms(v: float | None) -> str:
    return f"{v:.1f} ms" if v is not None else "N/A"


def _format_probe_anomalies(probes: list[ProbeResult]) -> str:
    """Resumen determinista de anomalias en probes (regla fija 2026-07-25).

    Lista todos los probes con packet_loss > 0 o jitter > warning,
    sin importar el provider ni el n. Nunca devuelve cadena vacia.
    """
    lines: list[str] = []
    loss_probes = [
        p for p in probes if p.stats is not None and p.stats.packet_loss_pct > 0.0
    ]
    if loss_probes:
        lines.append(" probes con perdida de paquetes:")
        for p in loss_probes:
            lines.append(
                f"   {p.provider:18s} loss={p.stats.packet_loss_pct:5.1f}%"
                f"  jitter={p.stats.jitter_ms:5.1f}ms"
            )
    jitter_probes = [
        p for p in probes if p.stats is not None and p.stats.jitter_ms > 20.0
    ]
    if jitter_probes:
        lines.append(" probes con jitter alto (>20ms):")
        for p in jitter_probes:
            lines.append(f"   {p.provider:18s} jitter={p.stats.jitter_ms:5.1f}ms")
    if not lines:
        return " sin anomalias en probes."
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Secciones (todas ttk.Frame)
# ---------------------------------------------------------------------------


class SectionFrame(ttk.Frame):
    """Clase base: un frame con titulo y un Text/Label interno.

    Uso: subclass y override `update_state(state)`. El layout basico
    es un header con nombre + scrollable text body.
    """

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master, padding=8)
        self._title = title
        self._build()

    def _build(self) -> None:
        ttk.Label(self, text=self._title, style="SectionHeader.TLabel").grid(
            row=0, column=0, sticky="ew"
        )
        self.columnconfigure(0, weight=1)
        self._body = tk.Text(
            self,
            height=18,
            wrap="word",
            state="disabled",
            background="#1e1e1e",
            foreground="#d4d4d4",
            insertbackground="#d4d4d4",
            selectbackground="#264f78",
            relief="flat",
            font=("Consolas", 10),
        )
        self._body.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.rowconfigure(1, weight=1)

    def _set_body_text(self, text: str) -> None:
        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        self._body.insert("1.0", text)
        self._body.configure(state="disabled")

    def update_state(self, state: Any) -> None:
        raise NotImplementedError


class CurrentStatusSection(SectionFrame):
    """Seccion 1: veredicto + score + responsible component.

    State esperado: dict con 'recommendation' (Recommendation) y opcionalmente
    'started_at' y 'finished_at'.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, "Estado actual")

    def update_state(self, state: Any) -> None:
        if not state or "recommendation" not in state:
            self._set_body_text(" Ejecute un diagnóstico para ver el estado.")
            return
        rec: Recommendation = state["recommendation"]
        lines: list[str] = []
        lines.append(
            _VERDICT_LABELS.get(rec.verdict, f"● {rec.verdict}")
            + f"   (score: {rec.score}/100)"
        )
        lines.append("")
        if "started_at" in state and "finished_at" in state:
            started = state["started_at"]
            finished = state["finished_at"]
            if isinstance(started, datetime) and isinstance(finished, datetime):
                dur = (finished - started).total_seconds()
                lines.append(
                    f" Corrida: {started.strftime('%H:%M:%S')} "
                    f"-> {finished.strftime('%H:%M:%S')} ({dur:.1f}s)"
                )
                lines.append("")
        lines.append(f" Componente responsable: {rec.responsible_component}")
        lines.append("")
        lines.append(" Explicación:")
        for line in rec.explanation:
            lines.append(f"  - {line}")
        self._set_body_text("\n".join(lines))


class NetworkTestsSection(SectionFrame):
    """Seccion 2: tabla de probes (latencia, loss, jitter) + anomalias.

    State esperado: dict con 'probes' (list[ProbeResult]).
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, "Network Tests")

    def update_state(self, state: Any) -> None:
        if not state or "probes" not in state:
            self._set_body_text(" Sin datos de probes.")
            return
        probes: list[ProbeResult] = state["probes"]
        if not probes:
            self._set_body_text(" No se ejecutaron probes.")
            return
        lines: list[str] = []
        header = (
            f" {'provider':18s} {'target':30s} {'estado':10s} "
            f"{'avg':>10s} {'min':>10s} {'max':>10s} "
            f"{'jitter':>10s} {'loss':>8s}"
        )
        lines.append(header)
        lines.append(" " + "-" * (len(header) - 1))
        for p in probes:
            if p.outcome == ProbeOutcomeKind.SUCCESS and p.stats is not None:
                avg = _fmt_ms(p.stats.avg_ms)
                mn = _fmt_ms(p.stats.min_ms)
                mx = _fmt_ms(p.stats.max_ms)
                jit = f"{p.stats.jitter_ms:.1f} ms"
                loss = f"{p.stats.packet_loss_pct:.1f}%"
                state_str = "OK"
            else:
                avg = mn = mx = jit = "N/A"
                loss = "-"
                state_str = _OUTCOME_LABELS.get(p.outcome, p.outcome.name)
            lines.append(
                f" {p.provider:18s} {p.target_name[:30]:30s} "
                f"{state_str:10s} {avg:>10s} {mn:>10s} {mx:>10s} "
                f"{jit:>10s} {loss:>8s}"
            )
        lines.append("")
        lines.append(" Anomalías (regla fija: nunca omitir):")
        lines.append(_format_probe_anomalies(probes))
        self._set_body_text("\n".join(lines))


class RouteAnalysisSection(SectionFrame):
    """Seccion 3: traceroutes + hop culpable + anomalias por hop.

    State esperado: dict con 'traceroutes' (list[TracerouteResult]).
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, "Route Analysis")

    def update_state(self, state: Any) -> None:
        if not state or "traceroutes" not in state or not state["traceroutes"]:
            self._set_body_text(" Sin traceroutes en esta corrida.")
            return
        trs: list[TracerouteResult] = state["traceroutes"]
        lines: list[str] = []
        for tr in trs:
            lines.append(
                f" Traceroute -> {tr.target_provider} "
                f"(culprit hop: "
                f"{tr.culprit_hop_index + 1 if tr.culprit_hop_index is not None else 'N/A'})"  # noqa: E501
            )
            lines.append(f" {'hop':>4s}  {'ip':15s}  {'rtt':>10s}  estado")
            for h in tr.hops:
                ip = h.ip or "?"
                rtt = f"{h.rtt_ms:.1f} ms" if h.rtt_ms is not None else "*"
                status = "respondio" if h.responded else "sin respuesta"
                lines.append(f" {h.hop_number:4d}  {ip:15s}  {rtt:>10s}  {status}")
            lines.append("")
        self._set_body_text("\n".join(lines))


class HistoricalComparisonSection(SectionFrame):
    """Seccion 4: comparacion contra baseline historico.

    State esperado: dict con 'baselines' (dict[str, HistoricalBaseline])
    y opcionalmente 'probes' para mostrar actual vs baseline.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, "Historical Comparison")

    def update_state(self, state: Any) -> None:
        if not state or "baselines" not in state:
            self._set_body_text(
                " Sin baseline histórico. Ejecute varias corridas"
                " para acumular datos."
            )
            return
        baselines: dict[str, Any] = state["baselines"]
        if not baselines:
            self._set_body_text(
                " Sin historico suficiente (se acumula con cada corrida)."
            )
            return
        lines: list[str] = []
        lines.append(f" {'provider':18s} {'avg':>10s} {'stddev':>10s} {'n':>6s}")
        lines.append(" " + "-" * 50)
        for provider in sorted(baselines.keys()):
            b = baselines[provider]
            lines.append(
                f" {provider:18s} {b.avg_ms:8.1f}ms"
                f" {b.stddev_ms:8.1f}ms {b.sample_count:6d}"
            )
        actual_probes = state.get("probes")
        if actual_probes:
            lines.append("")
            lines.append(" Actual vs baseline (anomalia si > avg + 2*stddev):")
            for p in actual_probes:
                if p.stats is None:
                    continue
                b = baselines.get(p.provider)
                if b is None or b.sample_count == 0:
                    continue
                threshold = b.avg_ms + 2.0 * b.stddev_ms
                flag = " (anómalo)" if p.stats.avg_ms > threshold else ""
                lines.append(
                    f"  {p.provider:18s} actual={p.stats.avg_ms:6.1f}ms "
                    f"baseline={b.avg_ms:6.1f}ms{flag}"
                )
        self._set_body_text("\n".join(lines))


class RecommendationsSection(SectionFrame):
    """Seccion 5: recomendacion final + anomalias consolidadas.

    Esta es la seccion que mas peso tiene para el usuario (PRD §6.1:
    decision jugar/esperar en <15s). Muestra el veredicto y consolida
    las anomalias de probes y de hops intermedios para que el usuario
    vea TODO lo detectado, no solo el veredicto (regla fija 2026-07-25).
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, "Recommendations")

    def update_state(self, state: Any) -> None:
        if not state or "recommendation" not in state:
            self._set_body_text(
                " Ejecute un diagnóstico para recibir una recomendación."
            )
            return
        rec: Recommendation = state["recommendation"]
        lines: list[str] = []
        lines.append(_VERDICT_LABELS.get(rec.verdict, rec.verdict))
        lines.append(f" Score de red: {rec.score}/100")
        lines.append(f" Componente responsable: {rec.responsible_component}")
        lines.append("")
        lines.append(" Razonamiento del motor:")
        for line in rec.explanation:
            lines.append(f"  - {line}")
        # Consolidar anomalias de probes si estan presentes
        probes = state.get("probes")
        if probes:
            lines.append("")
            lines.append(" Anomalías detectadas (probes):")
            lines.append(_format_probe_anomalies(probes))
        # Anomalias de hops si hay traceroutes con hop_stats
        monitoring_hops = state.get("hop_stats")
        if monitoring_hops:
            lines.append("")
            lines.append(" Anomalías detectadas (hops intermedios):")
            lines.append(format_anomalies_text(monitoring_hops))
        self._set_body_text("\n".join(lines))
