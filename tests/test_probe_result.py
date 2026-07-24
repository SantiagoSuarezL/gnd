"""Tests de ProbeResult — invariantes del modelo."""

from datetime import datetime

import pytest

from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult


def make_stats() -> LatencyStats:
    return LatencyStats(
        avg_ms=20.0,
        min_ms=15.0,
        max_ms=25.0,
        jitter_ms=3.0,
        packet_loss_pct=0.0,
        samples=10,
    )


def test_probe_result_success_con_stats_ok() -> None:
    r = ProbeResult(
        target_name="google",
        target_ip="8.8.8.8",
        provider="google",
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=make_stats(),
        timestamp=datetime.now(),
    )
    assert r.outcome == ProbeOutcomeKind.SUCCESS
    assert r.stats is not None


def test_probe_result_failed_stats_none_ok() -> None:
    r = ProbeResult(
        target_name="google",
        target_ip="8.8.8.8",
        provider="google",
        outcome=ProbeOutcomeKind.FILTERED,
        stats=None,
        timestamp=datetime.now(),
    )
    assert r.outcome == ProbeOutcomeKind.FILTERED
    assert r.stats is None


def test_probe_result_success_sin_stats_falla() -> None:
    with pytest.raises(
        ValueError, match="stats no puede ser None cuando outcome=SUCCESS"
    ):
        ProbeResult(
            target_name="google",
            target_ip="8.8.8.8",
            provider="google",
            outcome=ProbeOutcomeKind.SUCCESS,
            stats=None,
            timestamp=datetime.now(),
        )


def test_probe_result_failed_con_stats_falla() -> None:
    with pytest.raises(ValueError, match="stats debe ser None cuando outcome=FILTERED"):
        ProbeResult(
            target_name="google",
            target_ip="8.8.8.8",
            provider="google",
            outcome=ProbeOutcomeKind.FILTERED,
            stats=make_stats(),
            timestamp=datetime.now(),
        )


def test_target_name_vacio_falla() -> None:
    with pytest.raises(ValueError, match="target_name no puede ser vacío"):
        ProbeResult(
            target_name="",
            target_ip="8.8.8.8",
            provider="google",
            outcome=ProbeOutcomeKind.FILTERED,
            stats=None,
            timestamp=datetime.now(),
        )


def test_target_ip_vacio_falla() -> None:
    with pytest.raises(ValueError, match="target_ip no puede ser vacío"):
        ProbeResult(
            target_name="google",
            target_ip="",
            provider="google",
            outcome=ProbeOutcomeKind.FILTERED,
            stats=None,
            timestamp=datetime.now(),
        )


def test_provider_vacio_falla() -> None:
    with pytest.raises(ValueError, match="provider no puede ser vacío"):
        ProbeResult(
            target_name="google",
            target_ip="8.8.8.8",
            provider="",
            outcome=ProbeOutcomeKind.FILTERED,
            stats=None,
            timestamp=datetime.now(),
        )


def test_probe_outcome_kind_valores() -> None:
    assert ProbeOutcomeKind.SUCCESS.name == "SUCCESS"
    assert ProbeOutcomeKind.FILTERED.name == "FILTERED"
    assert ProbeOutcomeKind.UNREACHABLE.name == "UNREACHABLE"
    assert ProbeOutcomeKind.TIMEOUT.name == "TIMEOUT"
