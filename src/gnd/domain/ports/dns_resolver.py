"""Puerto DnsResolver — mide el tiempo de resolución DNS (Fase 12a.2).

TECHNICAL_SPEC.md §8 (gap). Implementación real en network/
(`RealDnsResolver` wrap de `socket.getaddrinfo` con timeout). Fake en
domain/fakes/ para tests sin red.

Como todo Protocol de Clean Architecture, cualquier implementación
(real, fake, grabada de fixture) debe ser intercambiable sin que el
código que la consume note la diferencia (Liskov, EP §2.L). El dominio
NO depende de `socket` ni de `subprocess` (Protocolo 1).
"""

from typing import Protocol, runtime_checkable

from gnd.models.dns_measurement import DnsResolution


@runtime_checkable
class DnsResolver(Protocol):
    """Resuelve `hostname` y mide tiempo de resolución en ms.

    `family` es `"ipv4"` o `"ipv6"` (la implementación interna traduce
    a `socket.AF_INET`/`socket.AF_INET6`). `timeout_ms` limita la
    espera; si expira, devuelve `DnsResolution(outcome=TIMEOUT, ...)`.

    EP §1.2: la implementación NUNCA debe lanzar excepciones a la UI.
    Errores de red, NXDOMAIN, timeouts — todo se traduce a un
    `DnsResolution` con outcome apropiado (TIMEOUT/ERROR) y `error`
    descriptivo. El caller orquestador no hace try/except; confía en
    el contrato del Protocol.
    """

    def resolve(
        self,
        hostname: str,
        *,
        family: str = "ipv4",
        timeout_ms: int = 1000,
    ) -> DnsResolution: ...
