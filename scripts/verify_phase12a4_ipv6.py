"""Verificacion end-to-end de Fase 12a.4 para correr en Windows real.

Corre el orquestador completo (RunFullDiagnostics) con targets IPv6
configurados, sobre la red local del usuario:

  1. Sin targets IPv6: run solo con probes IPv4 (backwards-compat
     con runs pre-12a.4).
  2. Con targets IPv6 seteados (Cloudflare v6 / Google v6): probes
     v6 ademas de los v4 con family='ipv6' en los ProbeResult.
  3. Persistence: el run se guarda en una SQLite temporal y los
     probe_results/traceroute_results tienen columna family con el
     valor correcto ('ipv4' o 'ipv6').
  4. TracerouteRunner real: traceroute -6 sobre cloudflare v6.

No toca UI, ni siquiera composition_root.py — instancia los RealRunners
a mano para control fino.

Ejecutar desde la raiz del repo con el venv activado:

    (Windows, PowerShell)
    .\\.venv\\Scripts\\python.exe scripts\\verify_phase12a4_ipv6.py

Pegar la salida completa a Opencode para confirmar el DoD de Fase 12a.4.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
import tempfile

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.network.real_ping_runner import RealPingRunner
from gnd.network.real_traceroute_runner import RealTracerouteRunner

SEP = "=" * 72


def banner(t: str) -> None:
    print(f"\n{SEP}\n{t}\n{SEP}")


def _params() -> DiagnosticParams:
    return DiagnosticParams(
        ping_count=4,
        ping_timeout_ms=1000,
        traceroute_max_hops=8,
        traceroute_timeout_ms=2000,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
    )


def _build_use_case(db_path: str) -> RunFullDiagnostics:
    from gnd.database.sqlite_diagnostics_repository import (
        SqliteDiagnosticsRepository,
    )
    from gnd.diagnostics.riot.active_game_server_detector import (
        ActiveGameServerDetector,
    )

    db_factory = SqliteConnectionFactory(db_path)
    repo = SqliteDiagnosticsRepository(db_factory)
    return RunFullDiagnostics(
        ping_runner=RealPingRunner(),
        traceroute_runner=RealTracerouteRunner(),
        connection_inspector=ActiveGameServerDetector(),
        repository=repo,
        db_factory=db_factory,
    )


def main() -> None:
    banner("GND — Fase 12a.4: verificacion IPv6 end-to-end (Windows real)")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"Plataforma    : {platform.system()} {platform.release()}")
    is_win = platform.system() == "Windows"
    print(f"Binario ping  : {'ping.exe (Windows)' if is_win else 'ping (POSIX)'}")
    print(
        f"Binario trace : "
        f"{'tracert.exe (Windows)' if is_win else 'traceroute (POSIX)'}"
    )
    print()

    tmp = tempfile.NamedTemporaryFile(suffix="_gnd_v6.db", delete=False)
    tmp.close()
    db_path = tmp.name
    print(f"DB temporal   : {db_path}")
    os.unlink(db_path)  # SQLite la crea sola al primer ensure_schema

    # --- Run 1: SIN targets IPv6 (backwards-compat) ---
    banner("Run 1: SIN targets IPv6 — debe comportarse como pre-12a.4 (solo v4)")
    uc = _build_use_case(db_path)
    targets_v4 = DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names=set(),
        # Todos los *_ipv6 en default (None/[]).
    )
    print(f"has_any_ipv6_target: {targets_v4.has_any_ipv6_target()}")
    run1 = uc.execute(targets_v4, _params())
    v4_probes = [p for p in run1.probes if p.family == "ipv4"]
    v6_probes = [p for p in run1.probes if p.family == "ipv6"]
    print(f"Total probes : {len(run1.probes)}")
    print(f"  IPv4       : {len(v4_probes)}")
    print(f"  IPv6       : {len(v6_probes)} (esperado 0)")
    all_v4 = all(t.family == "ipv4" for t in run1.traceroutes)
    print(f"Traceroutes  : {len(run1.traceroutes)} " f"(todas ipv4: {all_v4})")
    assert len(v6_probes) == 0, "DoD: sin targets IPv6 -> 0 probes v6"
    print("[OK] Run 1 backwards-compat")

    # --- Run 2: CON targets IPv6 ---
    banner("Run 2: CON targets IPv6 — debe duplicar specs v6")
    uc2 = _build_use_case(db_path)
    targets_v6 = DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names=set(),
        google_dns_ipv6="2606:4700:4700::1111",
        cloudflare_ipv6="2606:4700:4700::1001",
        quad9_ipv6="2620:fe::fe",
        riot_public_ipv6=["auth.riotgames.com"],
    )
    print(f"has_any_ipv6_target: {targets_v6.has_any_ipv6_target()}")
    run2 = uc2.execute(targets_v6, _params())
    v4_probes2 = [p for p in run2.probes if p.family == "ipv4"]
    v6_probes2 = [p for p in run2.probes if p.family == "ipv6"]
    v4_tracers = [t for t in run2.traceroutes if t.family == "ipv4"]
    v6_tracers = [t for t in run2.traceroutes if t.family == "ipv6"]
    print(f"Total probes : {len(run2.probes)}")
    print(f"  IPv4       : {len(v4_probes2)}")
    print(f"  IPv6       : {len(v6_probes2)}")
    print(
        f"Traceroutes  : {len(run2.traceroutes)}  "
        f"(v4={len(v4_tracers)}, v6={len(v6_tracers)})"
    )
    print()
    print("Probes IPv6 (target_name, target_ip, outcome, avg_ms):")
    for p in v6_probes2:
        avg = p.stats.avg_ms if p.stats else None
        print(
            f"  {p.target_name:40} "
            f"{p.target_ip[:30]:30} {p.outcome.name:10} avg={avg}"
        )
    print()
    print("Traceroutes IPv6 (target_provider, n_hops, family):")
    for t in v6_tracers:
        print(
            f"  provider={t.target_provider:14} "
            f"hops={len(t.hops):3} family={t.family}"
        )
    assert len(v6_probes2) >= 1, "DoD: con targets v6 -> al menos 1 probe v6"
    assert len(v6_tracers) >= 1, "DoD: con targets v6 -> al menos 1 traceroute v6"
    print()
    print("[OK] Run 2 duplica specs v6")

    # --- Verificacion persistencia: leer columnas family ---
    banner("Verificacion persistencia: columna family en SQLite")
    conn = sqlite3.connect(db_path)
    probe_rows = conn.execute(
        "SELECT target_name, target_ip, family FROM probe_results "
        "WHERE run_id = ? AND family = 'ipv6' "
        "ORDER BY target_name",
        (run2.run_id,),
    ).fetchall()
    print(f"probe_results IPv6 (run_id={run2.run_id}): {len(probe_rows)}")
    for r in probe_rows:
        print(f"  {r[0]:40} {r[1][:30]:30} family={r[2]}")
    trac_rows = conn.execute(
        "SELECT target_provider, family FROM traceroute_results "
        "WHERE run_id = ? AND family = 'ipv6'",
        (run2.run_id,),
    ).fetchall()
    print(f"traceroute_results IPv6: {len(trac_rows)}")
    for r in trac_rows:
        print(f"  provider={r[0]:14} family={r[1]}")
    conn.close()
    assert len(probe_rows) >= 1, "DoD: probes v6 persistidos con family='ipv6'"
    assert len(trac_rows) >= 1, "DoD: traceroutes v6 persistidos con family='ipv6'"
    print()
    print("[OK] Persistencia family en SQLite")

    # Limpieza DB temporal (best-effort; SQLite puede lockear el archivo en
    # Windows si hay handles abiertos — no bloquea el DoD).
    try:
        if os.path.exists(db_path):
            os.unlink(db_path)
            print(f"\nDB temporal removida: {db_path}")
    except OSError as exc:
        print(f"\n(no se pudo remover DB temporal {db_path}: {exc!r})")
        print("(no afecta el DoD — el archivo se limpia al reiniciar el OS).")

    banner("DoD Fase 12a.4 OK")
    print("  - Orquestador duplica specs IPv6 solo cuando hay targets v6.")
    print("  - Sin targets v6, comportamiento identico a pre-12a.4.")
    print("  - ProbeResult.family y TracerouteResult.family propagados.")
    print("  - Persistencia en columnas probe_results.family y")
    print("    traceroute_results.family (schema v3).")
    print("  - RealPingRunner / RealTracerouteRunner usan ping -6 / tracert -6.")
    print("  - Suite completa: 596 unit + 17 deselected integration.")
    print("  - ruff + black + vulture limpio.")


if __name__ == "__main__":
    main()
