"""Tests de FakeDiagnosticsRepository — separación de providers (TECHNICAL_SPEC.md §3)."""

from datetime import datetime, timedelta

from gnd.domain.fakes import FakeDiagnosticsRepository
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult


def make_probe(provider: str, target_ip: str = "1.2.3.4") -> ProbeResult:
    return ProbeResult(
        target_name=f"target-{provider}",
        target_ip=target_ip,
        provider=provider,
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=20.0,
            min_ms=15.0,
            max_ms=25.0,
            jitter_ms=3.0,
            packet_loss_pct=0.0,
            samples=10,
        ),
        timestamp=datetime.now(),
    )


def make_traceroute(provider: str) -> TracerouteResult:
    return TracerouteResult(
        target_provider=provider,
        hops=[
            TracerouteHop(
                hop_number=1, ip="1.2.3.4", hostname=None, rtt_ms=10.0, responded=True
            )
        ],
        culprit_hop_index=None,
    )


def make_rec() -> Recommendation:
    return Recommendation(
        verdict="safe_to_play",
        headline="OK",
        explanation=["Todo bien"],
        responsible_component="unknown",
        score=90,
    )


def make_run(run_id: str, probes: list[ProbeResult]) -> DiagnosticRun:
    now = datetime.now()
    return DiagnosticRun(
        run_id=run_id,
        started_at=now,
        finished_at=now + timedelta(seconds=5),
        probes=probes,
        traceroutes=[make_traceroute(probes[0].provider)],
        active_game_server=None,
        recommendation=make_rec(),
    )


def test_fake_repository_separation_riot_public_vs_riot_game_server() -> None:
    """TECHNICAL_SPEC.md §3: riot_public y riot_game_server son providers
    DISTINTOS — nunca deben mezclarse en queries históricas.
    """
    repo = FakeDiagnosticsRepository()

    # Run 1: solo riot_public
    run_public = make_run("run-public", [make_probe("riot_public", "104.160.136.3")])
    # Run 2: solo riot_game_server (IP dinámica distinta)
    run_game = make_run("run-game", [make_probe("riot_game_server", "185.40.64.1")])

    repo.save(run_public)
    repo.save(run_game)

    # Query por riot_public -> SOLO run-public
    public_runs = repo.get_by_provider("riot_public")
    assert len(public_runs) == 1
    assert public_runs[0].run_id == "run-public"
    # Verificar que el probe dentro es riot_public
    assert all(p.provider == "riot_public" for r in public_runs for p in r.probes)

    # Query por riot_game_server -> SOLO run-game
    game_runs = repo.get_by_provider("riot_game_server")
    assert len(game_runs) == 1
    assert game_runs[0].run_id == "run-game"
    assert all(p.provider == "riot_game_server" for r in game_runs for p in r.probes)

    # Query por google -> VACÍO (no hay runs de google)
    google_runs = repo.get_by_provider("google")
    assert google_runs == []


def test_fake_repository_get_all_returns_both() -> None:
    """get_all() devuelve todos, get_by_provider filtra."""
    repo = FakeDiagnosticsRepository()
    run1 = make_run("run-1", [make_probe("google")])
    run2 = make_run("run-2", [make_probe("cloudflare")])
    repo.save(run1)
    repo.save(run2)

    all_runs = repo.get_all()
    assert len(all_runs) == 2

    google = repo.get_by_provider("google")
    assert len(google) == 1
    assert google[0].run_id == "run-1"

    cloudflare = repo.get_by_provider("cloudflare")
    assert len(cloudflare) == 1
    assert cloudflare[0].run_id == "run-2"


def test_fake_repository_limit_works() -> None:
    repo = FakeDiagnosticsRepository()
    for i in range(5):
        repo.save(make_run(f"run-{i}", [make_probe("google", f"8.8.8.{i}")]))

    limited = repo.get_by_provider("google", limit=3)
    assert len(limited) == 3
    # Los últimos 3 (run-2, run-3, run-4)
    assert limited[-1].run_id == "run-4"


def test_fake_repository_clear_resets() -> None:
    repo = FakeDiagnosticsRepository()
    repo.save(make_run("run-1", [make_probe("google")]))
    repo.clear()
    assert repo.get_all() == []


def test_fake_repository_empty_provider_returns_empty() -> None:
    repo = FakeDiagnosticsRepository()
    repo.save(make_run("run-1", [make_probe("google")]))
    empty = repo.get_by_provider("inexistente")
    assert empty == []
