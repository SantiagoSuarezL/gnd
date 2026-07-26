"""Verificación E2E del fix Fase 9: baseline anomalies → Recommendation.

Este script simula el escenario exacto reportado:
  - Google actual 18.8ms vs baseline 13.3ms (anómalo: > avg + 2*stddev)
  - Quad9  actual 17.8ms vs baseline 12.6ms (anómalo)
  - Todo lo demás OK

Y verifica que el DiagnosticRun final refleje esas anomalías en su
Recommendation, no solo en Historical Comparison.

USO:
    python scripts/verify_phase9_fix.py                    # DB temporal en /tmp (no toca producción)
    python scripts/verify_phase9_fix.py --db-path ruta.db  # DB personalizada
"""
import argparse
import os
import tempfile
from datetime import datetime, timedelta

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult


def _probe(
    provider: str, avg_ms: float, loss: float = 0.0, jitter: float = 2.0
) -> ProbeResult:
    return ProbeResult(
        target_name=f"t-{provider}",
        target_ip="1.2.3.4",
        provider=provider,
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=avg_ms,
            min_ms=max(0, avg_ms - 5),
            max_ms=avg_ms + 5,
            jitter_ms=jitter,
            packet_loss_pct=loss,
            samples=8,
        ),
        timestamp=datetime.now(),
    )


