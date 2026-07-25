"""Calculo de baseline historico por provider.

TECHNICAL_SPEC.md §4.1: la comparacion usa avg + k*stddev (no promedio
simple) para evitar falsos positivos por fluctuacion normal de red.
Regla clave (§3): jamas mezclar providers — riot_public != riot_game_server.

Normalizacion del score (§4.2), documentada en codigo (ENGINEERING_PRINCIPLES.md §1.4):
  Cada componente se mapea a un valor 0-100 usando la formula documentada
  en cada funcion normalize_*. El score final es la suma ponderada de estos
  valores normalizados segun la tabla de pesos del spec.
"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timedelta

from gnd.models.historical_baseline import HistoricalBaseline

# k por defecto para la regla avg + k*stddev (TECHNICAL_SPEC.md §4.1).
# Un probe se marca como anomalo si su latencia > avg + DEVIATION_FACTOR * stddev.
DEVIATION_FACTOR: float = 2.0


def compute_baseline(
    conn: sqlite3.Connection,
    provider: str,
    period_days: int = 30,
    *,
    now: datetime | None = None,
) -> HistoricalBaseline:
    """Computa el baseline historico de latencia para un provider.

    Solo usa probes con outcome='SUCCESS' dentro del periodo dado.
    Nunca mezcla providers — TECHNICAL_SPEC.md §3.

    Args:
        conn: conexion SQLite con la tabla probe_results.
        provider: clave del provider ('local', 'google', 'riot_public', etc.).
        period_days: ventana historica en dias (default 30).
        now: instante de referencia para el calculo del cutoff (inyectable
             para tests deterministas, EP §4).

    Returns:
        HistoricalBaseline con avg_ms, stddev_ms y sample_count.
        Si no hay samples, devuelve zeros (no falla).
    """
    ref = now or datetime.now()
    cutoff = (ref - timedelta(days=period_days)).isoformat()

    rows = conn.execute(
        """SELECT avg_ms FROM probe_results
           WHERE provider = ?
             AND outcome = 'SUCCESS'
             AND timestamp >= ?
           ORDER BY timestamp""",
        (provider, cutoff),
    ).fetchall()

    samples = [r[0] for r in rows if r[0] is not None]

    if not samples:
        return HistoricalBaseline(
            provider=provider,
            period_days=period_days,
            avg_ms=0.0,
            stddev_ms=0.0,
            sample_count=0,
        )

    avg = statistics.mean(samples)
    # stddev requiere al menos 2 samples; con 1 sample, stddev = 0.
    stddev = statistics.stdev(samples) if len(samples) > 1 else 0.0

    return HistoricalBaseline(
        provider=provider,
        period_days=period_days,
        avg_ms=avg,
        stddev_ms=stddev,
        sample_count=len(samples),
    )


def is_anomaly(
    latency_ms: float,
    baseline: HistoricalBaseline,
    *,
    factor: float = DEVIATION_FACTOR,
) -> bool:
    """Determina si una latencia es anomala segun la regla avg + k*stddev.

    Un valor se marca como anomalo si:
        latency_ms > baseline.avg_ms + (factor * baseline.stddev_ms)

    Si baseline.sample_count == 0, siempre retorna False (sin datos = sin
    juicio, no anomalía).
    """
    if baseline.sample_count == 0:
        return False
    threshold = baseline.avg_ms + (factor * baseline.stddev_ms)
    return latency_ms > threshold
