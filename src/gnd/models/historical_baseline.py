"""Baseline histórica por provider para comparación estadística.

TECHNICAL_SPEC.md §4.1: la comparación usa avg + k*stddev (no promedio
simple) para evitar falsos positivos por fluctuación normal de red.
Regla clave (§3): jamás mezclar providers — riot_public != riot_game_server.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalBaseline:
    provider: str
    period_days: int
    avg_ms: float
    stddev_ms: float
    sample_count: int

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provider no puede ser vacío")
        if self.period_days < 1:
            raise ValueError(f"period_days debe ser >= 1, fue {self.period_days}")
        if self.avg_ms < 0.0:
            raise ValueError(f"avg_ms debe ser >= 0, fue {self.avg_ms}")
        if self.stddev_ms < 0.0:
            raise ValueError(f"stddev_ms debe ser >= 0, fue {self.stddev_ms}")
        if self.sample_count < 0:
            raise ValueError(f"sample_count debe ser >= 0, fue {self.sample_count}")
        # Un solo sample => stddev tiene que ser 0 (sin dispersión).
        if self.sample_count <= 1 and self.stddev_ms != 0.0:
            raise ValueError(
                f"stddev_ms debe ser 0 si sample_count<=1, fue {self.stddev_ms}"
            )