def build_use_case_with_db(db_path: str):
    """Construye RunFullDiagnostics con una DB específica (no producción)."""
    from gnd.config import get_settings
    from gnd.diagnostics.riot.active_game_server_detector import ActiveGameServerDetector
    from gnd.network.real_ping_runner import RealPingRunner
    from gnd.network.real_traceroute_runner import RealTracerouteRunner

    settings = get_settings()

    targets = DiagnosticTargets(
        gateway_ip="192.168.1.1",
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

    db_factory = SqliteConnectionFactory(db_path)
    repository = SqliteDiagnosticsRepository(db_factory)

    use_case = RunFullDiagnostics(
        ping_runner=RealPingRunner(),
        traceroute_runner=RealTracerouteRunner(
            jump_threshold_ms=settings.thresholds.hop_jump_threshold_ms,
        ),
        connection_inspector=ActiveGameServerDetector(),
        repository=repository,
        db_factory=db_factory,
    )
    return use_case, targets, params


def main(db_path: str | None = None) -> bool:
    print("=" * 70)
    print("VERIFICACION E2E FIX FASE 9 - Baseline anomalies -> Recommendation")
    print("=" * 70)

    # Resolver DB path: si no se pasa, usar temporal en directorio temp del sistema
    if db_path is None:
        db_path = os.path.join(tempfile.gettempdir(), f"gnd_verify_phase9_{os.getpid()}.db")
        print(f"\n[INFO] Usando DB temporal: {db_path}")
    else:
        print(f"\n[INFO] Usando DB especificada: {db_path}")

    # 1. Poblar la DB con histórico
    print("\n[1/3] Poblando base de datos histórica...")
    use_case, targets, params = build_use_case_with_db(db_path)
    repo = use_case._repo  # acceso al repo real para poblar histórico

    # Generar 30 corridas históricas con latencias normales
    for i in range(30):
        day_ago = 30 - i
        ts = datetime.now() - timedelta(days=day_ago)
        probes = [
            _probe("local", 5.0, 0.0, 1.0),
            _probe("google", 13.3, 0.0, 0.5),
            _probe("cloudflare", 12.0, 0.0, 0.5),
            _probe("quad9", 12.6, 0.0, 0.5),
            _probe("riot_public", 20.0, 0.0, 2.0),
        ]
        run = type("Run", (), {
            "run_id": f"hist-{i:03d}",
            "started_at": ts,
            "finished_at": ts,
            "probes": probes,
            "traceroutes": [],
            "active_game_server": None,
            "recommendation": type("Rec", (), {
                "verdict": "safe_to_play",
                "headline": " conexion estable",
                "explanation": ["OK"],
                "responsible_component": "unknown",
                "score": 95,
            })(),
        })()
        repo.save_run(run)
    print("    -> 30 corridas historicas insertadas")

    # 2. Ejecutar diagnóstico actual CON anomalías (Google 18.8, Quad9 17.8)
    print("\n[2/3] Ejecutando diagnóstico actual con anomalías...")
    targets = DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com", "lol.secure.dyn.riotcdn.net"],
        game_process_names={"League of Legends.exe"},
    )
    params = DiagnosticParams(
        ping_count=8,
        ping_timeout_ms=1000,
        traceroute_max_hops=30,
        traceroute_timeout_ms=1000,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
    )

    # Monkey-patch del ping_runner para devolver nuestros probes anómalos
    anomaly_probes = [
        _probe("local", 5.0),
        _probe("google", 18.8),       # ANÓMALO: baseline 13.3 + 2*0.5 = 14.3
        _probe("cloudflare", 12.0),    # OK
        _probe("quad9", 17.8),         # ANÓMALO: baseline 12.6 + 2*0.5 = 13.6
        _probe("riot_public", 20.0),
    ]

    def fake_ping(target_ip, target_name, provider, count, timeout_ms):
        for p in anomaly_probes:
            match_provider = p.provider == provider
            match_riot = provider == "riot_public" and "riot_public" in p.provider
            if match_provider or match_riot:
                return p
        # fallback
        return anomaly_probes[0]

    use_case._ping.ping = fake_ping

    # También monkey-patch traceroute y inspector (no críticos para este test)
    use_case._tracer.traceroute = lambda *a, **kw: type("TR", (), {
        "target_provider": kw.get("target_provider", "cloudflare"),
        "hops": [],
        "culprit_hop_index": None,
    })()
    use_case._inspector.detect_active_game_server = lambda *a, **kw: None

    run = use_case.execute(targets, params)
    print(f"    -> DiagnosticRun completado: {run.run_id}")

    # 3. Verificar que la Recommendation refleja las anomalías
    print("\n[3/3] Verificando Recommendation final...")
    rec = run.recommendation
    print(f"    Veredicto: {rec.verdict}")
    print(f"    Responsable: {rec.responsible_component}")
    print(f"    Score: {rec.score}")
    print("    Explicación:")
    for line in rec.explanation:
        print(f"      - {line}")

    # Aserciones del fix
    success = True

    # Veredicto NO puede ser safe_to_play
    if rec.verdict == "safe_to_play":
        print("\n[FAIL] Veredicto es 'safe_to_play' — el bug NO esta corregido")
        success = False
    else:
        print(f"\n[PASS] Veredicto degradado a '{rec.verdict}' (no safe_to_play)")

    # Explicación debe mencionar Google anómalo
    google_mentioned = any(
        "google" in e.lower() and "18.8" in e for e in rec.explanation
    )
    if not google_mentioned:
        print("[FAIL] Explicación no menciona anomalía de Google (18.8ms)")
        success = False
    else:
        print("[PASS] Explicación menciona anomalía Google (18.8ms)")

    # Explicación debe mencionar Quad9 anómalo
    quad9_mentioned = any("quad9" in e.lower() and "17.8" in e for e in rec.explanation)
    if not quad9_mentioned:
        print("[FAIL] Explicación no menciona anomalía de Quad9 (17.8ms)")
        success = False
    else:
        print("[PASS] Explicación menciona anomalía Quad9 (17.8ms)")

    # NO debe tener el texto ghost "Todos los diagnósticos son normales"
    ghost_text = any(
        "normales" in e.lower() or "es seguro jugar" in e.lower()
        for e in rec.explanation
    )
    if ghost_text:
        print("[FAIL] Texto ghost 'normales/seguro' presente junto a anomalías")
        success = False
    else:
        print("[PASS] Sin texto contradictorio 'normales/seguro'")

# Responsable debe ser 'isp' (heurística: anomalías solo en Internet externo)
    if rec.responsible_component != "isp":
        comp = rec.responsible_component
        msg = f"[INFO] responsible_component='{comp}' (esperado 'isp')"
        print(msg)
    else:
        print("[PASS] responsible_component='isp' (anomalías solo en Internet externo)")

    print("\n" + "=" * 70)
    if success:
        msg = "[SUCCESS] FIX FASE 9 CONFIRMADO: Baseline anomalies -> Recommendation OK"
        print(msg)
    else:
        print("[FAIL] FIX FASE 9 FALLO: Ver revisiones arriba")
    print("=" * 70)
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verificación E2E fix Fase 9: baseline anomalies -> Recommendation"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--db-path",
        metavar="PATH",
        help="Ruta a archivo SQLite a usar (por defecto: temporal en /tmp)",
    )
    group.add_argument(
        "--memory",
        action="store_true",
        help="Usar SQLite en memoria (:memory:) — más rápido, no persiste",
    )
    args = parser.parse_args()

    db_path: str | None
    if args.memory:
        db_path = ":memory:"
    else:
        db_path = args.db_path

    ok = main(db_path=db_path)
    exit(0 if ok else 1)