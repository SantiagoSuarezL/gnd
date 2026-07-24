"""Tests de DiagnosticRun."""

from datetime import datetime, timedelta

import pytest

from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult


def make_probe() -> ProbeResult:
    return ProbeResult(
        target_name="gateway",
        target_ip="10.0.0.1",
        provider="local",
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=1.0,
            min_ms=1.0,
            max_ms=1.0,
            jitter_ms=0.0,
            packet_loss_pct=0.0,
            samples=10,
        ),
        timestamp=datetime.now(),
    )


def make_traceroute() -> TracerouteResult:
    return TracerouteResult(
        target_provider="google",
        hops=[
            TracerouteHop(
                hop_number=1, ip="10.0.0.1", hostname=None, rtt_ms=1.0, responded=True
            )
        ],
        culprit_hop_index=None,
    )


def make_recommendation() -> Recommendation:
    return Recommendation(
        verdict="safe_to_play",
        headline="OK",
        explanation=["Todo bien"],
        responsible_component="unknown",
        score=90,
    )


def test_diagnostic_run_valido() -> None:
    now = datetime.now()
    r = DiagnosticRun(
        run_id="run-1",
        started_at=now,
        finished_at=now + timedelta(seconds=5),
        probes=[make_probe()],
        traceroutes=[make_traceroute()],
        active_game_server=None,
        recommendation=make_recommendation(),
    )
    assert r.run_id == "run-1"


def test_finished_before_started_falla() -> None:
    now = datetime.now()
    with pytest.raises(
        ValueError, match="finished_at no puede ser anterior a started_at"
    ):
        DiagnosticRun(
            run_id="run-1",
            started_at=now + timedelta(seconds=5),
            finished_at=now,
            probes=[],
            traceroutes=[],
            active_game_server=None,
            recommendation=make_recommendation(),
        )


def test_run_id_vacio_falla() -> None:
    now = datetime.now()
    with pytest.raises(ValueError, match="run_id no puede ser vacío"):
        DiagnosticRun(
            run_id="",
            started_at=now,
            finished_at=now + timedelta(seconds=1),
            probes=[],
            traceroutes=[],
            active_game_server=None,
            recommendation=make_recommendation(),
        )


def test_active_game_server_valido() -> None:
    now = datetime.now()
    ags = ActiveGameServerInfo(
        ip="1.2.3.4",
        port=5000,
        protocol="udp",
        detected_via="process_connection_scan",
        process_name="LoL.exe",
    )
    r = DiagnosticRun(
        run_id="run-1",
        started_at=now,
        finished_at=now + timedelta(seconds=5),
        probes=[make_probe()],
        traceroutes=[make_traceroute()],
        active_game_server=ags,
        recommendation=make_recommendation(),
    )
    assert r.active_game_server is not None
    assert r.active_game_server.ip == "1.2.3.4"
