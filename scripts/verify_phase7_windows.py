"""Verificacion end-to-end de Fase 7 para correr en Windows real.

Corre el pipeline de traceroute contra tu red local:
  1. Loopback (debe ser SUCCESS, 1 hop)
  2. Gateway local inferido (tracert con 1-2 hops)
  3. Google DNS, Cloudflare, Quad9 (alguno debe tener tracert completo)
  4. Riot public (auth.riotgames.com -> Cloudflare)
  5. Host no rutable (TEST-NET-3) -> timeout/UNREACHABLE, no crash
  6. DoD: tracert con salto de latencia sostenido -> identifica culprit_hop_index

No toca psutil, sqlite, ni capas superiores. Solo network/.

Ejecutar desde la raiz del repo con el venv activado:

    (Windows, PowerShell)
    .\\.venv\\Scripts\\python.exe scripts\\verify_phase7_windows.py

Pegar la salida completa a Opencode para confirmar el DoD de Fase 7.
"""

from __future__ import annotations

import platform
import sys

from gnd.network.real_traceroute_runner import RealTracerouteRunner

SEP = "=" * 72


def banner(t: str) -> None:
    print(f"\n{SEP}\n{t}\n{SEP}")


def main() -> None:
    banner("GND — Fase 7: verificacion end-to-end Traceroute sobre red Windows real")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"Plataforma    : {platform.system()} {platform.release()}")
    if platform.system() == "Windows":
        binario = "tracert.exe (Windows)"
    else:
        binario = "traceroute (POSIX)"
    print(f"Binario tracert: {binario}")

    runner = RealTracerouteRunner()

    banner("1) LOCAL — loopback (debe ser SUCCESS, 1 hop)")
    r = runner.traceroute("127.0.0.1", "local", 10, 1000)
    print(f"  hops={len(r.hops)}  culprit={r.culprit_hop_index}")
    for h in r.hops:
        rtt = f"{h.rtt_ms:.1f}ms" if h.rtt_ms is not None else "N/A"
        ip = h.ip if h.ip else "N/A"
        print(f"    hop {h.hop_number:2d} ip={ip:15s} rtt={rtt:>8s} resp={h.responded}")

    banner("2) LOCAL — gateway (tracert hasta 3 hops)")
    # Inferir gateway: hacer tracert a 8.8.8.8 y tomar el primer hop
    r = runner.traceroute("8.8.8.8", "google", 3, 1000)
    if len(r.hops) >= 1:
        gw = r.hops[0].ip
        print(f"  Gateway inferido: {gw}")
        if gw:
            r2 = runner.traceroute(gw, "local", 3, 1000)
            print(f"  hops={len(r2.hops)}  culprit={r2.culprit_hop_index}")

    banner("3) INTERNET — Google, Cloudflare, Quad9")
    for ip, prov in [
        ("8.8.8.8", "google"),
        ("1.1.1.1", "cloudflare"),
        ("9.9.9.9", "quad9"),
    ]:
        r = runner.traceroute(ip, prov, 15, 1500)
        culprit = r.culprit_hop_index if r.culprit_hop_index is not None else "None"
        print(f"  {prov:12s} {ip} -> hops={len(r.hops):2d}  culprit={culprit}")
        # Mostrar hops con RTT
        for h in r.hops:
            if h.responded:
                rtt = f"{h.rtt_ms:.1f}ms"
                print(f"    hop {h.hop_number:2d}  {h.ip:15s}  {rtt:>8s}")
            else:
                print(f"    hop {h.hop_number:2d}  * * *  (no respondio)")

    banner("4) RIOT PUBLIC — auth.riotgames.com (resuelve Cloudflare)")
    r = runner.traceroute("auth.riotgames.com", "riot_public", 15, 1500)
    last_ip = r.hops[-1].ip if r.hops else "N/A"
    print(f"  target_ip={last_ip}  hops={len(r.hops)}  culprit={r.culprit_hop_index}")
    for h in r.hops:
        if h.responded:
            rtt = f"{h.rtt_ms:.1f}ms"
            print(f"    hop {h.hop_number:2d}  {h.ip:15s}  {rtt:>8s}")
        else:
            print(f"    hop {h.hop_number:2d}  * * *  (no respondio)")

    banner("5) HOST NO RUTABLE — TEST-NET-3 203.0.113.42")
    r = runner.traceroute("203.0.113.42", "test_net", 8, 1500)
    print(f"  hops={len(r.hops)}  culprit={r.culprit_hop_index}")
    for h in r.hops:
        if h.responded:
            rtt = f"{h.rtt_ms:.1f}ms"
            print(f"    hop {h.hop_number:2d}  {h.ip:15s}  {rtt:>8s}")
        else:
            print(f"    hop {h.hop_number:2d}  * * *  (no respondio)")

    banner("6) DoD — salto de latencia sostenido (ej. 8.8.8.8 con max_hops alto)")
    r = runner.traceroute("8.8.8.8", "google", 30, 1500)
    print(f"  hops={len(r.hops)}  culprit_hop_index={r.culprit_hop_index}")
    if r.culprit_hop_index is not None:
        c = r.hops[r.culprit_hop_index]
        print(f"  >>> CULPABLE: hop {c.hop_number}  ip={c.ip}  rtt={c.rtt_ms:.1f}ms")
        # Mostrar contexto alrededor
        start = max(0, r.culprit_hop_index - 2)
        end = min(len(r.hops), r.culprit_hop_index + 3)
        for i in range(start, end):
            h = r.hops[i]
            mark = " >>>" if i == r.culprit_hop_index else ""
            if h.responded:
                print(f"    hop {h.hop_number:2d}  {h.ip:15s}  {h.rtt_ms:.1f}ms{mark}")
            else:
                print(f"    hop {h.hop_number:2d}  * * *{mark}")
    else:
        print("  (no se detecto salto anomalo sostenido en esta ruta)")

    banner("7) DIAGNOSTICO COMPLETO — sin crashear")
    runner2 = RealTracerouteRunner()
    targets = [
        ("127.0.0.1", "local"),
        ("8.8.8.8", "google"),
        ("1.1.1.1", "cloudflare"),
        ("9.9.9.9", "quad9"),
        ("auth.riotgames.com", "riot_public"),
        ("203.0.113.42", "test_net"),
    ]
    results = []
    for ip, prov in targets:
        results.append(runner2.traceroute(ip, prov, 10, 1500))
    print(f"  Se ejecutaron {len(results)} traceroutes sin excepcion:")
    for r in results:
        culprit = r.culprit_hop_index if r.culprit_hop_index is not None else "None"
        last_ip = r.hops[-1].ip if r.hops and r.hops[-1].ip else "N/A"
        print(
            f"    {r.target_provider:12s} {last_ip:16s}"
            f" -> hops={len(r.hops):2d} culprit={culprit}"
        )

    banner("FIN — si todo OK, pegale esta salida a Opencode")
    print(
        "DoD Fase 7: parser + runner + culprit_hop_index "
        "funciona end-to-end en red real."
    )


if __name__ == "__main__":
    main()
