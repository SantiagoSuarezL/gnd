"""Capa de visualización (Fase 10) — 5 gráficos del PRD §10.

ARQUITECTURA §3: "Generación de gráficos a partir de datos ya calculados.
No calcula ni interpreta datos."

Capas:
- ``models.py``: DTOs inmutables (``ChartDataSet``, ``SeriesPoint``).
- ``ports.py``: ``SeriesDataSource`` Protocol (queries históricas).
- ``queries.py``: ``SqliteSeriesDataSource`` (implementación real).
- ``charts.py``: 5 funciones puras ``ChartDataSet`` → ``matplotlib.figure.Figure``.

Los 5 gráficos del PRD §10:
1. Latencia en el tiempo (multi-provider).
2. Packet loss histórico (multi-provider).
3. Cloudflare vs Google (comparativa).
4. Latencia Riot histórica (single-series).
5. Mejores horas para jugar (bar chart por hora).

Tests relevantes: ``tests/test_visualization_queries.py`` (queries),
``tests/test_visualization_charts.py`` (render con backend Agg).
"""

from gnd.visualization.charts import (
    all_renderers,
    render_best_hours_to_play,
    render_cloudflare_vs_google,
    render_latency_over_time,
    render_packet_loss_over_time,
    render_riot_latency_over_time,
)
from gnd.visualization.models import ChartDataSet, SeriesPoint
from gnd.visualization.ports import SeriesDataSource
from gnd.visualization.queries import SqliteSeriesDataSource

__all__ = [
    "ChartDataSet",
    "SeriesPoint",
    "SeriesDataSource",
    "SqliteSeriesDataSource",
    "all_renderers",
    "render_best_hours_to_play",
    "render_cloudflare_vs_google",
    "render_latency_over_time",
    "render_packet_loss_over_time",
    "render_riot_latency_over_time",
]
