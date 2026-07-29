"""Medición de tiempo de resolución DNS por separado (Fase 12a.2).

TECHNICAL_SPEC.md §8 (gap): medir el tiempo de resolución DNS como
métrica independiente del ping (que suele embeber la resolución DNS
en su primer sample si el objetivo es un hostname, no una IP).

`DnsResolution` captura el resultado de pedir a `socket.getaddrinfo`
resolver un hostname dado. El `family` se reporta como string corto
(`"ipv4"` / `"ipv6"`) para evitar imports de `socket` en este módulo
de modelos (Protocolo 1: separación estricta `models/` sin imports de
subprocess/socket/sqlite).
"""

from dataclasses import dataclass
from enum import Enum, auto

__all__ = ["DnsResolution", "DnsOutcome"]


class DnsOutcome(Enum):
    SUCCESS = auto()  # resolución exitosa, elapsed_ms medido
    TIMEOUT = auto()  # getaddrinfo excedió timeout_ms
    ERROR = auto()  # falla distinta de timeout (NXDOMAIN, sin red, etc.)


@dataclass(frozen=True)
class DnsResolution:
    """Una medición de resolución DNS para un hostname.

    Invariante: si outcome == SUCCESS -> resolved_ip no es None y
    elapsed_ms fue medido. Si outcome != SUCCESS -> error no es None
    (string describiendo la causa) y elapsed_ms/ resolved_ip pueden
    ser None (timeout o error antes de resolver).
    """

    hostname: str
    resolved_ip: str | None
    outcome: DnsOutcome
    elapsed_ms: float | None
    family: str  # "ipv4" | "ipv6"
    error: str | None

    def __post_init__(self) -> None:
        if not self.hostname:
            raise ValueError("hostname no puede ser vacío")
        if self.family not in ("ipv4", "ipv6"):
            raise ValueError(f"family debe ser 'ipv4' o 'ipv6', no {self.family!r}")
        if self.outcome == DnsOutcome.SUCCESS and self.resolved_ip is None:
            raise ValueError(
                "resolved_ip no puede ser None cuando outcome=SUCCESS "
                f"(hostname={self.hostname})"
            )
        if self.outcome == DnsOutcome.SUCCESS and self.elapsed_ms is None:
            raise ValueError(
                "elapsed_ms no puede ser None cuando outcome=SUCCESS "
                f"(hostname={self.hostname})"
            )
        if self.outcome != DnsOutcome.SUCCESS and self.error is None:
            raise ValueError(
                f"error no puede ser None cuando outcome={self.outcome.name}"
            )
