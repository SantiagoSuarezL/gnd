"""Resultado de un sondeo individual contra un target.

TECHNICAL_SPEC.md §1: `stats` es None cuando outcome != SUCCESS.
provider es la clave estable para histórico: "local" | "google" |
"cloudflare" | "quad9" | "riot_public" | "riot_game_server".
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from gnd.models.latency_stats import LatencyStats


class ProbeOutcomeKind(Enum):
    SUCCESS = auto()
    FILTERED = auto()  # ICMP bloqueado u host que ignora ping deliberadamente
    UNREACHABLE = auto()  # error de red real (no ruta, RST, etc.)
    TIMEOUT = auto()


@dataclass(frozen=True)
class ProbeResult:
    target_name: str
    target_ip: str
    provider: str
    outcome: ProbeOutcomeKind
    stats: LatencyStats | None
    timestamp: datetime

    def __post_init__(self) -> None:
        # Invariante: stats solo está presente si outcome == SUCCESS
        # (TECHNICAL_SPEC.md §1: stats es None si outcome != SUCCESS).
        if self.outcome != ProbeOutcomeKind.SUCCESS and self.stats is not None:
            raise ValueError(
                f"stats debe ser None cuando outcome={self.outcome.name} (!= SUCCESS)"
            )
        if self.outcome == ProbeOutcomeKind.SUCCESS and self.stats is None:
            raise ValueError(
                "stats no puede ser None cuando outcome=SUCCESS "
                f"(target={self.target_name})"
            )
        if not self.target_name:
            raise ValueError("target_name no puede ser vacío")
        if not self.target_ip:
            raise ValueError("target_ip no puede ser vacío")
        if not self.provider:
            raise ValueError("provider no puede ser vacío")
