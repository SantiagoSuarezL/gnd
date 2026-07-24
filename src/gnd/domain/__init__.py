"""Puertos (Protocols) del dominio.

Definidos en ARCHITECTURE.md §2 (capa Domain/core). El dominio no conoce
las implementaciones concretas — las declara como Protocol y la
infraestructura (network/, database/) las implementa (Dependency Inversion,
ENGINEERING_PRINCIPLES.md §2.D).

Ningún archivo aquí importa psutil, sqlite3, subprocess ni sockets (EP §1.1).
"""

from gnd.domain.ports.connection_inspector import ConnectionInspector
from gnd.domain.ports.diagnostics_repository import DiagnosticsRepository
from gnd.domain.ports.ping_runner import PingRunner
from gnd.domain.ports.traceroute_runner import TracerouteRunner

__all__ = [
    "ConnectionInspector",
    "DiagnosticsRepository",
    "PingRunner",
    "TracerouteRunner",
]
