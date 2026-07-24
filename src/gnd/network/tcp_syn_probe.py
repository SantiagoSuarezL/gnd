"""Fallback TCP SYN para diferenciar FILTERED de UNREACHABLE.

TECHNICAL_SPEC.md §2.1 y §7: si ICMP falla (100% packet loss) se prueba un
TCP connect a un puerto conocido (default 443). Si el TCP handshake responde
(SYN-ACK o incluso RST), el host esta vivo y solo bloquea ICMP -> FILTERED.
Si TCP tambien falla por timeout -> TIMEOUT; si la red reporta unreachable
inmediato -> UNREACHABLE.

Implementacion: usa `socket.create_connection` con timeout corto. No hace
TLS handshake, solo el connect TCP ( SYN / SYN-ACK / ACK ).

Este modulo es infraestructura pura; devuelve un `TcpSynOutcome` que
RealPingRunner consume.
"""

import socket
from dataclasses import dataclass
from enum import Enum, auto


class TcpSynResult(Enum):
    """Resultado del fallback TCP SYN.

    OPEN: el connect completo -> host vivo.
    REJECTED: el host respondio RST (connect refused) -> host vivo bloqueando
        el puerto, pero sigue FILTERED pues el stack TCP responde.
    TIMEOUT: el connect expiro sin respuesta -> host probablemente caido o
        la red no lleva el paquete -> TIMEOUT (no es distinguible de
        UNREACHABLE sin mas senal, pero TECHNICAL_SPEC lo trata como
        no-FILTERED).
    NETWORK_UNREACHABLE: el SO reporto que no hay ruta -> UNREACHABLE.
    """

    OPEN = auto()
    REJECTED = auto()
    TIMEOUT = auto()
    NETWORK_UNREACHABLE = auto()


@dataclass(frozen=True)
class TcpSynOutcome:
    result: TcpSynResult
    detail: str


def probe(
    target_ip: str,
    port: int = 443,
    timeout_s: float = 1.0,
) -> TcpSynOutcome:
    """Ejecuta un TCP connect (SYN) contra (target_ip, port) con timeout.

    No lanza excepciones hacia el caller: toda condicion de red se devuelve
    como TcpSynOutcome (principio EP §1.2). `timeout_s` es el timeout
    maximo del connect.
    """
    try:
        with socket.create_connection((target_ip, port), timeout=timeout_s):
            return TcpSynOutcome(TcpSynResult.OPEN, "tcp connect ok")
    except ConnectionRefusedError:
        # RST recibido: el host responde a TCP pero rechaza el puerto.
        # El stack TCP del host esta vivo -> FILTERED en terminos de ping.
        return TcpSynOutcome(TcpSynResult.REJECTED, "connection refused (RST)")
    except TimeoutError:
        return TcpSynOutcome(TcpSynResult.TIMEOUT, "tcp connect timeout")
    except OSError as exc:
        # Incluye Network unreachable, No route to host, etc.
        return TcpSynOutcome(TcpSynResult.NETWORK_UNREACHABLE, str(exc))


def is_host_alive(outcome: TcpSynOutcome) -> bool:
    """True si el host esta vivo (OPEN o REJECTED), False si no responde nada.

    Tecnico: OPEN = SYN-ACK, REJECTED = RST. Ambos prueban que el host
    tiene stack TCP funcionando y recibe paquetes. UNREACHABLE/TIMEOUT no
    prueban nada (no distinguible de host caido).
    """
    return outcome.result in (TcpSynResult.OPEN, TcpSynResult.REJECTED)
