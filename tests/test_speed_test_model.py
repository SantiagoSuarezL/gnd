"""Tests del modelo SpeedTestResult, SpeedTestDelta, SpeedTestComparisonResult (Fase 12b.5).

Cubrimos:
- Inmutabilidad (frozen=True).
- Validación de invariantes en __post_init__.
- get_delta helper.
- Default values correctos.
"""

from __future__ import annotations

import pytest

from gnd.models.speed_test import (
    SpeedTestComparisonResult,
    SpeedTestDelta,
    SpeedTestResult,
)


def _result(
    latency_ms: float = 15.0,
    jitter_ms: float = 2.0,
    download_mbps: float = 100.0,
    upload_mbps: float = 50.0,
    packet_loss_pct: float = 0.0,
) -> SpeedTestResult:
    return SpeedTestResult(
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        packet_loss_pct=packet_loss_pct,
        server_name="Test Server",
        server_country="Test Country",
        isp="Test ISP",
    )


class TestSpeedTestResult:
    def test_constructor_basico(self) -> None:
        r = _result()
        assert r.latency_ms == 15.0
        assert r.jitter_ms == 2.0
        assert r.download_mbps == 100.0
        assert r.upload_mbps == 50.0
        assert r.packet_loss_pct == 0.0
        assert r.server_name == "Test Server"

    def test_inmutable(self) -> None:
        r = _result()
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            r.latency_ms = 999  # type: ignore[misc]

    def test_latency_negativa_raise(self) -> None:
        with pytest.raises(ValueError, match="latency_ms"):
            SpeedTestResult(
                latency_ms=-1.0,
                jitter_ms=2.0,
                download_mbps=100.0,
                upload_mbps=50.0,
                packet_loss_pct=0.0,
                server_name="Test",
                server_country="Test",
                isp="Test",
            )

    def test_jitter_negativo_raise(self) -> None:
        with pytest.raises(ValueError, match="jitter_ms"):
            SpeedTestResult(
                latency_ms=15.0,
                jitter_ms=-1.0,
                download_mbps=100.0,
                upload_mbps=50.0,
                packet_loss_pct=0.0,
                server_name="Test",
                server_country="Test",
                isp="Test",
            )

    def test_download_negativo_raise(self) -> None:
        with pytest.raises(ValueError, match="download_mbps"):
            SpeedTestResult(
                latency_ms=15.0,
                jitter_ms=2.0,
                download_mbps=-1.0,
                upload_mbps=50.0,
                packet_loss_pct=0.0,
                server_name="Test",
                server_country="Test",
                isp="Test",
            )

    def test_upload_negativo_raise(self) -> None:
        with pytest.raises(ValueError, match="upload_mbps"):
            SpeedTestResult(
                latency_ms=15.0,
                jitter_ms=2.0,
                download_mbps=100.0,
                upload_mbps=-1.0,
                packet_loss_pct=0.0,
                server_name="Test",
                server_country="Test",
                isp="Test",
            )

    def test_packet_loss_fuera_de_rango_raise(self) -> None:
        with pytest.raises(ValueError, match="packet_loss_pct"):
            SpeedTestResult(
                latency_ms=15.0,
                jitter_ms=2.0,
                download_mbps=100.0,
                upload_mbps=50.0,
                packet_loss_pct=150.0,
                server_name="Test",
                server_country="Test",
                isp="Test",
            )

    def test_server_name_vacio_raise(self) -> None:
        with pytest.raises(ValueError, match="server_name"):
            SpeedTestResult(
                latency_ms=15.0,
                jitter_ms=2.0,
                download_mbps=100.0,
                upload_mbps=50.0,
                packet_loss_pct=0.0,
                server_name="",
                server_country="Test",
                isp="Test",
            )


class TestSpeedTestDelta:
    def test_delta_positivo(self) -> None:
        d = SpeedTestDelta(
            metric_name="latency_ms",
            baseline_value=15.0,
            comparison_value=20.0,
            delta=5.0,
            delta_pct=33.3,
        )
        assert d.delta == 5.0
        assert d.delta_pct == 33.3

    def test_delta_negativo(self) -> None:
        d = SpeedTestDelta(
            metric_name="latency_ms",
            baseline_value=20.0,
            comparison_value=15.0,
            delta=-5.0,
            delta_pct=-25.0,
        )
        assert d.delta == -5.0
        assert d.delta_pct == -25.0

    def test_delta_pct_none_si_baseline_cero(self) -> None:
        d = SpeedTestDelta(
            metric_name="download_mbps",
            baseline_value=0.0,
            comparison_value=100.0,
            delta=100.0,
        )
        assert d.delta_pct is None

    def test_inmutable(self) -> None:
        d = SpeedTestDelta(
            metric_name="latency_ms",
            baseline_value=15.0,
            comparison_value=20.0,
            delta=5.0,
        )
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            d.delta = 999  # type: ignore[misc]


class TestSpeedTestComparisonResult:
    def _basic_result(self) -> SpeedTestComparisonResult:
        return SpeedTestComparisonResult(
            baseline=_result(),
            comparison=_result(),
            deltas=[],
            overall_verdict="neutral",
            verdict_explanation=["Test explanation"],
        )

    def test_constructor_basico(self) -> None:
        r = self._basic_result()
        assert r.overall_verdict == "neutral"
        assert r.verdict_explanation == ["Test explanation"]

    def test_defaults(self) -> None:
        r = self._basic_result()
        assert r.deltas == []
        assert r.baseline_duration_ms is None
        assert r.comparison_duration_ms is None
        assert r.speed_test_controller_available is True

    def test_get_delta_existente(self) -> None:
        d = SpeedTestDelta(
            metric_name="latency_ms",
            baseline_value=15.0,
            comparison_value=20.0,
            delta=5.0,
        )
        r = SpeedTestComparisonResult(
            baseline=_result(),
            comparison=_result(),
            deltas=[d],
        )
        found = r.get_delta("latency_ms")
        assert found is d

    def test_get_delta_inexistente(self) -> None:
        r = self._basic_result()
        assert r.get_delta("nonexistent") is None

    def test_inmutable(self) -> None:
        from dataclasses import FrozenInstanceError

        r = self._basic_result()
        with pytest.raises(FrozenInstanceError):
            r.overall_verdict = "changed"  # type: ignore[misc]

    def test_verdict_values_validos(self) -> None:
        for v in ["improved", "degraded", "neutral", "unavailable"]:
            r = SpeedTestComparisonResult(
                baseline=_result(),
                comparison=_result(),
                deltas=[],
                overall_verdict=v,
            )
            assert r.overall_verdict == v
