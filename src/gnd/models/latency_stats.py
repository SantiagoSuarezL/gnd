"""Estadísticas de latencia de un sondeo.

Invariante (TECHNICAL_SPEC.md §1, IMPLEMENTATION_PLAN.md Fase 1):
- packet_loss_pct en [0, 100]
- min_ms <= avg_ms <= max_ms
- samples >= 0
- jitter_ms >= 0
- avg_ms, min_ms, max_ms >= 0
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LatencyStats:
    avg_ms: float
    min_ms: float
    max_ms: float
    jitter_ms: float
    packet_loss_pct: float
    samples: int

    def __post_init__(self) -> None:
        if not (0.0 <= self.packet_loss_pct <= 100.0):
            raise ValueError(
                f"packet_loss_pct debe estar en [0, 100], fue {self.packet_loss_pct}"
            )
        if self.samples < 0:
            raise ValueError(f"samples debe ser >= 0, fue {self.samples}")
        if self.jitter_ms < 0.0:
            raise ValueError(f"jitter_ms debe ser >= 0, fue {self.jitter_ms}")
        if self.min_ms < 0.0 or self.avg_ms < 0.0 or self.max_ms < 0.0:
            raise ValueError("latencias (min/avg/max) deben ser >= 0")
        if not (self.min_ms <= self.avg_ms <= self.max_ms):
            raise ValueError(
                f"debe cumplirse min<=avg<=max: min={self.min_ms} "
                f"avg={self.avg_ms} max={self.max_ms}"
            )
