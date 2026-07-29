"""Puertos de la capa de visualización (Fase 10).

ARCHITECTURE.md §3: ``visualization/`` "Generación de gráficos a partir de
datos ya calculados. No calcula ni interpreta datos."  Por eso las queries
que alimentan los gráficos viven en ``queries.py`` — son lecturas puras
contra SQLite, no lógica de negocio. Los gráficos solo pintan lo que las
queries devuelven.

EP §2.D / §3 (DI por constructor): los consumers de queries no abren una
``sqlite3.Connection`` por su cuenta — reciben un ``SeriesDataSource``
(Protocol) que la pide via ``DatabaseConnectionFactory`` (Regla de Oro 9.1:
una conexion por hilo, nunca compartida).
"""

from __future__ import annotations

from typing import Protocol

from gnd.visualization.models import ChartDataSet


class SeriesDataSource(Protocol):
    """Fuente de series históricas para los 5 gráficos del PRD §10.

    Implementación real: ``SqliteSeriesDataSource`` (queries.py). Los tests
    usan ``FakeSeriesDataSource`` (in-memory) para no tocar SQLite.

    Contrato: cada método devuelve un ``ChartDataSet`` ya filtrado y
    ordenado cronológicamente. La capa de visualización NO filtra, NO
    dedupe, NO re-ordena. Si el resultado es vacío, devuelve
    ``ChartDataSet.empty()`` y la UI decide cómo mostrarlo (empty state).
    """

    def latency_over_time(
        self,
        *,
        providers: list[str],
        period_days: int = 30,
    ) -> ChartDataSet: ...

    def packet_loss_over_time(
        self,
        *,
        providers: list[str],
        period_days: int = 30,
    ) -> ChartDataSet: ...

    def cloudflare_vs_google(
        self,
        *,
        period_days: int = 30,
    ) -> ChartDataSet: ...

    def riot_latency_over_time(
        self,
        *,
        provider: str = "riot_public",
        period_days: int = 30,
    ) -> ChartDataSet: ...

    def best_hours_to_play(
        self,
        *,
        provider: str = "riot_public",
        period_days: int = 30,
        min_samples: int = 3,
    ) -> ChartDataSet: ...
