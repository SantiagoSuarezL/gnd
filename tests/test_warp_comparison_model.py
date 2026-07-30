"""Tests del modelo WarpComparisonResult y WarpComparisonDelta (Fase 12b.4).

Cubrimos:
- Inmutabilidad (frozen=True).
- Properties computadas (score_change_pct).
- get_provider_delta helper.
- Default values correctos.
"""

from __future__ import annotations

import pytest

from gnd.models.warp_comparison import WarpComparisonDelta, WarpComparisonResult


def _delta(
    metric: str = "avg_latency_ms", off: float = 50.0, on: float = 60.0
) -> WarpComparisonDelta:
    return WarpComparisonDelta(
        metric_name=metric,
        warp_off_value=off,
        warp_on_value=on,
        delta=on - off,
        delta_pct=round(((on - off) / off) * 100, 1) if off else None,
    )


class TestWarpComparisonDelta:
    def test_delta_positivo_significa_peor(self) -> None:
        d = _delta(off=50.0, on=60.0)
        assert d.delta == 10.0
        assert d.delta_pct == 20.0

    def test_delta_negativo_significa_mejor(self) -> None:
        d = _delta(off=50.0, on=40.0)
        assert d.delta == -10.0
        assert d.delta_pct == -20.0

    def test_delta_pct_none_si_baseline_cero(self) -> None:
        d = WarpComparisonDelta(
            metric_name="avg_latency_ms",
            warp_off_value=0.0,
            warp_on_value=10.0,
            delta=10.0,
        )
        assert d.delta_pct is None

    def test_inmutable(self) -> None:
        d = _delta()
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            d.delta = 999  # type: ignore[misc]

    def test_diferentes_metricas(self) -> None:
        for m in ["avg_latency_ms", "jitter_ms", "packet_loss_pct", "score"]:
            d = WarpComparisonDelta(
                metric_name=m,
                warp_off_value=10.0,
                warp_on_value=12.0,
                delta=2.0,
            )
            assert d.metric_name == m


class TestWarpComparisonResult:
    def _basic_result(self) -> WarpComparisonResult:
        return WarpComparisonResult(
            warp_off_run_id="r1",
            warp_on_run_id="r2",
            warp_off_score=80.0,
            warp_on_score=70.0,
            score_delta=-10.0,
            overall_verdict="improved",
            verdict_explanation=["WARP mejora el score"],
        )

    def test_constructor_basico(self) -> None:
        r = self._basic_result()
        assert r.warp_off_run_id == "r1"
        assert r.warp_on_run_id == "r2"
        assert r.warp_off_score == 80.0
        assert r.warp_on_score == 70.0
        assert r.score_delta == -10.0

    def test_defaults(self) -> None:
        r = self._basic_result()
        assert r.provider_deltas == {}
        assert r.verdict_explanation == ["WARP mejora el score"]
        assert r.warp_off_duration_ms is None
        assert r.warp_on_duration_ms is None
        assert r.warp_controller_available is True

    def test_score_change_pct(self) -> None:
        r = self._basic_result()
        # score_delta=-10, warp_off_score=80 -> -12.5%
        assert r.score_change_pct == -12.5

    def test_score_change_pct_none_si_baseline_cero(self) -> None:
        r = WarpComparisonResult(
            warp_off_run_id="r1",
            warp_on_run_id="r2",
            warp_off_score=0.0,
            warp_on_score=0.0,
            score_delta=0.0,
        )
        assert r.score_change_pct is None

    def test_get_provider_delta_existente(self) -> None:
        d = _delta()
        r = WarpComparisonResult(
            warp_off_run_id="r1",
            warp_on_run_id="r2",
            warp_off_score=80.0,
            warp_on_score=70.0,
            score_delta=-10.0,
            provider_deltas={"google": [d]},
        )
        found = r.get_provider_delta("google", "avg_latency_ms")
        assert found is d

    def test_get_provider_delta_inexistente(self) -> None:
        r = self._basic_result()
        assert r.get_provider_delta("cloudflare", "avg_latency_ms") is None
        assert r.get_provider_delta("google", "jitter_ms") is None

    def test_inmutable(self) -> None:
        from dataclasses import FrozenInstanceError

        r = self._basic_result()
        with pytest.raises(FrozenInstanceError):
            r.score_delta = 999  # type: ignore[misc]

    def test_verdict_values_validos(self) -> None:
        """Los veredictos válidos son 'improved'/'degraded'/'neutral'/'unavailable'."""
        for v in ["improved", "degraded", "neutral", "unavailable"]:
            r = WarpComparisonResult(
                warp_off_run_id="r1",
                warp_on_run_id="r2",
                warp_off_score=80.0,
                warp_on_score=80.0,
                score_delta=0.0,
                overall_verdict=v,
            )
            assert r.overall_verdict == v

    def test_provider_deltas_multiples_providers(self) -> None:
        d_google = _delta(metric="avg_latency_ms", off=30.0, on=40.0)
        d_cf = _delta(metric="avg_latency_ms", off=20.0, on=15.0)
        r = WarpComparisonResult(
            warp_off_run_id="r1",
            warp_on_run_id="r2",
            warp_off_score=80.0,
            warp_on_score=75.0,
            score_delta=-5.0,
            provider_deltas={
                "google": [d_google],
                "cloudflare": [d_cf],
            },
        )
        assert len(r.provider_deltas) == 2
        assert r.get_provider_delta("google", "avg_latency_ms") is d_google
        assert r.get_provider_delta("cloudflare", "avg_latency_ms") is d_cf
