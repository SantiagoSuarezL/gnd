"""ChartsSection — pestaña "Charts" con los 5 gráficos del PRD §10 (Fase 10).

Layout:
- Scroll vertical con los 5 gráficos apilados (cada uno en un Frame que
  contiene un ``FigureCanvasTkAgg`` — el widget Tk que embebe un
  ``matplotlib.figure.Figure``).
- Botón "Refresh Charts" arriba: pide queries a ``SeriesDataSource`` y
  re-renderiza on-demand. La MainWindow le inyecta la source (la real en
  composition_root, una fake en tests).
- Empty state por gráfico: si la query devuelve 0 datos, el renderer pinta
  el mensaje "Sin datos suficientes" (ver ``charts.py``).

Threading (Regla de Oro 9.1):
- ``SeriesDataSource`` pide su propia conn en el hilo del caller (main loop
  en este caso). Las queries son O(miles de rows) y viven <100ms, así que
  no bloquean el main loop perceptiblemente. Si la DB creciera mucho,
  mover el refresh a un worker thread es un refactor trivial (mismo
  patrón que ``DiagnosticsController``).
- Los ``Figure`` se construyen SIN backend interactivo en la creación del
  canvas — ``FigureCanvasTkAgg`` es el único que pide Tk.

Performance:
- En cada refresh, los ``Figure`` viejos se cierran explícitamente
  (``plt.close(fig)``) antes de instanciar los nuevos — matplotlib guarda
  figures en un registry global si no se cierran, y eso genera leaks en
  refresh repetidos. Esta es el área más delicada de esta sección.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any

from matplotlib import pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from gnd.visualization import ChartDataSet, SeriesDataSource
from gnd.visualization.charts import all_renderers

logger = logging.getLogger(__name__)


# Paleta dark (sincronizada con ui/main_window.py y charts.py)
_BG = "#1e1e1e"
_BG_ALT = "#252526"
_FG = "#d4d4d4"
_FG_DIM = "#808080"
_ACCENT = "#007acc"
_BORDER = "#3c3c3c"


# Configuración de los 5 gráficos: (key, title visible, query_builder).
# Cada entry dicta qué método del SeriesDataSource llamar y con qué kwargs.
# El orden de la lista define el orden de renderizado en la pestaña.
def _chart_specs() -> list[tuple[str, str, str, dict[str, Any]]]:
    """
    Returns:
        List of (key, display_title, source_method_name, kwargs). ``key``
        debe matchear una entrada de ``all_renderers()``.
    """
    return [
        (
            "latency_over_time",
            "1. Latencia a lo largo del tiempo",
            "latency_over_time",
            {"providers": ["google", "cloudflare", "quad9", "riot_public"]},
        ),
        (
            "packet_loss_over_time",
            "2. Pérdida de paquetes histórica",
            "packet_loss_over_time",
            {"providers": ["google", "cloudflare", "quad9", "riot_public"]},
        ),
        (
            "cloudflare_vs_google",
            "3. Cloudflare vs Google",
            "cloudflare_vs_google",
            {"period_days": 30},
        ),
        (
            "riot_latency_over_time",
            "4. Latencia Riot histórica",
            "riot_latency_over_time",
            {"provider": "riot_public", "period_days": 30},
        ),
        (
            "best_hours_to_play",
            "5. Mejores horas para jugar",
            "best_hours_to_play",
            {"provider": "riot_public", "period_days": 30},
        ),
    ]


class ChartsSection(ttk.Frame):
    """Pestaña "Charts": los 5 gráficos apilados con scroll vertical.

    La MainWindow construye una instancia y la mete en el Notebook. La
    source (SqliteSeriesDataSource o una fake) se setea via
    ``set_source(source)`` ANTES de llamar a ``refresh()``. Si la source
    no está seteada, ``refresh`` muestra empty state en los 5 gráficos.

    Threading: este widget vive en el main loop de Tk. Los refresh se
    hacen sync (queries rápidas). Si en el futuro se hace async, el
    patrón es el mismo que DiagnosticsController: worker thread + callback
    agendado via ``root.after(0, ...)``.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=8)
        self._source: SeriesDataSource | None = None
        self._canvases: list[FigureCanvasTkAgg] = []
        self._figures: list[Figure] = []
        self._build()

    # ── Layout ──────────────────────────────────────────────────────

    def _build(self) -> None:
        # Bar superior: título + botón refresh + label de estado.
        top = ttk.Frame(self)
        top.pack(side="top", fill="x")

        ttk.Label(
            top,
            text="Visualizaciones (datos reales de la DB)",
            style="SectionHeader.TLabel",
        ).pack(side="left")

        self._status_label = ttk.Label(top, text="—", foreground=_FG_DIM)
        self._status_label.pack(side="right", padx=(8, 0))

        self._refresh_button = ttk.Button(
            top,
            text="Refresh Charts",
            command=self._on_refresh_click,
            style="Accent.TButton",
        )
        self._refresh_button.pack(side="right")

        # Scroll area para los 5 gráficos.
        outer = ttk.Frame(self)
        outer.pack(side="top", fill="both", expand=True, pady=(6, 0))

        canvas = tk.Canvas(outer, bg=_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self._scroll_frame = ttk.Frame(canvas)
        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        self._canvas_win_id = canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw"
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._canvas_win_id, width=e.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse-wheel scrolling (tkinter no lo hace nativo en Windows).
        def _on_wheel(event: tk.Event) -> None:
            # Windows: event.delta es múltiplo de 120.
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_wheel)

        # Pre-build 5 placeholders del tamaño del contenedor para que el
        # layout no salte cuando se rendericen los charts reales.
        self._chart_containers: list[ttk.Frame] = []
        for _, title, _, _ in _chart_specs():
            container = ttk.Frame(self._scroll_frame, padding=(0, 8))
            container.pack(side="top", fill="x")
            ttk.Label(container, text=title, style="SectionHeader.TLabel").pack(
                side="top", anchor="w", padx=2
            )
            placeholder = ttk.Label(
                container,
                text="(click Refresh Charts para generar)",
                foreground=_FG_DIM,
            )
            placeholder.pack(side="top", anchor="w", padx=2)
            self._chart_containers.append(container)

    # ── API pública ─────────────────────────────────────────────────

    def set_source(self, source: SeriesDataSource) -> None:
        """Inyecta la fuente de series (DI). Llamar antes de ``refresh``."""
        self._source = source

    def refresh(self) -> None:
        """Vuelve a consultar la DB y re-renderiza los 5 gráficos.

        Llamar desde el main loop (no desde un worker thread — matplotlib
        + FigureCanvasTkAgg no son thread-safe; si se quiere async hay
        que compute figure en worker y solo ``draw()`` en main).
        """
        if self._source is None:
            self._status_label.configure(
                text="Sin data source configurada. Ejecute un diagnóstico primero.",
                foreground=_FG_DIM,
            )
            return
        self._render_all()

    # ── Rendering ──────────────────────────────────────────────────

    def _on_refresh_click(self) -> None:
        self.refresh()

    def _render_all(self) -> None:
        """Itera los 5 specs, ejecuta la query + render en cada container."""
        # Limpiar canvas anteriores (matplotlib leak si no cerramos figures).
        self._clear_canvases()

        renderers = all_renderers()
        specs = _chart_specs()
        total_points = 0

        for i, (key, _display, method_name, kwargs) in enumerate(specs):
            try:
                dataset = self._fetch_dataset(method_name, kwargs)
            except Exception as exc:  # noqa: BLE001 — no matar la UI entera
                logger.exception("Falla en query %s", key)
                self._render_error(self._chart_containers[i], f"Error: {exc!r}")
                continue

            total_points += len(dataset.points)
            renderer = renderers[key]
            fig = renderer(dataset)
            self._figures.append(fig)
            self._embed_figure(self._chart_containers[i], fig)

        self._status_label.configure(
            text=f"{total_points} puntos en {len(specs)} gráficos.",
            foreground=_FG_DIM,
        )

    def _fetch_dataset(self, method_name: str, kwargs: dict[str, Any]) -> ChartDataSet:
        """Despacha la query al SeriesDataSource por reflection controlada."""
        if self._source is None:
            return ChartDataSet.empty(title="—", y_label="—")
        method = getattr(self._source, method_name)
        return method(**kwargs)

    def _embed_figure(self, container: ttk.Frame, fig: Figure) -> None:
        """Embebe un Figure en un container, destruyendo el placeholder previo."""
        for child in container.winfo_children():
            # Mantener el header (Label con título) — borramos el resto.
            if (
                not isinstance(child, ttk.Label)
                or child.cget("style") != "SectionHeader.TLabel"
            ):
                child.destroy()

        canvas = FigureCanvasTkAgg(fig, master=container)
        canvas.draw()
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self._canvases.append(canvas)

    def _render_error(self, container: ttk.Frame, msg: str) -> None:
        """Muestra un error local en un gráfico sin romper el resto."""
        for child in container.winfo_children():
            if (
                not isinstance(child, ttk.Label)
                or child.cget("style") != "SectionHeader.TLabel"
            ):
                child.destroy()
        ttk.Label(container, text=msg, foreground="#c62828").pack(
            side="top", anchor="w", padx=2
        )

    def _clear_canvases(self) -> None:
        """Cierra matplotlib figures y destruye canvases previos.

        matplotlib guarda figures en ``pyplot.figure()`` registry — si no
        se cierran explícitamente, refresh repetidos acumulan memoria.
        """
        for c in self._canvases:
            try:
                c.get_tk_widget().destroy()
            except tk.TclError:
                pass
        self._canvases.clear()

        for fig in self._figures:
            plt.close(fig)
        self._figures.clear()
