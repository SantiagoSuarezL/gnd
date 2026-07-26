"""Adaptadores de red real \u2014 capa de infraestructura (ARCHITECTURE.md \u00a72).

Implementacion concreta de los `Protocol` del dominio sobre subprocesos y
sockets nativos. El dominio no importa nada de aqui (EP \u00a71.1).

- `ping_parser`: parseo de output textual de `ping` (Windows + Linux).
- `tcp_syn_probe`: fallback TCP SYN para distinguir FILTERED de UNREACHABLE.
- `RealPingRunner`: impl concreta de `Protocol PingRunner` (Fase 2).
- `tracert_parser`: parseo de output textual de `tracert` (Windows, EN + ES).
- `RealTracerouteRunner`: impl concreta de `Protocol TracerouteRunner`
  (Fase 7) con deteccion del `culprit_hop_index`.
- `detect_culprit_hop`: logica pura de deteccion del hop culpable
  (TECHNICAL_SPEC.md \u00a72.3), expuesta para tests sin red ni subprocess.
"""

from gnd.network import tracert_parser
from gnd.network.real_ping_runner import ProcessRunner, RealPingRunner
from gnd.network.real_traceroute_runner import (
    ProcessRunner as TracerouteProcessRunner,
)
from gnd.network.real_traceroute_runner import (
    RealTracerouteRunner,
    detect_culprit_hop,
)
from gnd.network.tcp_syn_probe import (
    TcpSynOutcome,
    TcpSynResult,
    is_host_alive,
    probe,
)

__all__ = [
    "ProcessRunner",
    "RealPingRunner",
    "RealTracerouteRunner",
    "TracerouteProcessRunner",
    "TcpSynOutcome",
    "TcpSynResult",
    "detect_culprit_hop",
    "is_host_alive",
    "probe",
    "tracert_parser",
]
