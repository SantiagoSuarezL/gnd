"""Verificacion end-to-end de Fase 8 para correr en Windows real.

DoD Fase 8 (IMPLEMENTATION_PLAN.md): "una sesion de 60 segundos de
monitoreo produce estadisticas agregadas por hop (avg/worst/best/loss/
jitter) coherentes con las muestras individuales."

Este script ejecuta 3 escenarios:

1) **Sesion corta de 15s con 1.1.1.1** — intervalo 5s, 3 tomas. DoD en
   escala controlada que termina pronto.
2) **Sesion de 60s con 1.1.1.1** — intervalo 5s, 12 tomas. DoD textual
   explícito (60s) con tiempo real.
3) **Coherencia agregado vs muestras individuales** — despues de cada
   sesion, recomputa manualmente best/worst/avg/jitter/loss a partir de
   las ``MonitoringSample`` y compara con los ``HopStats`` que devuelve
   el monitor. Si algun HopStats no matchea -> bug.

Adicional: persiste la sesion en un SQLite en memoria y la recupera,
para verificar que el repositorio round-trip no distorsiona los stats.

No toca psutil ni red Riot. Solo network.real_traceroute_runner +
monitoring + database.sqlite_monitoring_repository.

Ejecutar desde la raiz del repo con el venv activado:

    (Windows, PowerShell)
    .\\.venv\\Scripts\\python.exe scripts\\verify_phase8_windows.py

Pegar la salida completa a Opencode para confirmar el DoD de Fase 8.
"""

from __future__ import annotations

import platform
import sqlite3
import statistics
import sys
import time
from datetime import datetime

from gnd.database.sqlite_monitoring_repository import (
    SqliteMonitoringRepository,
)
from gnd.monitoring.route_monitor import RouteMonitor
from gnd.network.real_traceroute_runner import RealTracerouteRunner

SEP = "=" * 72


def banner(t: str) -> None:
    print(f"\n{SEP}\n{t}\n{SEP}")


def print_anomalies(session, label: str) -> None:
    """Resumen determinista de anomalias por hop.

    REGLA FIJA (2026-07-25): cualquier hop con perdida parcial
    (respondio + descarto) aparece sin importar n. Nunca omitir.
    Ver monitoring/aggregator.format_anomalies_text docstring.
    """
    from gnd.monitoring.aggregator import format_anomalies_text

    print(f"\n  [anomalias {label}]")
    print(format_anomalies_text(session.hop_stats))


def verify_coherence(session, label: str) -> bool:
    """Recomputa manualmente las estadisticas a partir de session.samples
    y las compara con session.hop_stats. Devuelve True si todo coherente.
    """
    print(f"\n  [coherencia {label}]")
    hs_by_hop = {hs.hop_number: hs for hs in session.hop_stats}

    samples_by_hop: dict[int, list[float | None]] = {}
    for s in session.samples:
        samples_by_hop.setdefault(s.hop_number, []).append(s.rtt_ms)

    all_ok = True
    for hop_num, rtts in sorted(samples_by_hop.items()):
        hs = hs_by_hop[hop_num]
        successes = [r for r in rtts if r is not None]
        expected_loss = 100.0 * (len(rtts) - len(successes)) / len(rtts)

        ok_samples = hs.samples == len(rtts)
        ok_success = hs.success_count == len(successes)
        # Comparacion tolerante (usar abs diff < 0.01ms por redondeo).
        ok_loss = abs(hs.loss_pct - expected_loss) < 0.001
        if successes:
            ok_best = abs(hs.best_ms - min(successes)) < 0.01
            ok_worst = abs(hs.worst_ms - max(successes)) < 0.01
            ok_avg = abs(hs.avg_ms - statistics.fmean(successes)) < 0.01
            expected_jitter = statistics.stdev(successes) if len(successes) > 1 else 0.0
            ok_jitter = abs(hs.jitter_ms - expected_jitter) < 0.01
        else:
            ok_best = hs.best_ms is None
            ok_worst = hs.worst_ms is None
            ok_avg = hs.avg_ms is None
            ok_jitter = hs.jitter_ms == 0.0

        ok = (
            ok_samples
            and ok_success
            and ok_loss
            and ok_best
            and ok_worst
            and ok_avg
            and ok_jitter
        )
        status = "OK" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(
            f"    hop {hop_num:2d}  samples={hs.samples}  success={hs.success_count}  "
            f"loss={hs.loss_pct:5.1f}%  best={hs.best_ms}  avg={hs.avg_ms}  "
            f"worst={hs.worst_ms}  jitter={hs.jitter_ms:.2f}  ip={hs.ip}  -> {status}"
        )
        if not ok:
            print(
                f"      esperado: samples={len(rtts)} success={len(successes)} "
                f"loss={expected_loss:.3f} "
                f"best={min(successes) if successes else None} "
                f"worst={max(successes) if successes else None} "
                f"avg={statistics.fmean(successes) if successes else None}"
            )

    return all_ok


