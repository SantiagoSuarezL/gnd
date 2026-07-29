"""Puerto TracerouteRunner — ejecuta traceroute hacia un target.

ARCHITECTURE.md §2 (Protocol TracerouteRunner). Implementación real en
network/ (wrapper sobre `tracert` nativo de Windows vía subprocess).
Implementación fake en domain/fakes/ para tests sin red.
"""

from typing import Protocol, runtime_checkable

from gnd.models.traceroute import TracerouteResult


@runtime_checkable
class TracerouteRunner(Protocol):
    """Ejecuta un traceroute hacia `target_ip` con `max_hops` y `timeout_ms`.

    Devuelve un TracerouteResult con la lista de hops y, si se detecta,
    culprit_hop_index ya calculado (TECHNICAL_SPEC.md §2.3).
    """

    def traceroute(
        self,
        target_ip: str,
        target_provider: str,
        max_hops: int,
        timeout_ms: int,
        *,
        family: str = "ipv4",
    ) -> TracerouteResult: ...
