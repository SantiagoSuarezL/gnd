"""Sección UI para mostrar el resultado de la comparación WARP (Fase 12b.4).

Presenta:
- Veredicto agregado (improved / degraded / neutral / unavailable)
- Score delta (WARP off vs on)
- Tabla de deltas por provider (latencia, jitter, packet loss)
- Explicación en lenguaje natural

Sigue el patrón de las secciones existentes en `sections.py`: recibe
state via `update_state()` con dicts de keys conocidas.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from gnd.models.warp_comparison import WarpComparisonResult

logger = logging.getLogger(__name__)


class WarpComparisonSection(ttk.Frame):
    """Sección que renderiza el resultado de una comparación WARP.

    Estado esperado (`update_state`):
        "result": WarpComparisonResult | None
        "is_running": bool  (True mientras corre la comparación)
        "_error": str | None  (mensaje de error si falló)
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._build_layout()
        self.update_state({})

    def _build_layout(self) -> None:
        # Header
        header = ttk.Label(
            self,
            text="WARP Comparison (off vs on)",
            style="SectionHeader.TLabel",
        )
        header.pack(side="top", anchor="w", padx=8, pady=(8, 4))

        # Status label (running / done / error)
        self._status_label = ttk.Label(
            self,
            text="Sin resultados aún. Presiona 'Run WARP Comparison'.",
            foreground="#808080",
        )
        self._status_label.pack(side="top", anchor="w", padx=8)

        # Verdict label (large, prominent)
        self._verdict_label = ttk.Label(
            self,
            text="",
            font=("Segoe UI", 14, "bold"),
        )
        self._verdict_label.pack(side="top", anchor="w", padx=8, pady=(8, 4))

        # Score delta
        self._score_label = ttk.Label(self, text="")
        self._score_label.pack(side="top", anchor="w", padx=8)

        # Explanation text
        self._explanation_text = tk.Text(
            self,
            height=3,
            wrap="word",
            state="disabled",
            background="#1e1e1e",
            foreground="#d4d4d4",
            borderwidth=0,
        )
        self._explanation_text.pack(side="top", fill="x", padx=8, pady=(4, 8))

        # Provider deltas table
        self._tree = ttk.Treeview(
            self,
            columns=("provider", "metric", "off", "on", "delta", "pct", "status"),
            show="headings",
            height=10,
        )
        for col, text in [
            ("provider", "Provider"),
            ("metric", "Metric"),
            ("off", "WARP off"),
            ("on", "WARP on"),
            ("delta", "Δ"),
            ("pct", "Δ%"),
            ("status", "Status"),
        ]:
            self._tree.heading(col, text=text)
        self._tree.column("provider", width=110, anchor="w")
        self._tree.column("metric", width=130, anchor="w")
        self._tree.column("off", width=80, anchor="e")
        self._tree.column("on", width=80, anchor="e")
        self._tree.column("delta", width=70, anchor="e")
        self._tree.column("pct", width=60, anchor="e")
        self._tree.column("status", width=90, anchor="center")
        self._tree.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))

    def update_state(self, state: dict) -> None:
        """Aplica un state dict al UI.

        Keys reconocidas:
            "result": WarpComparisonResult
            "is_running": bool
            "_error": str
        """
        if state.get("_error"):
            self._status_label.configure(
                text=f"Error: {state['_error']}", foreground="#f48771"
            )
            self._verdict_label.configure(text="")
            self._score_label.configure(text="")
            self._set_explanation("")
            self._clear_tree()
            return

        if state.get("is_running"):
            self._status_label.configure(
                text="Comparando WARP off vs on...", foreground="#d4d4d4"
            )
            self._verdict_label.configure(text="Ejecutando...", foreground="#dcdcaa")
            self._score_label.configure(text="")
            self._set_explanation("Esto puede tardar ~30-60s (dos corridas completas).")
            self._clear_tree()
            return

        result: WarpComparisonResult | None = state.get("result")
        if result is None:
            self._status_label.configure(
                text="Sin resultados aún. Presiona 'Run WARP Comparison'.",
                foreground="#808080",
            )
            self._verdict_label.configure(text="")
            self._score_label.configure(text="")
            self._set_explanation("")
            self._clear_tree()
            return

        self._render_result(result)

    def _render_result(self, result: WarpComparisonResult) -> None:
        """Renderiza el resultado completo."""
        if not result.warp_controller_available:
            self._status_label.configure(
                text="warp-cli no encontrado en PATH",
                foreground="#f48771",
            )
            self._verdict_label.configure(text="Unavailable", foreground="#f48771")
            self._score_label.configure(text="")
            self._set_explanation("\n".join(result.verdict_explanation))
            self._clear_tree()
            return

        if result.overall_verdict == "state_timeout":
            self._status_label.configure(
                text="Comparación abortada: WARP no transicionó al estado objetivo",
                foreground="#ce9178",
            )
        else:
            self._status_label.configure(
                text=(
                    f"Comparación completada ({result.warp_off_duration_ms:.0f}ms + "
                    f"{result.warp_on_duration_ms:.0f}ms)"
                ),
                foreground="#6a9955",
            )

        # Verdict (color coded)
        verdict_colors = {
            "improved": "#6a9955",
            "degraded": "#f48771",
            "neutral": "#dcdcaa",
            "unavailable": "#f48771",
            "state_timeout": "#ce9178",  # Regla 12b.4.4: abort por race
        }
        color = verdict_colors.get(result.overall_verdict, "#d4d4d4")
        self._verdict_label.configure(
            text=result.overall_verdict.upper(),
            foreground=color,
        )

        # Score delta
        pct_str = (
            f" ({result.score_change_pct:+.1f}%)"
            if result.score_change_pct is not None
            else ""
        )
        self._score_label.configure(
            text=(
                f"Score: {result.warp_off_score:.1f} (off) -> "
                f"{result.warp_on_score:.1f} (on)  "
                f"d={result.score_delta:+.1f}{pct_str}"
            ),
            foreground=color,
        )

        # Explanation
        explanation_lines = list(result.verdict_explanation)
        if result.restore_warning:
            explanation_lines.append("")
            explanation_lines.append(f"[!] {result.restore_warning}")
        self._set_explanation("\n".join(explanation_lines))

        # Table
        self._clear_tree()
        for provider, deltas in result.provider_deltas.items():
            for d in deltas:
                # Regla 12b.4.5 (bug 2 fix): valores/delta None cuando
                # algún lado del provider falló. Mostrar "-" en vez de
                # 0.0 o error.
                off_str = (
                    f"{d.warp_off_value:.1f}" if d.warp_off_value is not None else "-"
                )
                on_str = (
                    f"{d.warp_on_value:.1f}" if d.warp_on_value is not None else "-"
                )
                delta_str = f"{d.delta:+.1f}" if d.delta is not None else "-"
                pct = f"{d.delta_pct:+.1f}%" if d.delta_pct is not None else "-"
                # Status: "ok" (oculto), o "FAILED" si algún lado falló.
                status_str = "" if d.status == "ok" else "FAILED"
                self._tree.insert(
                    "",
                    "end",
                    values=(
                        provider,
                        d.metric_name,
                        off_str,
                        on_str,
                        delta_str,
                        pct,
                        status_str,
                    ),
                )

    def _set_explanation(self, text: str) -> None:
        self._explanation_text.configure(state="normal")
        self._explanation_text.delete("1.0", "end")
        self._explanation_text.insert("1.0", text)
        self._explanation_text.configure(state="disabled")

    def _clear_tree(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)
