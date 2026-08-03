"""Sección UI para mostrar el resultado de un speed test (Fase 12b.5).

Presenta:
- Veredicto agregado (improved / degraded / neutral / unavailable)
- Métricas de speed test (latencia, jitter, download, upload, packet loss)
- Deltas entre diagnóstico y speed test
- Explicación en lenguaje natural
- Información del servidor (nombre, país, ISP)

Sigue el patrón de las secciones existentes en `sections.py`: recibe
state via `update_state()` con dicts de keys conocidas.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from gnd.models.speed_test import SpeedTestComparisonResult

logger = logging.getLogger(__name__)


class SpeedTestComparisonSection(ttk.Frame):
    """Sección que renderiza el resultado de un speed test.

    Estado esperado (`update_state`):
        "result": SpeedTestComparisonResult | None
        "is_running": bool  (True mientras corre el speed test)
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
            text="Speed Test",
            style="SectionHeader.TLabel",
        )
        header.pack(side="top", anchor="w", padx=8, pady=(8, 4))

        # Status label (running / done / error)
        self._status_label = ttk.Label(
            self,
            text="Sin resultados aún. Presiona 'Run Speed Test'.",
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

        # Score / diagnostic info
        self._score_label = ttk.Label(self, text="")
        self._score_label.pack(side="top", anchor="w", padx=8)

        # Speed test metrics
        self._metrics_label = ttk.Label(self, text="")
        self._metrics_label.pack(side="top", anchor="w", padx=8, pady=(4, 8))

        # Server info
        self._server_label = ttk.Label(self, text="", foreground="#808080")
        self._server_label.pack(side="top", anchor="w", padx=8, pady=(0, 8))

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

        # Deltas table
        self._tree = ttk.Treeview(
            self,
            columns=("metric", "diagnostic", "speed_test", "delta", "pct"),
            show="headings",
            height=8,
        )
        for col, text in [
            ("metric", "Metric"),
            ("diagnostic", "Diagnostic"),
            ("speed_test", "Speed Test"),
            ("delta", "Δ"),
            ("pct", "Δ%"),
        ]:
            self._tree.heading(col, text=text)
        self._tree.column("metric", width=160, anchor="w")
        self._tree.column("diagnostic", width=100, anchor="e")
        self._tree.column("speed_test", width=100, anchor="e")
        self._tree.column("delta", width=80, anchor="e")
        self._tree.column("pct", width=70, anchor="e")
        self._tree.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))

    def update_state(self, state: dict) -> None:
        """Aplica un state dict al UI.

        Keys reconocidas:
            "result": SpeedTestComparisonResult
            "is_running": bool
            "_error": str
        """
        if state.get("_error"):
            self._status_label.configure(
                text=f"Error: {state['_error']}", foreground="#f48771"
            )
            self._verdict_label.configure(text="")
            self._score_label.configure(text="")
            self._metrics_label.configure(text="")
            self._server_label.configure(text="")
            self._set_explanation("")
            self._clear_tree()
            return

        if state.get("is_running"):
            self._status_label.configure(
                text="Ejecutando speed test...",
                foreground="#d4d4d4",
            )
            self._verdict_label.configure(text="Ejecutando...", foreground="#dcdcaa")
            self._score_label.configure(text="")
            self._metrics_label.configure(text="")
            self._server_label.configure(text="")
            self._set_explanation(
                "Esto puede tardar ~30-120s (diagnóstico + speed test)."
            )
            self._clear_tree()
            return

        result: SpeedTestComparisonResult | None = state.get("result")
        if result is None:
            self._status_label.configure(
                text="Sin resultados aún. Presiona 'Run Speed Test'.",
                foreground="#808080",
            )
            self._verdict_label.configure(text="")
            self._score_label.configure(text="")
            self._metrics_label.configure(text="")
            self._server_label.configure(text="")
            self._set_explanation("")
            self._clear_tree()
            return

        self._render_result(result)

    def _render_result(self, result: SpeedTestComparisonResult) -> None:
        """Renderiza el resultado completo."""
        if not result.speed_test_controller_available:
            self._status_label.configure(
                text="speedtest (ookla-speedtest) no encontrado en PATH",
                foreground="#f48771",
            )
            self._verdict_label.configure(text="Unavailable", foreground="#f48771")
            self._score_label.configure(text="")
            self._metrics_label.configure(text="")
            self._server_label.configure(text="")
            self._set_explanation("\n".join(result.verdict_explanation))
            self._clear_tree()
            return

        self._status_label.configure(
            text="Speed test completado",
            foreground="#6a9955",
        )

        # Verdict (color coded)
        verdict_colors = {
            "improved": "#6a9955",
            "degraded": "#f48771",
            "neutral": "#dcdcaa",
            "unavailable": "#f48771",
        }
        color = verdict_colors.get(result.overall_verdict, "#d4d4d4")
        self._verdict_label.configure(
            text=result.overall_verdict.upper(),
            foreground=color,
        )

        # Diagnostic info (score + verdict del diagnóstico)
        # Bug original (Fase 12b.5): el template usaba `result.baseline.server_name`
        # (nombre del servidor de speed test) en lugar del score del diagnóstico.
        # El `SpeedTestComparisonResult` ahora transporta `diagnostic_score` y
        # `diagnostic_verdict` (seteados por el use case desde `run.recommendation`).
        diag_score = result.diagnostic_score
        diag_verdict = result.diagnostic_verdict
        if diag_score is not None and diag_verdict is not None:
            self._score_label.configure(
                text=f"Diagnóstico: score={diag_score}/100, verdict={diag_verdict}",
                foreground=color,
            )
        else:
            # Caso unavailable: no hay score del diagnóstico.
            self._score_label.configure(text="", foreground=color)

        # Speed test metrics
        speed = result.comparison
        self._metrics_label.configure(
            text=(
                f"Speed test: {speed.download_mbps:.1f}↓ "
                f"{speed.upload_mbps:.1f}↑ "
                f"latencia={speed.latency_ms:.1f}ms "
                f"jitter={speed.jitter_ms:.1f}ms "
                f"loss={speed.packet_loss_pct:.1f}%"
            ),
        )

        # Server info
        self._server_label.configure(
            text=(
                f"Servidor: {speed.server_name}, "
                f"{speed.server_country} | ISP: {speed.isp}"
            )
        )

        # Explanation
        self._set_explanation("\n".join(result.verdict_explanation))

        # Deltas table
        self._clear_tree()
        for d in result.deltas:
            pct = f"{d.delta_pct:+.1f}%" if d.delta_pct is not None else "-"
            self._tree.insert(
                "",
                "end",
                values=(
                    d.metric_name,
                    f"{d.baseline_value:.1f}",
                    f"{d.comparison_value:.1f}",
                    f"{d.delta:+.1f}",
                    pct,
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
