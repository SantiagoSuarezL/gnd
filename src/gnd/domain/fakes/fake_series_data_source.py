"""Fake ``SeriesDataSource`` para tests de UI sin tocar DB (Fase 10).

Siguiendo el mismo patrón que ``FakeDiagnosticsRepository`` / ``FakePingRunner``:
implementación in-memory del ``SeriesDataSource`` Protocol para que los tests
de UI puedan ejercitar la pestaña Charts sin necesidad de SQLite (ni del
back-end matplotlib backend interactivo — el smoke test solo verifica que
se llame el método ``refresh()`` del ChartsSection sin falla).
"""

from __future__ import annotations

from datetime import datetime

from gnd.visualization.models import ChartDataSet, SeriesPoint


class FakeSeriesDataSource:
    """Implementación in-memory de ``SeriesDataSource``.

    Por defecto devuelve datos sintéticos no vacíos para que la UI tenga
    algo que renderizar. Los tests pueden inyectar datasets custom via
    constructor para validar edge cases (ej. empty state).
    """

    def __init__(
        self,
        *,
        latency_dataset: ChartDataSet | None = None,
        packet_loss_dataset: ChartDataSet | None = None,
        cloudflare_vs_google_dataset: ChartDataSet | None = None,
        riot_latency_dataset: ChartDataSet | None = None,
        best_hours_dataset: ChartDataSet | None = None,
    ) -> None:
        # Defaults: datasets sintéticos con 5 puntos por provider.
        self._latency = latency_dataset or _default_latency()
        self._packet_loss = packet_loss_dataset or _default_packet_loss()
        self._cloudflare_vs_google = cloudflare_vs_google_dataset or _default_latency()
        self._riot_latency = riot_latency_dataset or _default_latency()
        self._best_hours = best_hours_dataset or _default_best_hours()

    def latency_over_time(
        self, *, providers: list[str], period_days: int = 30
    ) -> ChartDataSet:
        return self._latency

    def packet_loss_over_time(
        self, *, providers: list[str], period_days: int = 30
    ) -> ChartDataSet:
        return self._packet_loss

    def cloudflare_vs_google(self, *, period_days: int = 30) -> ChartDataSet:
        return self._cloudflare_vs_google

    def riot_latency_over_time(
        self, *, provider: str = "riot_public", period_days: int = 30
    ) -> ChartDataSet:
        return self._riot_latency

    def best_hours_to_play(
        self, *, provider: str = "riot_public", period_days: int = 30
    ) -> ChartDataSet:
        return self._best_hours


def _default_latency() -> ChartDataSet:
    pts = tuple(
        SeriesPoint(
            x=datetime(2026, 7, 27, h),
            y=15.0 + h * 0.5,
            group="google",
        )
        for h in range(5)
    )
    return ChartDataSet(
        title="Latencia (fake)",
        y_label="ms",
        points=pts,
    )


def _default_packet_loss() -> ChartDataSet:
    pts = tuple(
        SeriesPoint(
            x=datetime(2026, 7, 27, h),
            y=float(h % 3),
            group="google",
        )
        for h in range(5)
    )
    return ChartDataSet(
        title="Loss (fake)",
        y_label="%",
        points=pts,
    )


def _default_best_hours() -> ChartDataSet:
    pts = tuple(
        SeriesPoint(
            x=datetime(2000, 1, 1, h),
            y=15.0 + h,
            group=f"{h:02d}",
        )
        for h in range(24)
    )
    return ChartDataSet(
        title="Best hours (fake)",
        y_label="ms",
        points=pts,
        x_label="Hora del día",
    )
