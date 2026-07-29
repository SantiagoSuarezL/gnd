"""Resultado de un sondeo individual contra un target.

TECHNICAL_SPEC.md §1: `stats` es None cuando outcome != SUCCESS.
provider es la clave estable para histórico: "local" | "google" |
"cloudflare" | "quad9" | "riot_public" | "riot_game_server".

Fase 12a.4: `family` distingue ipv4 (default) de ipv6 (cuando el ISP
asigna IPv6 y el usuario opt-in). Para la DB histórica, family es
columna nueva con default 'ipv4' (Schema v2 retro-compat: probes
existentes siguen siendo ipv4 por default). La CV de old runs queda
intacta (Protocolo 19).
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
    # Fase 12a.4: familia IP del sondeo. Default 'ipv4' backwards-compat.
    # String corto en vez de Enum para no disparar Regla 1.1 (imports
    # circulares con dataclass same file). Invariante: 'ipv4' | 'ipv6'.
    family: str = "ipv4"

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
        if self.family not in ("ipv4", "ipv6"):
            raise ValueError(f"family debe ser 'ipv4' o 'ipv6', no {self.family!r}")
