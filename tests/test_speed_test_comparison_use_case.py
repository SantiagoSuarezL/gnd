"""Tests del SpeedTestComparisonUseCase (Fase 12b.5).

Cubrimos:
- Flujo completo: ejecuta diagnóstico + speed test, computa deltas.
- Comportamiento cuando SpeedTestController no está disponible.
- Veredictos: improved, degraded, neutral, unavailable.
- Cálculo de deltas entre diagnóstico y speed test.
- Manejo de errores (SpeedTestError desde run()).
- skip_if_speedtest_unavailable.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
)
from gnd.application.speed_test_comparison import (
    SpeedTestComparisonParams,
    SpeedTestComparisonUseCase,
)
from gnd.domain.fakes.fake_speed_test_controller import FakeSpeedTestController
from gnd.domain.ports.speed_test_controller import SpeedTestError
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.speed_test import SpeedTestResult


def _probe(
    provider: str, target: str, avg_ms: float, jitter: float = 1.0
) -> ProbeResult:
    return ProbeResult(
        target_name=target,
        target_ip="1.2.3.4",
        provider=provider,
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=avg_ms,
            min_ms=avg_ms - 1,
            max_ms=avg_ms + 1,
            jitter_ms=jitter,
            packet_loss_pct=0.0,
            samples=10,
        ),
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )


def _recommendation(score: int) -> Recommendation:
    return Recommendation(
        verdict="safe_to_play" if score >= 80 else "playable",
        headline="Test",
        explanation=["Test explanation"],
        responsible_component="unknown",
        score=score,
    )


def _make_run(run_id: str, probes: list[ProbeResult], score: int) -> DiagnosticRun:
    return DiagnosticRun(
        run_id=run_id,
        started_at=datetime(2026, 1, 1, 12, 0, 0),
        finished_at=datetime(2026, 1, 1, 12, 0, 30),
        probes=probes,
        traceroutes=[],
        active_game_server=None,
        recommendation=_recommendation(score),
        dns_results=(),
        interface_snapshot=None,
    )


def _make_targets() -> DiagnosticTargets:
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names=set(),
    )


def _make_params() -> DiagnosticParams:
    return DiagnosticParams(
        ping_count=4,
        ping_timeout_ms=1000,
        traceroute_max_hops=10,
        traceroute_timeout_ms=1000,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
    )


def _speed_test_result(
    latency_ms: float = 15.0,
    download_mbps: float = 100.0,
    upload_mbps: float = 50.0,
    packet_loss_pct: float = 0.0,
) -> SpeedTestResult:
    return SpeedTestResult(
        latency_ms=latency_ms,
        jitter_ms=2.0,
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        packet_loss_pct=packet_loss_pct,
        server_name="Test Server",
        server_country="Test Country",
        isp="Test ISP",
    )


class _MockDiagnostics:
    """Mock de RunFullDiagnostics que devuelve runs programables."""

    def __init__(self, run: DiagnosticRun) -> None:
        self._run = run
        self.call_count = 0

    def execute(self, targets, params, *, clock=None):
        self.call_count += 1
        return self._run


class TestSpeedTestComparisonUseCase:
    def test_skip_si_speedtest_unavailable(self) -> None:
        speed_test = FakeSpeedTestController(available=False)
        diag = _MockDiagnostics(_make_run("r1", [], 80))
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        params = SpeedTestComparisonParams(
            diagnostic_params=_make_params(),
            skip_if_speedtest_unavailable=True,
        )
        result = use_case.execute(_make_targets(), params)
        assert result.speed_test_controller_available is False
        assert result.overall_verdict == "unavailable"

    def test_raise_si_speedtest_unavailable_y_skip_false(self) -> None:
        speed_test = FakeSpeedTestController(available=False)
        diag = _MockDiagnostics(_make_run("r1", [], 80))
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        params = SpeedTestComparisonParams(
            diagnostic_params=_make_params(),
            skip_if_speedtest_unavailable=False,
        )
        with pytest.raises(SpeedTestError):
            use_case.execute(_make_targets(), params)

    def test_flujo_completo_con_deltas(self) -> None:
        """Corre diagnóstico + speed test, computa deltas."""
        run = _make_run(
            "r1",
            [_probe("local", "gateway", avg_ms=15.0, jitter=2.0)],
            score=85,
        )
        speed_result = _speed_test_result(
            latency_ms=20.0, download_mbps=100.0, upload_mbps=50.0
        )
        speed_test = FakeSpeedTestController(result=speed_result)
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        params = SpeedTestComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)

        assert result.speed_test_controller_available is True
        assert result.baseline is speed_result
        assert result.comparison is speed_result

        # Latencia delta: speed_test (20.0) - gateway (15.0) = +5.0
        lat_delta = result.get_delta("latency_ms")
        assert lat_delta is not None
        assert lat_delta.baseline_value == 15.0
        assert lat_delta.comparison_value == 20.0
        assert lat_delta.delta == 5.0

    def test_verdict_improved_con_score_alto(self) -> None:
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=90)
        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        assert result.overall_verdict == "improved"

    def test_verdict_degraded_con_score_bajo(self) -> None:
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=50)
        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        assert result.overall_verdict == "degraded"

    def test_verdict_neutral_con_score_medio(self) -> None:
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=70)
        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        assert result.overall_verdict == "neutral"

    # ── Tests de regresión: bugs visuales reportados por el usuario ──

    def test_bug1_score_alto_con_latencia_empeorada_es_degraded_no_improved(
        self,
    ) -> None:
        """REGRESIÓN bug 1: badge decía "IMPROVED" cuando la latencia del
        speed test estaba +684% peor vs gateway. La lógica vieja solo miraba
        `score>=80` → improved, ignorando los deltas de latencia/jitter/loss.

        Setup: gateway=15ms (diagnóstico OK, score=86, safe_to_play) pero
        speed test=120ms (delta=+105, delta_pct=+700%). El badge NO debe ser
        "improved" aunque el score del diagnóstico sea alto.

        Fix: si alguna métrica de red (latency/jitter/loss) empeora
        significativamente vs gateway, el veredicto es "degraded" sin
        importar el score absoluto. No se permite "improved" ciego.
        """
        run = _make_run(
            "r1",
            [_probe("local", "gateway", avg_ms=15.0, jitter=2.0)],
            score=86,
        )
        # Speed test: latencia +105ms vs gateway (15ms), delta_pct=+700%
        speed_result = _speed_test_result(
            latency_ms=120.0,  # gateway=15 → delta=+105 → empeoramiento brutal
        )
        speed_test = FakeSpeedTestController(result=speed_result)
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )

        # BUG ORIGINAL: esto devolvía "improved" porque score=86>=80,
        # ignorando que latencia empeoró +700%.
        assert (
            result.overall_verdict == "degraded"
        ), f"latencia +700% no puede ser 'improved' (got {result.overall_verdict})"
        # Verificamos que la explicación menciona la congestión
        joined = " | ".join(result.verdict_explanation)
        assert "latencia" in joined.lower()
        assert "congestión" in joined.lower() or "congesti" in joined.lower()

    def test_bug1_jitter_empeorado_previene_improved(
        self,
    ) -> None:
        """Cobertura adicional: jitter empeorado también previene 'improved'."""
        run = _make_run(
            "r1",
            [_probe("local", "gateway", avg_ms=10.0, jitter=2.0)],
            score=92,  # score muy alto
        )
        # Speed test: jitter=15ms cuando gateway jitter=2ms → delta=+13ms
        speed_result = SpeedTestResult(
            latency_ms=10.0,
            jitter_ms=15.0,  # gateway jitter=2 → delta=+13 → empeora
            download_mbps=100.0,
            upload_mbps=50.0,
            packet_loss_pct=0.0,
            server_name="X",
            server_country="Y",
            isp="Z",
        )
        speed_test = FakeSpeedTestController(result=speed_result)
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )

        # score=92 (mejor que el anterior) pero jitter empeoró: degradado.
        assert result.overall_verdict == "degraded"
        joined = " | ".join(result.verdict_explanation)
        assert "jitter" in joined.lower()

    def test_bug1_packet_loss_empeorado_previene_improved(
        self,
    ) -> None:
        """Cobertura adicional: packet loss empeorado previene 'improved'."""
        run = _make_run(
            "r1",
            [
                ProbeResult(
                    target_name="gateway",
                    target_ip="1.2.3.4",
                    provider="local",
                    outcome=ProbeOutcomeKind.SUCCESS,
                    stats=LatencyStats(
                        avg_ms=10.0,
                        min_ms=9.0,
                        max_ms=11.0,
                        jitter_ms=1.0,
                        packet_loss_pct=0.0,
                        samples=10,
                    ),
                    timestamp=datetime(2026, 1, 1),
                )
            ],
            score=95,
        )
        speed_result = SpeedTestResult(
            latency_ms=10.0,
            jitter_ms=1.0,
            download_mbps=100.0,
            upload_mbps=50.0,
            packet_loss_pct=2.5,  # gateway=0 → delta=+2.5pp → empeora
            server_name="X",
            server_country="Y",
            isp="Z",
        )
        speed_test = FakeSpeedTestController(result=speed_result)
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )

        assert result.overall_verdict == "degraded"
        joined = " | ".join(result.verdict_explanation)
        assert "loss" in joined.lower() or "packet" in joined.lower()

    def test_bug2_diagnostic_score_y_verdict_se_transportan_en_el_resultado(
        self,
    ) -> None:
        """REGRESIÓN bug 2: el template de la UI usaba `baseline.server_name`
        (nombre del servidor de speed test) donde debería ir el score numérico
        del diagnóstico. El `SpeedTestComparisonResult` ahora transporta
        `diagnostic_score` y `diagnostic_verdict` (seteados por el use case
        desde `run.recommendation`), así la UI puede mostrar
        `Diagnóstico: score=86/100, verdict=safe_to_play` en lugar de
        `score=Movistar`.

        Este test valida que el use case SI los transporta en el resultado
        (el test del template roto está en la section, ver
        `test_bug2_score_label_muestra_score_no_server_name`).
        """
        run = _make_run(
            "r1",
            [_probe("local", "gateway", avg_ms=15.0)],
            score=86,
        )
        # forzamos verdict distinto a default
        assert run.recommendation.verdict == "safe_to_play"  # score=86>=80

        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )

        assert result.diagnostic_score == 86
        assert result.diagnostic_verdict == "safe_to_play"

    def test_bug2_unavailable_path_no_pone_score_ni_verdict(
        self,
    ) -> None:
        """Caso unavailable: el resultado NO trae score/verdict del
        diagnóstico (no se corrió). Los campos deben ser None.
        """
        speed_test = FakeSpeedTestController(available=False)
        diag = _MockDiagnostics(_make_run("r1", [], 80))
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        params = SpeedTestComparisonParams(
            diagnostic_params=_make_params(),
            skip_if_speedtest_unavailable=True,
        )
        result = use_case.execute(_make_targets(), params)
        assert result.diagnostic_score is None
        assert result.diagnostic_verdict is None

    def test_speedtest_se_ejecuta_despues_del_diagnostico(self) -> None:
        """El speed test debe ejecutarse después del diagnóstico."""
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=85)
        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        # El diagnóstico se ejecutó primero, luego el speed test
        assert diag.call_count == 1
        assert speed_test.run_calls == 1

    def test_error_en_speedtest_se_propaga(self) -> None:
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=85)
        speed_test = FakeSpeedTestController(fail_on_run=True)
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        with pytest.raises(SpeedTestError):
            use_case.execute(
                _make_targets(),
                SpeedTestComparisonParams(diagnostic_params=_make_params()),
            )

    def test_deltas_de_download_upload(self) -> None:
        """Download/upload no tienen equivalente en diagnóstico."""
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=85)
        speed_test = FakeSpeedTestController(
            result=_speed_test_result(download_mbps=200.0, upload_mbps=100.0)
        )
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        download_delta = result.get_delta("download_mbps")
        assert download_delta is not None
        assert download_delta.baseline_value == 0.0
        assert download_delta.comparison_value == 200.0
        assert download_delta.delta_pct is None  # baseline es 0

    def test_durations_captured(self) -> None:
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=85)
        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        assert result.baseline_duration_ms is not None
        assert result.comparison_duration_ms is not None
        assert result.baseline_duration_ms > 0
        assert result.comparison_duration_ms > 0

    def test_explicacion_no_vacia(self) -> None:
        run = _make_run("r1", [_probe("local", "gateway", 15.0)], score=85)
        speed_test = FakeSpeedTestController(result=_speed_test_result())
        diag = _MockDiagnostics(run)
        use_case = SpeedTestComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            speed_test_controller=speed_test,
        )
        result = use_case.execute(
            _make_targets(), SpeedTestComparisonParams(diagnostic_params=_make_params())
        )
        assert len(result.verdict_explanation) > 0
