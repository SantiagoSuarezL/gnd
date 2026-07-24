"""Demo del DoD de Fase 2: fallback TCP SYN funcionando de verdad.

Este script NO es un test: es evidencia reproducible de que el fallback
TCP SYN funciona sobre red real (no solo en fixtures in-memory). Combina:

- ICMP fabricado como "100% timeout" (inyectado por un ProcessRunner stub)
  para forzar el camino del fallback sin depender de encontrar un host
  que bloquee ICMP en el entorno de corrida.
- TCP SYN REAL contra hosts con 443 conocido vivo (1.1.1.1, 8.8.8.8, 9.9.9.9)
  y contra un host no-rutable (TEST-NET-3 203.0.113.42) que debe fallar.

Resultado esperado:
- Hosts con TCP 443 vivo -> outcome FILTERED (host vivo, ICMP bloqueado).
- Host no rutable -> outcome TIMEOUT o UNREACHABLE (TCP tambien cae).

Uso:
    python src/gnd/network/demo_fallback_evidence.py
"""

from gnd.network.real_ping_runner import RealPingRunner


class _AllTimeoutProcess:
    """ProcessRunner que simula output de `ping` con 100% packet loss.

    Fuerza el camino del fallback TCP SYN en RealPingRunner sin necesidad
    de encontrar un host real que bloquee ICMP en este entorno.
    """

    def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]:
        # Formato Windows "Request timed out" puro, sin error_letter.
        stdout = (
            "Pinging x with 32 bytes of data:\n"
            "Request timed out.\n"
            "Request timed out.\n"
            "Ping statistics for x:\n"
            "    Packets: Sent = 2, Received = 0, Lost = 2 (100% loss),\n"
        )
        return (stdout, "", 1)


def main() -> None:
    runner = RealPingRunner(
        fallback_port=443,
        tcp_syn_timeout_s=2.0,
        process_runner=_AllTimeoutProcess(),
    )

    print("=" * 70)
    print("Demo: fallback TCP SYN forzando ICMP 100% timeout")
    print("Si el host responde TCP 443 -> FILTERED (vivo, bloquea ICMP).")
    print("Si no responde TCP -> TIMEOUT/UNREACHABLE (host caido).")
    print("=" * 70)

    cases = [
        (
            "1.1.1.1",
            "cloudflare",
            "cloudflare",
            "TCP 443 vivo, ICMP falsamente bloqueado",
        ),
        ("8.8.8.8", "google_dns", "google", "TCP 443 vivo"),
        ("9.9.9.9", "quad9", "quad9", "TCP 443 vivo"),
        ("203.0.113.42", "test_net", "local", "TEST-NET-3 no rutable: TCP debe fallar"),
    ]

    for ip, name, provider, desc in cases:
        print(f"\n--- {ip} ({name}) — {desc} ---")
        r = runner.ping(ip, name, provider, count=2, timeout_ms=1000)
        print(f"  outcome = {r.outcome.name}")
        print(f"  stats   = {r.stats}")
        expected = "FILTERED" if "vivo" in desc else ("TIMEOUT", "UNREACHABLE")
        print(f"  esperado = {expected}")
        ok = (
            r.outcome.name == "FILTERED"
            if "vivo" in desc
            else r.outcome.name in ("TIMEOUT", "UNREACHABLE")
        )
        print(f"  OK      = {ok}")

    print("\n" + "=" * 70)
    print("Si los hosts con 'TCP 443 vivo' dan FILTERED y el no-rutable da")
    print("TIMEOUT/UNREACHABLE, el fallback TCP SYN funciona sobre red real.")
    print("=" * 70)


if __name__ == "__main__":
    main()
