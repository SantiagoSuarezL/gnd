"""Entidades y value objects del dominio de GND.

Contratos de datos definidos en TECHNICAL_SPEC.md §1. Ningún modelo aquí
importa infraestructura (psutil, sqlite3, subprocess) — ver
ENGINEERING_PRINCIPLES.md §1.1. Todos son inmutables (frozen=True) salvo
justificación explícita (EP §1.6).
"""

from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult

__all__ = [
    "ActiveGameServerInfo",
    "DiagnosticRun",
    "HistoricalBaseline",
    "LatencyStats",
    "ProbeOutcomeKind",
    "ProbeResult",
    "Recommendation",
    "TracerouteHop",
    "TracerouteResult",
]
