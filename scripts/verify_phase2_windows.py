"""Verificacion end-to-end de Fase 2 para correr en Windows real.

Corre el pipeline de Phase 2 contra tu red local:
  1. Local (loopback + gateway inferido)
  2. Internet general: Google, Cloudflare, Quad9
  3. Riot public (suele bloquear ICMP -> esperable FILTERED)
  4. Un host no rutable (TEST-NET-3) -> debe ser TIMEOUT/UNREACHABLE no crash
  5. Fallback TCP SYN en accion: fuerza ICMP timeout y muestra FILTERED para
     hosts con TCP 443 vivo.

No toca psutil, sqlite, ni nada de capas superiores. Solo network/.

Ejecutar desde la raiz del repo con el venv activado:

    (Windows, PowerShell)
    .\\.venv\\Scripts\\python.exe scripts\\verify_phase2_windows.py

Pegarle la salida completa a Opencode para confirmar el DoD de Fase 2.
"""

from __future__ import annotations

import platform
import socket
import sys

from gnd.network.real_ping_runner import RealPingRunner

SEP = "=" * 72


def banner(t: str) -> None:
    print(f"\n{SEP}\n{t}\n{SEP}")


def probe_tcp(ip: str, port: int = 443, t: float = 2.0) -> None:
    try:
        s = socket.create_connection((ip, port), timeout=t)
        s.close()
        print(f"  TCP {ip}:{port} -> OPEN")
    except ConnectionRefusedError:
        print(f"  TCP {ip}:{port} -> REJECTED (RST, host vivo)")
    except TimeoutError:
        print(f"  TCP {ip}:{port} -> TIMEOUT (host caido o filtrado)")
    except OSError as e:
        print(f"  TCP {ip}:{port} -> OSError: {e}")


def main() -> None:
    banner("GND — Fase 2: verificacion end-to-end sobre red Windows real")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"Plataforma    : {platform.system()} {platform.release()}")
    binario = "ping.exe (Windows)" if platform.system() == "Windows" else "ping (POSIX)"
    print(f"Binario ping  : {binario}")

    runner = RealPingRunner(fallback_port=443, tcp_syn_timeout_s=2.0)

    banner("1) LOCAL — loopback (debe ser SUCCESS)")
    r = runner.ping("127.0.0.1", "loopback", "local", 4, 1000)
    print(f"  outcome = {r.outcome.name}")
    print(f"  stats   = {r.stats}")

    banner("2) INTERNET — Google, Cloudflare, Quad9 (alguno debe ser SUCCESS)")
    for ip, name, prov in [
        ("8.8.8.8", "google_dns", "google"),
        ("1.1.1.1", "cloudflare", "cloudflare"),
        ("9.9.9.9", "quad9", "quad9"),
    ]:
        r = runner.ping(ip, name, prov, 4, 1000)
        print(f"  {name:12s} {ip} -> {r.outcome.name}  stats={r.stats}")

    banner(
        "3) RIOT PUBLIC — 104.160.136.3 (IP legacy; desde LATAM suele ser"
        " TIMEOUT real, no FILTERED)"
    )
    r = runner.ping("104.160.136.3", "riot_public", "riot_public", 3, 1000)
    print(f"  outcome = {r.outcome.name}")
    print(f"  stats   = {r.stats}")
    probe_tcp("104.160.136.3", 443)
    print("  (si outcome=FILTERED + TCP REJECTED/OPEN, el fallbackCorrecto)")

    banner(
        "4) HOST NO RUTABLE — TEST-NET-3 203.0.113.42 "
        "(TIMEOUT o UNREACHABLE, no crash)"
    )
    r = runner.ping("203.0.113.42", "test_net", "local", 2, 1000)
    print(f"  outcome = {r.outcome.name}")
    print(f"  stats   = {r.stats}")
    probe_tcp("203.0.113.42", 443)

    banner("5) FALLBACK TCP SYN en accion (ICMP forzado 100% timeout, IPv4 vivo)")

    # Re-usa el runner pero inyecta ICMP "todo timeout" para forzar el fallback
    class _AllTimeout:
        def __call__(self, args, timeout_ms):
            return (
                "Pinging x with 32 bytes of data:\n"
                "Request timed out.\n"
                "Ping statistics for x:\n"
                "    Packets: Sent = 2, Received = 0, Lost = 2 (100% loss),\n",
                "",
                1,
            )

    runner2 = RealPingRunner(
        fallback_port=443, tcp_syn_timeout_s=2.0, process_runner=_AllTimeout()
    )
    for ip, name, prov in [
        ("1.1.1.1", "cloudflare", "cloudflare"),
        ("8.8.8.8", "google_dns", "google"),
        ("203.0.113.42", "test_net", "local"),
    ]:
        r = runner2.ping(ip, name, prov, 2, 1000)
        print(f"  ICMP-blocked {name:12s} {ip} -> {r.outcome.name}")
    print("  (hosts con 443 vivo -> FILTERED; el no-rutable -> TIMEOUT/UNREACHABLE)")

    banner("6) DIAGNOSTICO COMPLETO — sin crashear")
    runner3 = RealPingRunner(fallback_port=443, tcp_syn_timeout_s=2.0)
    results = []
    for ip, name, prov in [
        ("127.0.0.1", "loopback", "local"),
        ("8.8.8.8", "google_dns", "google"),
        ("1.1.1.1", "cloudflare", "cloudflare"),
        ("9.9.9.9", "quad9", "quad9"),
        ("104.160.136.3", "riot_public", "riot_public"),
        ("203.0.113.42", "test_net", "local"),
    ]:
        results.append(runner3.ping(ip, name, prov, 3, 1000))
    print(f"  Se ejecutaron {len(results)} probes sin excepcion:")
    for r in results:
        print(f"    {r.target_name:12s} {r.target_ip:16s} -> {r.outcome.name}")

    banner("FIN — si todo OK, pegale esta salida a Opencode")
    print("DoD Fase 2 (parcial): diagnostico local + internet end-to-end sin crashear.")
    print("Confirmacion final requiere ver FILTERED en Riot/Cloudflare con TCP vivo.")


if __name__ == "__main__":
    main()
