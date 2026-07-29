"""Una corrida completa de diagnóstico.

TECHNICAL_SPEC.md §1: agrega todos los probes, traceroutes, el servidor de
partida activo (si lo hubo) y la recomendación final.

Fase 12a.2: agrega `dns_results` (mediciones de tiempo de resolución DNS,
opcional — vacío si la feature está deshabilitada o el resolver falló para
todos los hosts). El campo tiene default `()` para mantener backwards-
compatibilidad con callers existentes que no lo pasan (Protocolo 5:
frozen=True no se rompe añadiendo campos con default).
"""

from dataclasses import dataclass, field
from datetime import datetime

from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.dns_measurement import DnsResolution
from gnd.models.network_interface import NetworkInterfaceSnapshot
from gnd.models.probe_result import ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteResult


@dataclass(frozen=True)
class DiagnosticRun:
    run_id: str
    started_at: datetime
    finished_at: datetime
    probes: list[ProbeResult]
    traceroutes: list[TracerouteResult]
    active_game_server: ActiveGameServerInfo | None
    recommendation: Recommendation
    # Fase 12a.2: mediciones de resolución DNS (vacio si feature off).
    # tuple para inmutabilidad total (Protocolo 5: frozen completo).
    dns_results: tuple[DnsResolution, ...] = field(default_factory=tuple)
    # Fase 12a.3: snapshot de la interfaz de red activa (None si feature off
    # o si el inspector fallo y se devolvio sin snapshot — aunque el contrato
    # del inspector nunca devuelve None). Default None para backwards-compat.
    interface_snapshot: NetworkInterfaceSnapshot | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id no puede ser vacío")
        if self.finished_at < self.started_at:
            raise ValueError(
                "finished_at no puede ser anterior a started_at "
                f"(start={self.started_at} finish={self.finished_at})"
            )
