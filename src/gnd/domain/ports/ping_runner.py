"""Puerto PingRunner — ejecuta sondeos de latencia contra un target.

ARCHITECTURE.md §2 (Protocol PingRunner). Implementación real en network/
(subprocess sobre `ping` nativo o icmplib). Implementación fake en
domain/fakes/ para tests sin red (IMPLEMENTATION_PLAN.md Fase 1).

Cualquier implementación (real, fake, grabada de fixture) debe ser
intercambiable sin que el código que la consume note la diferencia
(Liskov, ENGINEERING_PRINCIPLES.md §2.L).
"""

from typing import Protocol, runtime_checkable

from gnd.models.probe_result import ProbeResult


@runtime_checkable
class PingRunner(Protocol):
    """Ejecuta `count` sondeos de ICMP contra `target_ip` y devuelve un ProbeResult.

    El `timestamp` del ProbeResult es el momento del sondeo (el caller no
    debe asumir que es "ahora" — inyectar/reloj controlado en tests, ver
    ENGINEERING_PRINCIPLES.md §4 "sin reloj real").
    """

    def ping(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        timeout_ms: int,
        *,
        family: str = "ipv4",
    ) -> ProbeResult: ...
