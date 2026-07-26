"""Fakes in-memory de todos los Protocol del dominio.

IMPLEMENTATION_PLAN.md Fase 1: implementaciones fake/in-memory de cada
Protocol (PingRunner, TracerouteRunner, ConnectionInspector,
DiagnosticsRepository) para testear capas superiores sin tocar red ni
disco real (ENGINEERING_PRINCIPLES.md §4).

Fase 8: se añaden FakeRouteMonitor + FakeMonitoringRepository para
testear el orquestador de monitoreo y la persistencia sin red/disco.
Fase 9: se añade FakeDatabaseConnectionFactory para tests que quieran
envolver una conn SQLite existente sin tocar SqliteConnectionFactory.
"""

from gnd.domain.fakes.fake_connection_inspector import FakeConnectionInspector
from gnd.domain.fakes.fake_database_connection_factory import (
    FakeDatabaseConnectionFactory,
)
from gnd.domain.fakes.fake_diagnostics_repository import FakeDiagnosticsRepository
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_route_monitor import (
    FakeMonitoringRepository,
    FakeRouteMonitor,
)
from gnd.domain.fakes.fake_traceroute_runner import FakeTracerouteRunner

__all__ = [
    "FakeConnectionInspector",
    "FakeDatabaseConnectionFactory",
    "FakeDiagnosticsRepository",
    "FakeMonitoringRepository",
    "FakePingRunner",
    "FakeRouteMonitor",
    "FakeTracerouteRunner",
]