def print_session_summary(session, label: str) -> None:
    print(f"\n  [resumen {label}]")
    print(
        f"    run_id={session.run_id} target={session.target_ip} "
        f"provider={session.target_provider}"
    )
    print(
        f"    started={session.started_at.isoformat()} "
        f"finished={session.finished_at.isoformat()}"
    )
    print(
        f"    interval_s={session.interval_s}  "
        f"samples_count={len(session.samples)} hops_observed={len(session.hop_stats)}"
    )
    print("    hop_stats:")
    for hs in session.hop_stats:
        best = f"{hs.best_ms:7.2f}ms" if hs.best_ms is not None else "    N/A"
        avg = f"{hs.avg_ms:7.2f}ms" if hs.avg_ms is not None else "    N/A"
        worst = f"{hs.worst_ms:7.2f}ms" if hs.worst_ms is not None else "    N/A"
        print(
            f"      hop {hs.hop_number:2d}  ip={str(hs.ip):15s} "
            f"best={best} avg={avg} worst={worst} jitter={hs.jitter_ms:6.2f}ms "
            f"loss={hs.loss_pct:5.1f}% "
            f"(samples={hs.samples} success={hs.success_count})"
        )


def main() -> None:
    banner("GND - Fase 8: verificacion end-to-end Monitoreo continuo WinMTR")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"Plataforma    : {platform.system()} {platform.release()}")
    print(f"Reloj         : {datetime.now().isoformat()}")

    runner = RealTracerouteRunner(jump_threshold_ms=40.0)
    monitor = RouteMonitor(traceroute_runner=runner)

    # ------------------------------------------------------------------- #
    banner("1) SESION CORTA 15s - 1.1.1.1 (3 tomas)")
    print(f"  Inicio: {datetime.now().isoformat()}")
    started_perf = time.perf_counter()
    session_short = monitor.monitor(
        target_ip="1.1.1.1",
        target_provider="cloudflare",
        run_id="verify-short",
        interval_s=5.0,
        duration_s=15.0,
        max_hops=10,
        timeout_ms=1000,
    )
    elapsed = time.perf_counter() - started_perf
    print(f"  Fin:    {datetime.now().isoformat()} (elapsed={elapsed:.1f}s)")
    print_session_summary(session_short, "corta")
    print_anomalies(session_short, "corta")
    ok1 = verify_coherence(session_short, "corta")

    # ------------------------------------------------------------------- #
    banner("2) DoD SESION 60s - 1.1.1.1 (12 tomas)")
    print(f"  Inicio: {datetime.now().isoformat()}")
    started_perf = time.perf_counter()
    session_60 = monitor.monitor(
        target_ip="1.1.1.1",
        target_provider="cloudflare",
        run_id="verify-60s",
        interval_s=5.0,
        duration_s=60.0,
        max_hops=10,
        timeout_ms=1000,
    )
    elapsed = time.perf_counter() - started_perf
    print(f"  Fin:    {datetime.now().isoformat()} (elapsed={elapsed:.1f}s)")
    print_session_summary(session_60, "60s")
    print_anomalies(session_60, "60s")
    ok2 = verify_coherence(session_60, "60s")

    # ------------------------------------------------------------------- #
    banner("3) PERSISTENCIA round-trip (60s) en SQLite en memoria")
    conn = sqlite3.connect(":memory:")
    repo = SqliteMonitoringRepository(conn)
    repo.save_session(session_60)
    recovered = repo.get_sessions_by_run("verify-60s")
    print(f"  Sesiones recuperadas para run_id=verify-60s: {len(recovered)}")
    if recovered:
        r = recovered[0]
        print(
            f"    run_id={r.run_id} target={r.target_ip} "
            f"interval_s={r.interval_s} hops={len(r.hop_stats)}"
        )
        # Comparar los hop_stats recuperados con los originales uno a uno.
        original_hops = {h.hop_number: h for h in session_60.hop_stats}
        ok3 = True
        for h in r.hop_stats:
            orig = original_hops.get(h.hop_number)
            if orig != h:
                ok3 = False
                print(f"    DIFF hop {h.hop_number}: " f"orig={orig}  ->  recov={h}")
        if ok3:
            print(f"  Round-trip OK para los {len(r.hop_stats)} hops persistidos.")
    else:
        ok3 = False
        print("  FAIL: no se recupero ninguna sesion.")

    # ------------------------------------------------------------------- #
    banner("RESUMEN DoD Fase 8")
    print(f"  Sesion corta (15s, 3 tomas) coherente: {ok1}")
    print(f"  Sesion DoD (60s, 12 tomas) coherente: {ok2}")
    print(f"  Persistencia SQLite round-trip exacta: {ok3}")
    all_ok = ok1 and ok2 and ok3
    print(f"  GLOBAL: {'OK' if all_ok else 'FAIL'}")
    if not all_ok:
        print(
            "\n  >>> FALLO el DoD. Copiar TODA esta salida a Opencode "
            "para diagnostico."
        )
        sys.exit(1)

    banner("FIN - si todo OK, pegale esta salida a Opencode")
    print(
        "DoD Fase 8: sesion de 60s de monitoreo produce estadisticas "
        "agregadas por hop coherentes con las muestras individuales."
    )


if __name__ == "__main__":
    main()
