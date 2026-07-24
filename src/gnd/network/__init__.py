"""Adaptadores de red real — capa de infraestructura (ARCHITECTURE.md §2).

Implementacion concreta de los `Protocol` del dominio sobre subprocesos y
sockets nativos. El dominio no importa nada de aqui (EP §1.1).

- `ping_parser`: parseo de output textual de `ping` (Windows + Linux).
- `tcp_syn_probe`: fallback TCP SYN para distinguir FILTERED de UNREACHABLE.
- `RealPingRunner`: impl concreta de `Protocol PingRunner` (Fase 2).
"""

from gnd.network.real_ping_runner import ProcessRunner, RealPingRunner
from gnd.network.tcp_syn_probe import (
    TcpSynOutcome,
    TcpSynResult,
    is_host_alive,
    probe,
)

__all__ = [
    "ProcessRunner",
    "RealPingRunner",
    "TcpSynOutcome",
    "TcpSynResult",
    "is_host_alive",
    "probe",
]
