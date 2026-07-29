"""Funciones puras de renderización matplotlib (Fase 10).

ARCHITECTURE.md §3 para ``visualization/``: "Generación de gráficos a partir
de datos ya calculados. No calcula ni interpreta datos."

Cada función toma un ``ChartDataSet`` (datos listos) y devuelve una
``matplotlib.figure.Figure`` lista para embeber en Tk (FigureCanvasTkAgg)
o para salvar a PNG. NO tocan la DB, no filtran, no recomputan — solo
pintan lo que la query devolvió.

Regla de testing (EP §4): los tests de charts usan backend ``Agg``
(matplotlib.use("Agg")) que es no-interactivo y headless. Ningún test
abre una ventana, ningún test importa tkinter. Esto separa la prueba de
la lógica de render de la prueba de la integración en Tk.

Tema dark: usa los mismos hex que ``ui/main_window.py`` (_BG, _FG, _ACCENT)
para consistencia visual con el resto de la app.
"""

from __future__ import annotations

from collections.abc import Callable

from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from gnd.visualization.models import ChartDataSet

# ── Paleta dark (sincronizada con ui/main_window.py) ──────────────
_BG = "#1e1e1e"
_BG_ALT = "#252526"
_FG = "#d4d4d4"
_FG_DIM = "#808080"
_ACCENT = "#007acc"
_BORDER = "#3c3c3c"

# Paleta cíclica para series múltiples (2+ providers en un mismo chart):
# tonos suficientemente distinguibles sobre fondo dark.
_SERIES_COLORS = ["#4ec9b0", "#ce9178", "#569cd6", "#c586c0", "#dcdcaa", "#9cdcfe"]
_GRID_COLOR = "#3c3c3c"


def _style_dark_axes(ax: Axes) -> None:
    """Aplica tema dark a un Axes (background, ticks, spines, grid)."""
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_FG_DIM, which="both")
    for spine in ax.spines.values():
        spine.set_color(_BORDER)
    ax.title.set_color(_FG)
    ax.xaxis.label.set_color(_FG_DIM)
    ax.yaxis.label.set_color(_FG_DIM)
    ax.grid(True, color=_GRID_COLOR, linestyle="-", linewidth=0.4, alpha=0.7)
    ax.set_axisbelow(True)


def _finalize(fig: Figure) -> Figure:
    """Aplica fondo dark al figure y ajusta layout (tight_layout)."""
    fig.patch.set_facecolor(_BG)
    fig.tight_layout()
    return fig


