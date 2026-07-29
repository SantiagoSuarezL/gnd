"""Fakes in-memory de todos los Protocol del dominio.

IMPLEMENTATION_PLAN.md Fase 1: implementaciones fake/in-memory de cada
Protocol (PingRunner, TracerouteRunner, ConnectionInspector,
DiagnosticsRepository) para testear capas superiores sin tocar red ni
disco real (ENGINEERING_PRINCIPLES.md §4).

Fase 8: se añaden FakeRouteMonitor + FakeMonitoringRepository para
testear el orquestador de monitoreo y la persistencia sin red/disco.
Fase 9: se añade FakeDatabaseConnectionFactory para tests que quieran
envolver una conn SQLite existente sin tocar SqliteConnectionFactory.
Fase 10: se añade FakeSeriesDataSource para tests de la pestaña Charts
sin tocar DB ni matplotlib backend interactivo.
Fase 12a.2: se añade FakeDnsResolver para testear la etapa DNS del
RunFullDiagnostics sin red real (sin tocar socket.getaddrinfo).
Fase 12a.3: se añade FakeNetworkInterfaceInspector para testear la etapa
de snapshot de interfaz sin invocar netsh/psutil.
"""

from gnd.domain.fakes.fake_connection_inspector import FakeConnectionInspector
from gnd.domain.fakes.fake_database_connection_factory import (
    FakeDatabaseConnectionFactory,
)
from gnd.domain.fakes.fake_diagnostics_repository import FakeDiagnosticsRepository
from gnd.domain.fakes.fake_dns_resolver import FakeDnsResolver
from gnd.domain.fakes.fake_network_interface_inspector import (
    FakeNetworkInterfaceInspector,
)
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_route_monitor import (
    FakeMonitoringRepository,
    FakeRouteMonitor,
)
from gnd.domain.fakes.fake_series_data_source import FakeSeriesDataSource
from gnd.domain.fakes.fake_traceroute_runner import FakeTracerouteRunner

__all__ = [
    "FakeConnectionInspector",
    "FakeDatabaseConnectionFactory",
    "FakeDiagnosticsRepository",
    "FakeDnsResolver",
    "FakeMonitoringRepository",
    "FakeNetworkInterfaceInspector",
    "FakePingRunner",
    "FakeRouteMonitor",
    "FakeSeriesDataSource",
    "FakeTracerouteRunner",
]
