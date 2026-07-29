"""MainWindow — ventana principal dark mode con 5 secciones (PRD §7).

Fase 9 (IMPLEMENTATION_PLAN.md): UI oscura, un clic ejecuta todo, sin
bloquear la interfaz durante los sondeos. Usa tkinter (decision 2026-07-25:
stdlib, sin dependencias externas).

Layout:
- Top bar: titulo + boton "Run Diagnostics" + label de estado.
- Notebook (ttk): una pestana por seccion del PRD (5 en total).
- Status bar: progreso + timestamp de la ultima corrida.

Threading:
- El boton lanza `DiagnosticsController.run_async()`.
- Los callbacks del controller (`on_progress`, `on_result`, `on_error`)
  se agendan al main loop via `self.after(0, ...)` — nunca tocan
  widgets directamente desde el worker thread (tkinter no es thread-safe).
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.ui.charts_section import ChartsSection
from gnd.ui.controller import DiagnosticsController
from gnd.ui.sections import (
    CurrentStatusSection,
    HistoricalComparisonSection,
    NetworkTestsSection,
    RecommendationsSection,
    RouteAnalysisSection,
)
from gnd.visualization import SeriesDataSource

logger = logging.getLogger(__name__)


# Paleta dark mode (colores derivados del tema "dark" de VS Code, una
# ref familiar para el usuario. Tecnicamente: tonos medios de gris con
# acento azul para emphasize.)
_BG = "#1e1e1e"
_BG_ALT = "#252526"
_FG = "#d4d4d4"
_FG_DIM = "#808080"
_ACCENT = "#007acc"
_BORDER = "#3c3c3c"


def apply_dark_theme(root: tk.Tk) -> ttk.Style:
    """Aplica un tema dark a ttk via `ttk.Style`.

    tkinter no trae un dark theme oob, pero `ttk.Style` permite
    customizar colores de los widgets ttk (botones, notebook, labels).
    Los widgets `tk.Text` usan colores directos via options (no style),
    por eso se setean explicitamente en `sections.py`.
    """
    root.configure(background=_BG)
    style = ttk.Style(root)
    # Ignoramos el theme por default; partimos de 'clam' que es el
    # mas flexible para customizar (otros themes como 'vista' en
    # Windows no respetan todos los_options).
    style.theme_use("clam")

    style.configure("TFrame", background=_BG, foreground=_FG)
    style.configure("TButton", background=_BG_ALT, foreground=_FG, borderwidth=0)
    style.map(
        "TButton",
        background=[("active", _ACCENT), ("disabled", _BG_ALT)],
        foreground=[("disabled", _FG_DIM)],
    )
    style.configure("TLabel", background=_BG, foreground=_FG)
    style.configure("TNotebook", background=_BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab", background=_BG_ALT, foreground=_FG_DIM, padding=(12, 6)
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", _BG), ("active", _BG_ALT)],
        foreground=[("selected", _FG), ("active", _FG)],
    )
    style.configure("SectionHeader.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
    return style


class MainWindow:
    """Ventana principal. Orquesta la UI y delega trabajo al controller.

    MVC ligero: MainWindow = View+Controller (UI), DiagnosticsController =
    Controller (worker), RunFullDiagnostics = Model/UseCase. La MainWindow
    no conoce implementaciones concretas de los Protocol — solo el caso
    de uso ya construido (composition_root).
    """

    def __init__(
        self,
        *,
        use_case: RunFullDiagnostics,
        targets: DiagnosticTargets,
        params: DiagnosticParams,
        series_source: SeriesDataSource | None = None,
    ) -> None:
        self._use_case = use_case
        self._targets = targets
        self._params = params
        self._series_source = series_source
        self._controller = DiagnosticsController(
            use_case=use_case,
            targets=targets,
            params=params,
            on_progress=self._on_progress,
            on_result=self._on_result,
            on_error=self._on_error,
        )

        self._root = tk.Tk()
        self._root.title("Game Network Diagnostics")
        self._root.geometry("920x620")
        self._root.minsize(720, 480)
        apply_dark_theme(self._root)

        self._build_layout()

    def _build_layout(self) -> None:
        # Top bar: titulo + boton run + estado
        top = ttk.Frame(self._root, padding=(12, 8))
        top.pack(side="top", fill="x")

        ttk.Label(
            top, text="Game Network Diagnostics", style="SectionHeader.TLabel"
        ).pack(side="left")

        self._run_button = ttk.Button(
            top,
            text="Run Diagnostics",
            command=self._on_click_run,
            style="Accent.TButton",
        )
        self._run_button.pack(side="right", padx=(0, 0))

        self._status_label = ttk.Label(top, text="Listo.", foreground=_FG_DIM)
        self._status_label.pack(side="right", padx=(0, 16))

        # Notebook con las 5 secciones
        nb = ttk.Notebook(self._root)
        nb.pack(side="top", fill="both", expand=True, padx=8, pady=8)

        self._sec_current = CurrentStatusSection(nb)
        nb.add(self._sec_current, text="Current Status")
        self._sec_tests = NetworkTestsSection(nb)
        nb.add(self._sec_tests, text="Network Tests")
        self._sec_route = RouteAnalysisSection(nb)
        nb.add(self._sec_route, text="Route Analysis")
        self._sec_hist = HistoricalComparisonSection(nb)
        nb.add(self._sec_hist, text="Historical Comparison")
        self._sec_rec = RecommendationsSection(nb)
        nb.add(self._sec_rec, text="Recommendations")
        self._sec_charts = ChartsSection(nb)
        nb.add(self._sec_charts, text="Charts")
        if self._series_source is not None:
            self._sec_charts.set_source(self._series_source)

        # Inicialmente vacias
        for sec in (
            self._sec_current,
            self._sec_tests,
            self._sec_route,
            self._sec_hist,
            self._sec_rec,
        ):
            sec.update_state({})

    # --- Boton callback ---

    def _on_click_run(self) -> None:
        if self._controller.is_running():
            return
        self._run_button.configure(state="disabled")
        self._status_label.configure(text="Ejecutando diagnóstico...")
        self._controller.run_async()

    # --- Controller callbacks (ejecutados desde worker thread) ---
    # Estos metodos se invocan desde el thread del controller, por lo que
    # solo agendamos UI updates via `self._root.after(0, ...)`.

    def _on_progress(self, stage: str) -> None:
        self._root.after(
            0, lambda: self._status_label.configure(text=f"Etapa: {stage}")
        )

    def _on_result(self, run: DiagnosticRun) -> None:
        self._root.after(0, lambda: self._apply_run(run))

    def _on_error(self, msg: str) -> None:
        self._root.after(0, lambda: self._apply_error(msg))

    # --- Aplicacion de resultados en el main loop ---

    def _apply_run(self, run: DiagnosticRun) -> None:
        """Aplica el resultado del run a todas las secciones (main loop)."""
        # Baselines ya computados en Etapa 5 del use_case (execute()) en
        # el worker thread. Los reutilizamos aca (main loop) SIN pedir
        # una nueva conn — Regla de Oro 9.1. Antes de Fase 9 fix, esto
        # llamaba compute_baseline(db) donde db era la conn del worker
        # thread -> nuevo ProgrammingError cross-thread cuando la UI
        # trata de leer. Ahora el use_case expone ``last_baselines``.
        baselines: dict[str, object] = dict(
            getattr(self._use_case, "last_baselines", {}) or {}
        )

        current_state = {
            "recommendation": run.recommendation,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        tests_state = {"probes": run.probes}
        route_state = {"traceroutes": run.traceroutes}
        hist_state = {
            "baselines": baselines,
            "probes": run.probes,
        }
        rec_state = {
            "recommendation": run.recommendation,
            "probes": run.probes,
        }

        self._sec_current.update_state(current_state)
        self._sec_tests.update_state(tests_state)
        self._sec_route.update_state(route_state)
        self._sec_hist.update_state(hist_state)
        self._sec_rec.update_state(rec_state)

        # Charts: auto-refresh para que los nuevos datos del run aparezcan
        # en los gráficos sin que el usuario tenga que tocar "Refresh".
        # El refresh es sync (queries rápidas) y solo si hay source seteada.
        if self._series_source is not None:
            try:
                self._sec_charts.refresh()
            except Exception:  # noqa: BLE001 — no romper la UI por un chart
                logger.exception("Falla refrescando charts tras run")

        self._run_button.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self._status_label.configure(text=f"Listo (últ. corrida: {ts}).")

    def _apply_error(self, msg: str) -> None:
        self._run_button.configure(state="normal")
        self._status_label.configure(text=f"Error: {msg}")
        # Mostrar en seccion Current Status tambien
        self._sec_current.update_state(
            {
                "recommendation": None,
                "_error": msg,
            }
        )

    # --- Loop ---

    def run(self) -> None:
        self._root.mainloop()
