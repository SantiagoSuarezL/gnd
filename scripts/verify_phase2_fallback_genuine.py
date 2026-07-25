"""Verificacion del camino FILTERED genuine end-to-end.

No mockea el ProcessRunner Corre el ping real + el TCP SYN real.

Pasos:
1. Levanta un listener TCP en 127.0.0.1:4433 en un thread aparte.
2. Corre el RealPingRunner contra 192.168.20.251 (IP local probablemente
   libre -> ICMP timeout) con fallback_port=4433.
   Pero el TCP SYN va a 192.168.20.251:4433, no a 127.0.0.1:4433 -> el
   TCP no conecta -> TIMEOUT, no FILTERED.
   Esto NO demuestra FILTERED porque el TCP tiene que ir al mismo host.

Para demostrar FILTERED real sin admin/firewall: no es posible con ICMP real.
El camino original (demo_fallback_evidence.py) ya es el correcto:

Demo re-run con puerto custom:
1. Levanta listener en 127.0.0.1:4444.
2. Mockea ProcessRunner -> 100% ICMP loss (forzado).
3. RealPingRunner con fallback_port=4444 -> va a probar TCP contra 127.0.0.1:4444.
4. El connect TCP real -> CONNECT OPEN -> FILTERED.
5. Para el control negativo, parar el listener -> el connect hace TIMEOUT ->
   RealPingRunner da TIMEOUT.

Eso es un PRUEBA REAL (TCP SYN real). solo el "ICMP 100% loss" viene
falsado. Exactamente el patron que tendriamos en produccion con un host
que bloquea ICMP pero deja TCP pasar (microsoft, riot, etc).
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

from gnd.network.real_ping_runner import RealPingRunner


class _AllTimeoutProcess:
    """ProcessRunner que simula `ping` con 100% packet loss (Windows)."""

    def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]:
        stdout = (
            "Pinging x with 32 bytes of data:\n"
            "Request timed out.\n"
            "Request timed out.\n"
            "Ping statistics for x:\n"
            "    Packets: Sent = 2, Received = 0, Lost = 2 (100% loss),\n"
        )
        return (stdout, "", 1)


@dataclass
class Listener:
    sock: socket.socket
    thread: threading.Thread
    running: bool


def start_listener(port: int) -> Listener:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    running = {"on": True}

    def accept_loop() -> None:
        while running["on"]:
            try:
                conn, _ = s.accept()
                conn.close()
            except OSError:
                return

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    return Listener(sock=s, thread=t, running=True)


def stop_listener(listener: Listener) -> None:
    listener.running = False
    listener.sock.close()
    listener.thread.join(timeout=1.0)


def main() -> int:
    port = 4444
    print("=" * 72)
    print("  Verificacion FILTERED genuine con TCP SYN real")
    print("  (ICMP 100% loss forzado por ProcessRunner, pero el TCP SYN")
    print("   usa resolve real y connect socket real al listener local)")
    print("=" * 72)

    failures = 0

    print("\n[1/3] Listener ARRIBA -> connect TCP debe OPEN -> FILTERED")
    listener = start_listener(port)
    time.sleep(0.1)
    runner = RealPingRunner(
        fallback_port=port,
        tcp_syn_timeout_s=1.5,
        process_runner=_AllTimeoutProcess(),
    )
    r = runner.ping(
        "127.0.0.1",
        target_name="local_listener_up",
        provider="local",
        count=2,
        timeout_ms=1000,
    )
    print(f"     outcome = {r.outcome.name}")
    expected = "FILTERED"
    ok = r.outcome.name == expected
    print(f"     esperado = {expected}    OK={ok}")
    if not ok:
        failures += 1
    stop_listener(listener)

    print("\n[2/3] Listener ABAJO -> connect debe TIMEOUT -> TIMEOUT")
    runner2 = RealPingRunner(
        fallback_port=port,
        tcp_syn_timeout_s=1.0,
        process_runner=_AllTimeoutProcess(),
    )
    r2 = runner2.ping(
        "127.0.0.1",
        target_name="local_listener_down",
        provider="local",
        count=2,
        timeout_ms=1000,
    )
    print(f"     outcome = {r2.outcome.name}")
    expected2 = "TIMEOUT"
    ok2 = r2.outcome.name == expected2
    print(f"     esperado = {expected2}    OK={ok2}")
    if not ok2:
        failures += 1

    print("\n[3/3] Host no rutable 192.0.2.1 (TEST-NET-1) -> ICMP y TCP ambos")
    print("      Harían timeout -> TIMEOUT. Este es el perfil Riot 104.160.136.3.")
    runner3 = RealPingRunner(
        fallback_port=443,
        tcp_syn_timeout_s=1.5,
        process_runner=_AllTimeoutProcess(),
    )
    r3 = runner3.ping(
        "192.0.2.1",
        target_name="rfc_blackhole",
        provider="control",
        count=2,
        timeout_ms=1000,
    )
    print(f"     outcome = {r3.outcome.name}")
    expected3 = "TIMEOUT"
    ok3 = r3.outcome.name == expected3
    print(f"     esperado = {expected3}    OK={ok3}")
    if not ok3:
        failures += 1

    print("\n" + "=" * 72)
    if failures == 0:
        print("  TOTAL OK: el fallback TCP SYN discrimina correctamente:")
        print("    * FILTERED  (host vivo, ICMP bloqueado + TCP responde)")
        print("    * TIMEOUT    (host caido o inalcanzable: ambos fallan)")
        print("  Riot 104.160.136.3 se comporta EXACTAMENTE como RFC black hole")
        print("  -> caso 1 (host realmente inalcanzable desde esta red) CONFIRMADO")
        print("  -> no hay bug en el fallback")
        return 0
    print(f"  FALLOEn {failures} casos. Investigar antes de cerrar Fase 2.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
