"""Fakes in-memory de todos los Protocol del dominio.

IMPLEMENTATION_PLAN.md Fase 1: implementaciones fake/in-memory de cada
Protocol (PingRunner, TracerouteRunner, ConnectionInspector,
DiagnosticsRepository) para testear capas superiores sin tocar red ni
disco real (ENGINEERING_PRINCIPLES.md §4).
"""

from gnd.domain.fakes.fake_connection_inspector import FakeConnectionInspector
from gnd.domain.fakes.fake_diagnostics_repository import FakeDiagnosticsRepository
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_traceroute_runner import FakeTracerouteRunner

__all__ = [
    "FakeConnectionInspector",
    "FakeDiagnosticsRepository",
    "FakePingRunner",
    "FakeTracerouteRunner",
]