def render_latency_over_time(dataset: ChartDataSet) -> Figure:
    """Render 1: latencia avg_ms en el tiempo, multi-series por provider.

    Línea + marcadores. Eje X = timestamp, eje Y = ms. Una serie por grupo
    (provider). Si ``dataset.is_empty`` devuelve un figure con mensaje de
    empty state en lugar de un gráfico vacío.
    """
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=100)
    _style_dark_axes(ax)

    if dataset.is_empty:
        ax.text(
            0.5,
            0.5,
            "Sin datos suficientes\nEjecutá diagnósticos para ver tendencias",
            ha="center",
            va="center",
            color=_FG_DIM,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(dataset.title, color=_FG)
        return _finalize(fig)

    for i, group in enumerate(dataset.groups):
        xs = [p.x for p in dataset.points if p.group == group]
        ys = [p.y for p in dataset.points if p.group == group]
        color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
        ax.plot(
            xs,
            ys,
            color=color,
            marker="o",
            markersize=3,
            linewidth=1.2,
            label=group,
        )

    ax.set_title(dataset.title)
    ax.set_ylabel(dataset.y_label)
    ax.set_xlabel(dataset.x_label)
    ax.legend(facecolor=_BG_ALT, edgecolor=_BORDER, labelcolor=_FG, fontsize=8)
    # Rotación de fechas para que no se superpongan.
    fig.autofmt_xdate(bottom=0.25)
    return _finalize(fig)


def render_packet_loss_over_time(dataset: ChartDataSet) -> Figure:
    """Render 2: packet loss % en el tiempo, multi-series por provider.

    Línea con área sombreada para enfatizar el carácter de pérdida.
    Eje Y auto-escalado (kickoff 2026-07-27, cierre de Fase 10):
        ylim_sup = min(100.0, max(5.0, max_y * 1.2))
    El piso de 5% evita gráficos "colapsados" cuando todos los valores
    están cerca de 0% (caso real, pérdida típica <2%). El headroom de
    1.2x deja espacio sobre el máximo observado si hay un pico de
    pérdida. El tope de 100% respeta el rango físicamente posible.
    Threshold warning/critical no se grafican acá (esa lógica vive en
    score.py); solo se pinta el dato.
    """
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=100)
    _style_dark_axes(ax)

    if dataset.is_empty:
        ax.text(
            0.5,
            0.5,
            "Sin datos suficientes\nEjecutá diagnósticos para ver tendencias",
            ha="center",
            va="center",
            color=_FG_DIM,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(dataset.title, color=_FG)
        return _finalize(fig)

    for i, group in enumerate(dataset.groups):
        xs = [p.x for p in dataset.points if p.group == group]
        ys = [p.y for p in dataset.points if p.group == group]
        color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
        ax.plot(
            xs,
            ys,
            color=color,
            marker="o",
            markersize=3,
            linewidth=1.2,
            label=group,
        )
        ax.fill_between(xs, ys, color=color, alpha=0.12)

    max_y = max((p.y for p in dataset.points), default=0.0)
    ylim_top = min(100.0, max(5.0, max_y * 1.2))
    ax.set_ylim(0, ylim_top)
    ax.set_title(dataset.title)
    ax.set_ylabel(dataset.y_label)
    ax.set_xlabel(dataset.x_label)
    ax.legend(facecolor=_BG_ALT, edgecolor=_BORDER, labelcolor=_FG, fontsize=8)
    fig.autofmt_xdate(bottom=0.25)
    return _finalize(fig)


def render_cloudflare_vs_google(dataset: ChartDataSet) -> Figure:
    """Render 3: comparativa Cloudflare vs Google (2 series).

    Misma estructura que ``render_latency_over_time`` — existe por
    separado porque el PRD §10 lo lista como gráfico independiente y
    permite customizar labels (ej. destacar diferencia) sin tocar el
    gráfico genérico.
    """
    return render_latency_over_time(dataset)


def render_riot_latency_over_time(dataset: ChartDataSet) -> Figure:
    """Render 4: latencia Riot histórica (single-series).

    Línea con marcador y color de acento (_ACCENT) para diferenciarlo del
    resto (es la métrica más crítica para el caso de uso del jugador
    competitivo: PRD user story #1).
    """
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=100)
    _style_dark_axes(ax)

    if dataset.is_empty:
        ax.text(
            0.5,
            0.5,
            "Sin datos suficientes\nEjecutá diagnósticos para ver tendencias",
            ha="center",
            va="center",
            color=_FG_DIM,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(dataset.title, color=_FG)
        return _finalize(fig)

    xs = [p.x for p in dataset.points]
    ys = [p.y for p in dataset.points]
    ax.plot(
        xs,
        ys,
        color=_ACCENT,
        marker="o",
        markersize=4,
        linewidth=1.5,
        label=dataset.groups[0] if dataset.groups else "",
    )

    ax.set_title(dataset.title)
    ax.set_ylabel(dataset.y_label)
    ax.set_xlabel(dataset.x_label)
    if dataset.groups:
        ax.legend(
            facecolor=_BG_ALT,
            edgecolor=_BORDER,
            labelcolor=_FG,
            fontsize=8,
            loc="best",
        )
    fig.autofmt_xdate(bottom=0.25)
    return _finalize(fig)


def render_best_hours_to_play(dataset: ChartDataSet) -> Figure:
    """Render 5: mejores horas para jugar — bar chart por hora del día.

    El bar más bajo = mejor hora (menor latencia). Se destaca el mínimo
    con el color de acento (_ACCENT); el resto en _SERIES_COLORS[0].
    """
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=100)
    _style_dark_axes(ax)

    if dataset.is_empty:
        ax.text(
            0.5,
            0.5,
            "Sin datos suficientes\nEjecutá diagnósticos para ver tendencias",
            ha="center",
            va="center",
            color=_FG_DIM,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(dataset.title, color=_FG)
        return _finalize(fig)

    # Eje X: las horas (group label "00".."23"). Eje Y: latencia media.
    labels = [p.group for p in dataset.points]
    values = [p.y for p in dataset.points]
    # n_samples de cada punto (metadata inyectado por best_hours_to_play).
    # Si no está, default 0 (no anotamos).
    n_samples_list = [int(p.metadata.get("n_samples", 0)) for p in dataset.points]

    if values:
        min_idx = values.index(min(values))
    else:
        min_idx = -1

    bar_colors = [
        _ACCENT if i == min_idx else _SERIES_COLORS[0] for i in range(len(values))
    ]
    ax.bar(labels, values, color=bar_colors, edgecolor=_BORDER, linewidth=0.4)

    # Anotar n_samples encima de cada barra para que el usuario vea
    # cuántas mediciones representan cada hora (kickoff 2026-07-27).
    # Sin n visible, una sola barra con n=5 podría confundirse con una
    # conclusión firme — ver Regla de Oro 10.4 (empty state vs. datos
    # engañosos).
    for i, n in enumerate(n_samples_list):
        if n > 0:
            ax.annotate(
                f"n={n}",
                xy=(i, values[i]),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                color=_FG_DIM,
                fontsize=7,
            )

    # Anotar el mínimo con un texto "★ Xms HH:00".
    if min_idx >= 0:
        best_label = labels[min_idx]
        best_val = values[min_idx]
        ax.annotate(
            f"★ {best_val:.1f}ms @ {best_label}:00",
            xy=(min_idx, best_val),
            xytext=(0, 22),
            textcoords="offset points",
            ha="center",
            color=_FG,
            fontsize=9,
        )

    ax.set_title(dataset.title)
    ax.set_ylabel(dataset.y_label)
    ax.set_xlabel(dataset.x_label)
    # Las etiquetas del eje X son horas "00".."23"; pueden ser muchas,
    # forzamos mostrarlas todas cada 2 para evitar overlap.
    if len(labels) > 12:
        for label in ax.get_xticklabels():
            label.set_fontsize(7)
    return _finalize(fig)


# Exportado para claridad (consumers pueden registrar el mapa completo).
def all_renderers() -> dict[str, Callable[[ChartDataSet], Figure]]:
    """Devuelve el mapa nombre → renderer (para iterar los 5 charts)."""
    return {
        "latency_over_time": render_latency_over_time,
        "packet_loss_over_time": render_packet_loss_over_time,
        "cloudflare_vs_google": render_cloudflare_vs_google,
        "riot_latency_over_time": render_riot_latency_over_time,
        "best_hours_to_play": render_best_hours_to_play,
    }
