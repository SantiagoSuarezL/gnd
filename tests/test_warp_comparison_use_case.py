"""Tests del WarpComparisonUseCase (Fase 12b.4).

Cubrimos:
- Flujo completo: enable/disable WARP, ejecutar dos diagnósticos,
  restaurar estado original, computar deltas.
- Restauración del estado original al terminar.
- Comportamiento cuando WarpController no está disponible.
- Veredictos: improved, degraded, neutral.
- Cálculo de deltas por provider.
- Manejo de errores (WarpError desde enable/disable).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
)
from gnd.application.warp_comparison import (
    WarpComparisonParams,
    WarpComparisonUseCase,
)
from gnd.domain.fakes.fake_warp_controller import FakeWarpController
from gnd.domain.ports.warp_controller import WarpError
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation


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


class _MockDiagnostics:
    """Mock de RunFullDiagnostics que devuelve runs programables."""

    def __init__(self, runs: list) -> None:
        self._runs = list(runs)
        self._call_count = 0

    def execute(self, targets, params, *, clock=None):
        if self._call_count >= len(self._runs):
            raise RuntimeError("No more runs configured")
        run = self._runs[self._call_count]
        self._call_count += 1
        return run


class TestWarpComparisonUseCase:
    def test_skip_si_warp_controller_unavailable(self) -> None:
        warp = FakeWarpController(fail_on_status=True)
        diag = _MockDiagnostics([])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            skip_if_warp_unavailable=True,
        )
        result = use_case.execute(_make_targets(), params)
        assert result.warp_controller_available is False
        assert result.overall_verdict == "unavailable"

    def test_raise_si_warp_unavailable_y_skip_false(self) -> None:
        warp = FakeWarpController(fail_on_status=True)
        diag = _MockDiagnostics([])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            skip_if_warp_unavailable=False,
        )
        with pytest.raises(WarpError):
            use_case.execute(_make_targets(), params)

    def test_flujo_completo_con_deltas(self) -> None:
        """Corre dos diagnósticos (WARP off + on), restaura estado, computa deltas."""
        # WARP off: latencia alta (sin WARP, ruta directa)
        off_run = _make_run(
            "off123",
            [
                _probe("cloudflare", "cf", avg_ms=30.0),
                _probe("google", "goog", avg_ms=25.0),
            ],
            score=85,
        )
        # WARP on: latencia menor (WARP optimiza ruta)
        on_run = _make_run(
            "on456",
            [
                _probe("cloudflare", "cf", avg_ms=20.0),
                _probe("google", "goog", avg_ms=22.0),
            ],
            score=95,
        )

        warp = FakeWarpController(initially_connected=False, initially_registered=True)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            restore_original_state=True,
        )
        result = use_case.execute(_make_targets(), params)

        # Score mejoró (off=85, on=95)
        assert result.warp_off_score == 85
        assert result.warp_on_score == 95
        assert result.score_delta == 10  # on - off = positivo = mejor
        assert result.overall_verdict == "improved"

        # Cloudflare: 30 -> 20 (delta = -10, mejor)
        cf_deltas = result.provider_deltas["cloudflare"]
        lat_delta = next(d for d in cf_deltas if d.metric_name == "avg_latency_ms")
        assert lat_delta.warp_off_value == 30.0
        assert lat_delta.warp_on_value == 20.0
        assert lat_delta.delta == -10.0

    def test_restaura_estado_original_off(self) -> None:
        """Si WARP estaba OFF, debe quedar OFF al terminar."""
        warp = FakeWarpController(initially_connected=False, initially_registered=True)
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 85)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            restore_original_state=True,
        )
        use_case.execute(_make_targets(), params)
        # Al terminar, debe haber llamado enable() (para WARP ON)
        # y luego disable() (restore a OFF).
        assert warp.enable_calls == 1
        assert warp.disable_calls == 2  # una para WARP OFF run, otra para restore

    def test_restaura_estado_original_on(self) -> None:
        """Si WARP estaba ON, debe quedar ON al terminar."""
        warp = FakeWarpController(initially_connected=True, initially_registered=True)
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 85)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            restore_original_state=True,
        )
        use_case.execute(_make_targets(), params)
        # enable() ya estaba ON, disable() para OFF run, enable() para ON run,
        # enable() para restore a ON.
        assert warp.enable_calls == 2
        assert warp.disable_calls == 1

    def test_no_restaura_si_restore_false(self) -> None:
        warp = FakeWarpController(initially_connected=False, initially_registered=True)
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 85)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            restore_original_state=False,
        )
        use_case.execute(_make_targets(), params)
        # Solo enable (ON) + disable (OFF) para los runs, sin restore.
        assert warp.enable_calls == 1
        assert warp.disable_calls == 1

    def test_verdict_degraded_cuando_warp_empeora(self) -> None:
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 20.0)], 95)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 40.0)], 60)
        warp = FakeWarpController()
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)
        assert result.score_delta < 0  # score bajó con WARP (peor)
        assert result.overall_verdict == "degraded"

    def test_verdict_neutral_con_cambio_menor(self) -> None:
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run(
            "r2", [_probe("cloudflare", "cf", 30.5)], 79
        )  # cambio de 1 punto
        warp = FakeWarpController()
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)
        assert result.overall_verdict == "neutral"

    def test_solo_providers_en_ambas_corridas(self) -> None:
        """Un provider que solo aparece en una corrida no genera deltas."""
        off_run = _make_run(
            "r1",
            [_probe("cloudflare", "cf", 30.0), _probe("google", "goog", 25.0)],
            80,
        )
        on_run = _make_run(
            "r2",
            [_probe("cloudflare", "cf", 25.0)],  # sin google
            85,
        )
        warp = FakeWarpController()
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)
        assert "google" not in result.provider_deltas
        assert "cloudflare" in result.provider_deltas

    def test_run_ids_correctos(self) -> None:
        off_run = _make_run("off_abc", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run("on_xyz", [_probe("cloudflare", "cf", 25.0)], 85)
        warp = FakeWarpController()
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)
        assert result.warp_off_run_id == "off_abc"
        assert result.warp_on_run_id == "on_xyz"

    def test_durations_captured(self) -> None:
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 85)
        warp = FakeWarpController()
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)
        assert result.warp_off_duration_ms is not None
        assert result.warp_on_duration_ms is not None
        assert result.warp_off_duration_ms > 0
        assert result.warp_on_duration_ms > 0

    def test_restore_failure_no_propagates(self) -> None:
        """Si el restore falla, no debe propagar la excepción."""
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 80)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 85)
        warp = FakeWarpController(initially_connected=False)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )

        # Llamamos _restore_original_state directamente para testear el
        # manejo de errores sin enredar el flujo completo.
        # Original conectado=True, así que va a llamar enable().
        # Si enable() lanza WarpError, _restore_original_state debe capturarla.
        from gnd.domain.ports.warp_controller import WarpStatus

        original_connected = WarpStatus(
            connected=True,
            registration_status="registered",
            connection_status="connected",
            warp_plus=False,
        )
        warp.set_fail_on_enable(True)
        # No debe lanzar — capturada y logueada
        use_case._restore_original_state(original_connected)  # noqa: SLF001
