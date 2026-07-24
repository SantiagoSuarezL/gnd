"""Información del servidor de partido activo detectado.

TECHNICAL_SPEC.md §1 y §2.2. La detección ocurre vía enumeración de
conexiones UDP del proceso del juego (process_connection_scan) o confirmada
cruzada con la Live Client Data API (live_client_api_confirmed).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveGameServerInfo:
    ip: str
    port: int
    protocol: str  # "udp" | "tcp"
    detected_via: str  # "process_connection_scan" | "live_client_api_confirmed"
    process_name: str

    def __post_init__(self) -> None:
        if not self.ip:
            raise ValueError("ip no puede ser vacío")
        if not self.process_name:
            raise ValueError("process_name no puede ser vacío")
        if self.protocol not in ("udp", "tcp"):
            raise ValueError(f"protocol debe ser 'udp' o 'tcp', fue {self.protocol!r}")
        if self.detected_via not in (
            "process_connection_scan",
            "live_client_api_confirmed",
        ):
            raise ValueError(f"detected_via inválido: {self.detected_via!r}")
        if not (1 <= self.port <= 65535):
            raise ValueError(f"port debe estar en [1, 65535], fue {self.port}")
