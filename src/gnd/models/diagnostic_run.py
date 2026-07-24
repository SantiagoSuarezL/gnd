"""Una corrida completa de diagnóstico.

TECHNICAL_SPEC.md §1: agrega todos los probes, traceroutes, el servidor de
partida activo (si lo hubo) y la recomendación final.
"""

from dataclasses import dataclass
from datetime import datetime

from gnd.models.active_game_server import ActiveGameServerInfo
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

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id no puede ser vacío")
        if self.finished_at < self.started_at:
            raise ValueError(
                "finished_at no puede ser anterior a started_at "
                f"(start={self.started_at} finish={self.finished_at})"
            )
