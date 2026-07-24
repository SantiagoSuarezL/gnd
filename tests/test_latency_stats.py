"""Tests de LatencyStats — invariantes."""

import pytest

from gnd.models.latency_stats import LatencyStats


def test_latency_stats_valido() -> None:
    s = LatencyStats(
        avg_ms=20.0,
        min_ms=15.0,
        max_ms=25.0,
        jitter_ms=3.0,
        packet_loss_pct=0.0,
        samples=10,
    )
    assert s.avg_ms == 20.0


def test_packet_loss_fuera_de_rango_falla() -> None:
    with pytest.raises(ValueError, match="packet_loss_pct debe estar en \\[0, 100\\]"):
        LatencyStats(
            avg_ms=10, min_ms=5, max_ms=15, jitter_ms=1, packet_loss_pct=-1, samples=5
        )
    with pytest.raises(ValueError, match="packet_loss_pct debe estar en \\[0, 100\\]"):
        LatencyStats(
            avg_ms=10, min_ms=5, max_ms=15, jitter_ms=1, packet_loss_pct=101, samples=5
        )


def test_samples_negativo_falla() -> None:
    with pytest.raises(ValueError, match="samples debe ser >= 0"):
        LatencyStats(
            avg_ms=10, min_ms=5, max_ms=15, jitter_ms=1, packet_loss_pct=0, samples=-1
        )


def test_jitter_negativo_falla() -> None:
    with pytest.raises(ValueError, match="jitter_ms debe ser >= 0"):
        LatencyStats(
            avg_ms=10, min_ms=5, max_ms=15, jitter_ms=-0.1, packet_loss_pct=0, samples=5
        )


def test_latencias_negativas_falla() -> None:
    with pytest.raises(ValueError, match="latencias \\(min/avg/max\\) deben ser >= 0"):
        LatencyStats(
            avg_ms=-1, min_ms=5, max_ms=15, jitter_ms=1, packet_loss_pct=0, samples=5
        )


def test_min_le_avg_le_max_falla() -> None:
    with pytest.raises(ValueError, match="debe cumplirse min<=avg<=max"):
        LatencyStats(
            avg_ms=20, min_ms=25, max_ms=30, jitter_ms=1, packet_loss_pct=0, samples=5
        )


def test_avg_mayor_max_falla() -> None:
    with pytest.raises(ValueError, match="debe cumplirse min<=avg<=max"):
        LatencyStats(
            avg_ms=35, min_ms=10, max_ms=30, jitter_ms=1, packet_loss_pct=0, samples=5
        )
