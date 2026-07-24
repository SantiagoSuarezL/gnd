"""Resultados de traceroute y hops individuales.

TECHNICAL_SPEC.md §1:
- TracerouteHop.ip/hostname/rtt_ms son None si el hop no respondió —
  no implica error (comportamiento común de red).
- culprit_hop_index es el hop donde se detecta el salto de latencia anómalo,
  None si no se identificó culpable.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TracerouteHop:
    hop_number: int
    ip: str | None
    hostname: str | None
    rtt_ms: float | None
    responded: bool

    def __post_init__(self) -> None:
        if self.hop_number < 1:
            raise ValueError(f"hop_number debe ser >= 1, fue {self.hop_number}")
        # Invariante: si responded es True, rtt_ms debe ser >= 0
        # (None solo es válido cuando responded=False).
        if self.responded and self.rtt_ms is None:
            raise ValueError(
                f"rtt_ms no puede ser None si responded=True (hop={self.hop_number})"
            )
        if self.rtt_ms is not None and self.rtt_ms < 0.0:
            raise ValueError(f"rtt_ms debe ser >= 0, fue {self.rtt_ms}")


@dataclass(frozen=True)
class TracerouteResult:
    target_provider: str
    hops: list[TracerouteHop]
    culprit_hop_index: int | None

    def __post_init__(self) -> None:
        if not self.target_provider:
            raise ValueError("target_provider no puede ser vacío")
        if not self.hops:
            raise ValueError("hops no puede ser vacío")
        if self.culprit_hop_index is not None and not (
            0 <= self.culprit_hop_index < len(self.hops)
        ):
            raise ValueError(
                f"culprit_hop_index fuera de rango: {self.culprit_hop_index} "
                f"(hops={len(self.hops)})"
            )
