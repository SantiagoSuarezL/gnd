"""Perfil E2E del RunFullDiagnostics.execute() completo (paralelismo incluido).

Mide el wall-clock real con paralelismo: ThreadPoolExecutor lanza 6 pings
+ 2 traceroutes concurrentes. El wall-clock total deberia ser ~= max(probe)
+ max(traceroute), no la suma.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "src")

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.composition_root import _resolve_gateway_ip
from gnd.config import get_settings
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository
from gnd.diagnostics.riot.active_game_server_detector import (
    ActiveGameServerDetector,
)
from gnd.network.real_ping_runner import RealPingRunner
from gnd.network.real_traceroute_runner import RealTracerouteRunner


def main() -> None:
    settings = get_settings()
    print("=== Profile E2E RunFullDiagnostics.execute() ===")
    pc = settings.probes
    print(f"ping_count={pc.ping_count} timeout_ms={pc.timeout_ms}")
    print(f"traceroute_max_hops={settings.probes.traceroute_max_hops}")
    print(f"riot_public={settings.targets.riot_public}")
    print()

    ping = RealPingRunner()
    tracer = RealTracerouteRunner(
        jump_threshold_ms=settings.thresholds.hop_jump_threshold_ms
    )
    inspector = ActiveGameServerDetector()
    factory = SqliteConnectionFactory(os.path.expandvars(settings.database.path))
    repo = SqliteDiagnosticsRepository(factory)

    targets = DiagnosticTargets(
        gateway_ip=_resolve_gateway_ip(),
        google_dns=settings.targets.google_dns,
        cloudflare=settings.targets.cloudflare,
        quad9=settings.targets.quad9,
        riot_public=list(settings.targets.riot_public),
        game_process_names=set(settings.game_detection.process_names),
    )
    params = DiagnosticParams(
        ping_count=settings.probes.ping_count,
        ping_timeout_ms=settings.probes.timeout_ms,
        traceroute_max_hops=settings.probes.traceroute_max_hops,
        traceroute_timeout_ms=settings.probes.timeout_ms,
        baseline_period_days=30,
        packet_loss_warning_pct=settings.thresholds.packet_loss_warning_pct,
        packet_loss_critical_pct=settings.thresholds.packet_loss_critical_pct,
        jitter_warning_ms=settings.thresholds.jitter_warning_ms,
        jitter_critical_ms=settings.thresholds.jitter_critical_ms,
    )

    use_case = RunFullDiagnostics(
        ping_runner=ping,
        traceroute_runner=tracer,
        connection_inspector=inspector,
        repository=repo,
        db_factory=factory,
    )

    t0 = time.perf_counter()
    run = use_case.execute(targets, params, progress_callback=lambda s: None)
    dt = time.perf_counter() - t0

    print(f"WALL CLOCK TOTAL: {dt:.2f}s")
    print(f"  probes      : {len(run.probes)}")
    print(f"  traceroutes : {len(run.traceroutes)}")
    rec = run.recommendation
    print(f"  recommend   : verdict={rec.verdict} score={rec.score}")
    baselines = use_case.last_baselines
    nonempty = sum(1 for b in baselines.values() if b.sample_count > 0)
    print(f"  baselines   : {len(baselines)} total, {nonempty} con datos (n>0)")
    print()
    if dt <= 15.0:
        print(f">>> PRD §8 OK: {dt:.1f}s < 15s objetivo.")
    else:
        print(f">>> PRD §8 OFF: {dt:.1f}s > 15s objetivo.")


if __name__ == "__main__":
    main()
