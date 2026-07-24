"""Tests de HistoricalBaseline."""

import pytest

from gnd.models.historical_baseline import HistoricalBaseline


def test_historical_baseline_valido() -> None:
    b = HistoricalBaseline(
        provider="google",
        period_days=30,
        avg_ms=25.0,
        stddev_ms=5.0,
        sample_count=100,
    )
    assert b.provider == "google"


def test_period_days_invalido_falla() -> None:
    with pytest.raises(ValueError, match="period_days debe ser >= 1"):
        HistoricalBaseline(
            provider="google", period_days=0, avg_ms=10, stddev_ms=0, sample_count=10
        )


def test_stddev_cero_con_un_solo_sample_ok() -> None:
    # sample_count <= 1 => stddev debe ser 0
    b = HistoricalBaseline(
        provider="google", period_days=30, avg_ms=20.0, stddev_ms=0.0, sample_count=1
    )
    assert b.stddev_ms == 0.0


def test_stddev_no_cero_con_un_solo_sample_falla() -> None:
    with pytest.raises(ValueError, match="stddev_ms debe ser 0 si sample_count<=1"):
        HistoricalBaseline(
            provider="google",
            period_days=30,
            avg_ms=20.0,
            stddev_ms=5.0,
            sample_count=1,
        )


def test_valores_negativos_falla() -> None:
    with pytest.raises(ValueError, match="avg_ms debe ser >= 0"):
        HistoricalBaseline(
            provider="google", period_days=30, avg_ms=-1, stddev_ms=0, sample_count=10
        )
    with pytest.raises(ValueError, match="stddev_ms debe ser >= 0"):
        HistoricalBaseline(
            provider="google", period_days=30, avg_ms=20, stddev_ms=-1, sample_count=10
        )
    with pytest.raises(ValueError, match="sample_count debe ser >= 0"):
        HistoricalBaseline(
            provider="google", period_days=30, avg_ms=20, stddev_ms=0, sample_count=-1
        )
