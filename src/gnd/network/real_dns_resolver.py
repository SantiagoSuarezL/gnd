"""Adaptador real de DnsResolver vía subprocess thread + socket.getaddrinfo.

Fase 12a.2. Tech_stack.md / Protocolo 1: este módulo es Infrastructure
(network/) — puede importar `socket`. El Protocol correspondiente
(domain/ports/dns_resolver.py) NO lo importa.

Decisiones de implementación:

1. `socket.getaddrinfo` NO acepta timeout directo. Para respetar el
   parámetro `timeout_ms` del Protocol, se invoca dentro de un
   `concurrent.futures.ThreadPoolExecutor` con `future.result(timeout=)`.
   Si el getaddrinfo (call bloqueante en C resolver DNS del OS) cuelga,
   el `TimeoutExpired` del future se captura y traduce a un
   `DnsResolution(outcome=TIMEOUT, ...)`.

2. El thread funciona como Daemonic — el future no se cancela (thread
   sigue su curso hasta que el OS resolver responda o timeout del propio
   getaddrinfo), pero el caller no espera el future cancelado. En
   v1 (single-run, sesiones cortas) esto es aceptable: el thread
   zombie se une al proceso al morir (daemon).

3. EP §1.2: cualquier excepción del getaddrinfo (NXDOMAIN, gaierror,
   OSError) se captura y traduce a `DnsResolution(outcome=ERROR,
   error=str(exc))` — nunca propaga al caller orquestador.

4. La medición de elapsed_ms usa `time.perf_counter` (monótono, alta
   resolución — EP §4: sin reloj real en tests, en runtime es el
   apropiado para mediciones de latencia).
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from gnd.models.dns_measurement import DnsOutcome, DnsResolution

# Familia minúscula -> socket.AF_*
_FAMILY_TO_SOCK = {
    "ipv4": socket.AF_INET,
    "ipv6": socket.AF_INET6,
}


class RealDnsResolver:
    """Implementación real de DnsResolver con socket.getaddrinfo + timeout.

    Threading-safe: el ThreadPoolExecutor se crea por call. El socket
    de por sí no es thread-safe, pero acá solo se usa getaddrinfo (que
    sí lo es — seed OS DNS resolver).
    """

    def resolve(
        self,
        hostname: str,
        *,
        family: str = "ipv4",
        timeout_ms: int = 1000,
    ) -> DnsResolution:
        family_sock = _FAMILY_TO_SOCK.get(family)
        if family_sock is None:
            # No debería ocurrir: el caller valida family@modelos. Pero
            # belt-and-suspenders: traducción interna segura.
            return DnsResolution(
                hostname=hostname,
                resolved_ip=None,
                outcome=DnsOutcome.ERROR,
                elapsed_ms=None,
                family=family,
                error=f"family no soportada: {family!r}",
            )

        started = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    socket.getaddrinfo,
                    hostname,
                    None,
                    family_sock,
                    socket.SOCK_STREAM,
                )
                try:
                    res = future.result(timeout=timeout_ms / 1000.0)
                except FutureTimeout:
                    elapsed = (time.perf_counter() - started) * 1000.0
                    return DnsResolution(
                        hostname=hostname,
                        resolved_ip=None,
                        outcome=DnsOutcome.TIMEOUT,
                        elapsed_ms=round(elapsed, 2),
                        family=family,
                        error=(
                            f"getaddrinfo timeout tras "
                            f"{timeout_ms}ms para {hostname}"
                        ),
                    )
        except OSError as exc:
            elapsed = (time.perf_counter() - started) * 1000.0
            return DnsResolution(
                hostname=hostname,
                resolved_ip=None,
                outcome=DnsOutcome.ERROR,
                elapsed_ms=round(elapsed, 2),
                family=family,
                error=f"getaddrinfo OSError para {hostname}: {exc!r}",
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        # res es lista de (family, type, proto, canonname, sockaddr).
        # sockaddr ya es (ip, port,...) del family seleccionado.
        # Tomar la primera sockaddr válida como resolved_ip.
        try:
            resolved_ip = res[0][4][0]
        except (IndexError, TypeError) as exc:
            return DnsResolution(
                hostname=hostname,
                resolved_ip=None,
                outcome=DnsOutcome.ERROR,
                elapsed_ms=round(elapsed, 2),
                family=family,
                error=f"respuesta getaddrinfo sin sockaddr para {hostname}: {exc!r}",
            )

        return DnsResolution(
            hostname=hostname,
            resolved_ip=resolved_ip,
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=round(elapsed, 2),
            family=family,
            error=None,
        )
