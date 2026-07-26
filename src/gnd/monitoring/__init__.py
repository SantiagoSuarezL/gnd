"""Capa de orquestacion de monitoreo de ruta (Fase 8).

TECHNICAL_SPEC.md §2.4 + IMPLEMENTATION_PLAN.md Fase 8.

Implementa ``Protocol RouteMonitor`` del dominio (EP §1.1: dominio no
importa infraestructura; el orquestador SÍ es infraestructura porque
depende de ``TracerouteRunner``, un adapter).

Submodulos:
- ``aggregator``: logica pura de agregacion de muestras en HopStats.
  Testeable sin red, sin reloj, sin subprocess (EP §4).
- ``route_monitor``: orquestador real; inyecta ``TracerouteRunner`` +
  ``Sleeper`` + ``Clock`` para tests sin I/O de OS.
"""

from gnd.monitoring.aggregator import aggregate_hops, fill_ip_hostname_mode
from gnd.monitoring.route_monitor import RouteMonitor

__all__ = [
    "RouteMonitor",
    "aggregate_hops",
    "fill_ip_hostname_mode",
]
