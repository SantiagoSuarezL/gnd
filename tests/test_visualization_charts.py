"""Tests de charts.py (Fase 10) — render puro sobre fig/ax.

EP §4: usa backend matplotlib ``Agg`` (headless, no interactivo, no abre
ventana Tk). Los tests VALIDAN que fig/ax se construyen correctamente
sin importar la UI → coverage barata y densa.

Verifica:
- Cada renderer devuelve una ``Figure`` no nula con tema dark aplicado.
- Empty data → figure contiene el mensaje de empty state visible.
- Non-empty data → axes contienen los puntos (lines/bars) esperados.
- Theme dark: facecolor de axes es ``#1e1e1e`` (consistencia con UI).

NO importa tkinter, NO usa FigureCanvasTkAgg — eso se cubre en el
smoke test de UI (test_main_window_smoke.py) que ya tiene Tk importado.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # FORZADO antes de pyplot. Headless. No abre GUI.

from datetime import datetime, timedelta  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402 — import after use('Agg')
import pytest  # noqa: E402

from gnd.visualization import (  # noqa: E402
    ChartDataSet,
    SeriesPoint,
    all_renderers,
)
from gnd.visualization.charts import (  # noqa: E402
    _ACCENT,
    _BG,
    render_best_hours_to_play,
    render_cloudflare_vs_google,
    render_latency_over_time,
    render_packet_loss_over_time,
    render_riot_latency_over_time,
)

NOW = datetime(2026, 7, 27, 14, 0, 0)


def _seed_series(providers: list[str], n: int = 10) -> tuple[SeriesPoint, ...]:
    """Construye n puntos por provider, ordenados cronológicamente."""
    pts: list[SeriesPoint] = []
    for provider in providers:
        for i in range(n):
            ts = NOW - timedelta(hours=n - i)
            pts.append(SeriesPoint(x=ts, y=15.0 + i * 0.5, group=provider))
    # Sort por timestamp para respetar la invariante del ChartDataSet.
    pts.sort(key=lambda p: (p.x, p.group))
    return tuple(pts)


def _make_dataset(
    *,
    title: str = "Test chart",
    y_label: str = "ms",
    points: tuple[SeriesPoint, ...] = (),
    x_label: str = "Fecha",
) -> ChartDataSet:
    return ChartDataSet(title=title, y_label=y_label, points=points, x_label=x_label)


@pytest.fixture(autouse=True)
def _close_figures_after_test():
    """Cerrar figures después de cada test para no acumular en pyplot.

    pytest fixture autouse → se ejecuta después del yield. Sin esto
    vulture/runtime puede reservar memoria entre tests para figures
    añadidas al pyplot global registry.
    """
    yield
    plt.close("all")


def test_all_renderers_returns_five_entries() -> None:
    """El PRD §10 enumera 5 gráficos — el mapa expone justo esos 5."""
    renderers = all_renderers()
    assert set(renderers.keys()) == {
        "latency_over_time",
        "packet_loss_over_time",
        "cloudflare_vs_google",
        "riot_latency_over_time",
        "best_hours_to_play",
    }


def test_render_latency_over_time_returns_figure() -> None:
    ds = _make_dataset(points=_seed_series(["google", "cloudflare"], n=5))
    fig = render_latency_over_time(ds)
    assert fig is not None
    assert len(fig.axes) == 1


def test_render_latency_over_time_applies_dark_bg() -> None:
    """El axes del chart tiene fondo _BG (consistencia con ui/main_window.py)."""
    ds = _make_dataset(points=_seed_series(["google"], n=3))
    fig = render_latency_over_time(ds)
    ax = fig.axes[0]
    bg_rgb = tuple(ax.get_facecolor())[:3]
    expected_rgb = _parse_color(_BG)[:3]
    assert bg_rgb == expected_rgb


def test_render_latency_over_time_empty_shows_message() -> None:
    """Empty dataset → el axes contiene texto 'Sin datos suficientes'."""
    ds = ChartDataSet.empty("test", "ms")
    fig = render_latency_over_time(ds)
    texts = [t.get_text() for t in fig.axes[0].texts]
    assert any("Sin datos suficientes" in t for t in texts)


def test_render_packet_loss_empty_shows_message() -> None:
    ds = ChartDataSet.empty("test", "%")
    fig = render_packet_loss_over_time(ds)
    texts = [t.get_text() for t in fig.axes[0].texts]
    assert any("Sin datos suficientes" in t for t in texts)


def test_render_packet_loss_over_time_includes_fill() -> None:
    """Packet loss se grafica con fill_between para visualizar área."""
    ds = _make_dataset(points=_seed_series(["google"], n=4))
    fig = render_packet_loss_over_time(ds)
    # Una PolyCollection (fill_between) genera collections no vacías.
    assert len(fig.axes[0].collections) > 0


def test_render_cloudflare_vs_google_returns_figure() -> None:
    ds = _make_dataset(points=_seed_series(["cloudflare", "google"], n=3))
    fig = render_cloudflare_vs_google(ds)
    assert fig is not None


def test_render_riot_latency_single_series_with_accent_color() -> None:
    """El Riot chart usa _ACCENT como color de la línea principal."""
    ds = _make_dataset(points=_seed_series(["riot_public"], n=3))
    fig = render_riot_latency_over_time(ds)
    lines = fig.axes[0].lines
    assert len(lines) >= 1
    color = lines[0].get_color()
    # color viene como tuple de floats o string ("#007acc" o "(0,0.478,...)")
    # lo comparamos comparando contra el rgb parseado de _ACCENT.
    assert _normalize_color(color)[:3] == _parse_color(_ACCENT)[:3]


def test_render_best_hours_uses_bars() -> None:
    """Best hours = bar chart de latex media por hora."""
    pts = tuple(
        SeriesPoint(x=datetime(2000, 1, 1, h), y=12.0 + h, group=f"{h:02d}")
        for h in range(24)
    )
    ds = _make_dataset(
        title="Best hours",
        y_label="ms",
        points=pts,
        x_label="Hora del día",
    )
    fig = render_best_hours_to_play(ds)
    # bar chart crea BarContainer en ax.containers.
    assert len(fig.axes[0].containers) > 0


def test_render_best_hours_annotates_n_samples_per_bar() -> None:
    """Kickoff 2026-07-27: cada barra lleva "n=X" para que el usuario
    vea cuántas muestras la representan. Sin esto, una sola barra con
    n=5 podría confundirse con conclusión firme."""
    pts = tuple(
        SeriesPoint(
            x=datetime(2000, 1, 1, h),
            y=12.0 + h,
            group=f"{h:02d}",
            metadata={"n_samples": 7},
        )
        for h in range(3)
    )
    ds = _make_dataset(
        title="Best hours",
        y_label="ms",
        points=pts,
        x_label="Hora del día",
    )
    fig = render_best_hours_to_play(ds)
    n_labels = [
        a.get_text() for a in fig.axes[0].texts if a.get_text().startswith("n=")
    ]
    assert len(n_labels) == 3
    assert all("7" in a for a in n_labels)


def test_render_best_hours_min_bar_uses_accent() -> None:
    """El bar con valor mínimo se pinta con _ACCENT (destaque visual)."""
    pts = tuple(
        SeriesPoint(
            x=datetime(2000, 1, 1, h), y=20.0 - (10 if h == 3 else 0), group=f"{h:02d}"
        )
        for h in range(0, 24)
    )
    ds = _make_dataset(title="x", y_label="ms", points=pts)
    fig = render_best_hours_to_play(ds)
    bars = fig.axes[0].containers[0]
    # Encontrar el bar con menor altura → su color debe estar cerca de _ACCENT.
    heights = [b.get_height() for b in bars]
    min_idx = heights.index(min(heights))
    accent_rgb = _parse_color(_ACCENT)
    bar_color = _normalize_color(bars[min_idx].get_facecolor())
    assert bar_color[:3] == accent_rgb[:3]


# ── packet_loss_over_time: auto-zoom Y axis (cierre Fase 10) ────────


def _make_loss_dataset(pts: tuple[SeriesPoint, ...]) -> ChartDataSet:
    """Helper: dataset típico de packet_loss_over_time."""
    return _make_dataset(
        title="Packet loss",
        y_label="Packet loss (%)",
        points=pts,
    )


def test_packet_loss_chart_ylim_autoescala_con_datos_bajos() -> None:
    """Datos reales típicos (<1%) → ylim_top escala con headroom, sin
    aplastar los puntos contra el piso.

    Cálculo esperado: max_y < 1.0 → max_y*1.2 < 1.2 → max(5.0, ...) = 5.0
    → ylim_top = 5.0 (piso mínimo). El gráfico muestra 5% de rango en vez
    de 100%, dejando los puntos diferenciables.
    """
    pts = tuple(
        SeriesPoint(
            x=datetime(2026, 7, 27, h),
            y=0.1 + 0.05 * h,  # 0.1% a 1.15% en 24 puntos.
            group="google",
        )
        for h in range(24)
    )
    ds = _make_loss_dataset(pts)
    fig = render_packet_loss_over_time(ds)
    ylim = fig.axes[0].get_ylim()
    assert ylim[1] < 10  # < 10% confirma auto-zoom (no el rango 0-100%).
    assert ylim[0] == 0.0
    assert ylim[1] == 5.0  # piso mínimo aplicado.


def test_packet_loss_chart_ylim_respeta_tope_100_con_pico_alto() -> None:
    """Un valor de 90% en el dataset → ylim_top <= 100 (no se rompe el
    rango físicamente posible).

    Cálculo: max_y = 90 → max_y*1.2 = 108 → min(100.0, 108) = 100.
    """
    pts = tuple(
        SeriesPoint(
            x=datetime(2026, 7, 27, h),
            y=90.0 if h == 12 else 0.5,  # un pico de 90% al mediodía.
            group="cloudflare",
        )
        for h in range(24)
    )
    ds = _make_loss_dataset(pts)
    fig = render_packet_loss_over_time(ds)
    ylim = fig.axes[0].get_ylim()
    assert ylim[1] <= 100.0
    assert ylim[1] == 100.0  # tope 100% aplicado.


def test_packet_loss_chart_ylim_piso_minimo_con_todo_cero() -> None:
    """Todos los valores en 0% → ylim_top = 5.0 (piso), no colapsa a (0,0).

    El gráfico sigue siendo legible aunque no haya pérdidas reales.
    """
    pts = tuple(
        SeriesPoint(
            x=datetime(2026, 7, 27, h),
            y=0.0,
            group="google",
        )
        for h in range(10)
    )
    ds = _make_loss_dataset(pts)
    fig = render_packet_loss_over_time(ds)
    ylim = fig.axes[0].get_ylim()
    assert ylim[0] == 0.0
    assert ylim[1] >= 5.0  # piso mínimo: no colapsa a (0,0).
    assert ylim[1] == 5.0


# ── Helpers ──────────────────────────────────────────────────────────


def _parse_color(hex_string: str) -> tuple[float, float, float, float]:
    """Convierte '#rrggbb' en RGBA float tuple (0..1)."""
    from matplotlib.colors import to_rgba

    return to_rgba(hex_string)


def _normalize_color(c) -> tuple[float, ...]:
    """Acepta '#rrggbb' o (r,g,b[,a]) float y normaliza a tuple[float, ...]."""
    from matplotlib.colors import to_rgba

    if isinstance(c, str):
        return to_rgba(c)
    return tuple(c)  # (r,g,b[,a])
