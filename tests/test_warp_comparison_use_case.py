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

from collections.abc import Callable
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
from gnd.domain.ports.warp_controller import WarpError, WarpStatus
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
        """Si WARP estaba ON (con modo/protocolo detectados), debe quedar ON
        al terminar — restaurando vía set_mode + set_tunnel_protocol +
        enable (Regla 12b.4.2)."""
        warp = FakeWarpController(
            initially_connected=True,
            initially_registered=True,
            mode="warp",
            tunnel_protocol="WireGuard",
        )
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
        # enable() para ON run, enable() para restore a ON (restore es
        # set_mode + set_protocol + enable). disable() solo para OFF run.
        assert warp.enable_calls == 2
        assert warp.disable_calls == 1
        assert warp.set_mode_calls == ["warp"]
        assert warp.set_tunnel_protocol_calls == ["WireGuard"]

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
        # Original conectado=True con mode+protocolo conocidos (regresa la
        # rama del restore que replica). Si enable() lanza WarpError, debe
        # capturarse y no propagarse (bug pre-existente cubierto por 12b.4).
        from gnd.domain.ports.warp_controller import WarpStatus

        original_connected = WarpStatus(
            connected=True,
            registration_status="registered",
            connection_status="connected",
            warp_plus=False,
            mode="warp",
            tunnel_protocol="WireGuard",
        )
        warp.set_fail_on_enable(True)
        # No debe lanzar — capturada y logueada
        use_case._restore_original_state(original_connected)  # noqa: SLF001

    # --- Regla 12b.4.2: restore fiel de modo/protocolo + fail-safe ---

    def test_restore_replica_protocolo_wireguard_si_estaba_en_udp(self) -> None:
        """Reproduce el escenario real del usuario: WARP prendido en modo
        "UDP" (=WireGuard) antes de correr la comparación. El restore debe
        setear el protocolo de vuelta a WireGuard (NO a MASQUE default) y
        luego enable(). Regla 12b.4.2."""
        warp = FakeWarpController(
            initially_connected=True,
            initially_registered=True,
            mode="warp",
            tunnel_protocol="WireGuard",
        )
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

        # Flujo: disable (off run) + enable (on run) + restore:
        #   restore llama set_mode("warp") + set_tunnel_protocol("WireGuard")
        #   + enable().
        assert warp.enable_calls == 2  # ON run + restore
        assert warp.disable_calls == 1  # OFF run
        assert warp.set_mode_calls == ["warp"]
        assert warp.set_tunnel_protocol_calls == ["WireGuard"]

    def test_restore_no_replica_modo_si_protocolo_none_fail_safe(self) -> None:
        """Fail-safe: si el adapter no detectó el protocolo (None), el
        restore NO llama a enable() ciego (lo dejaría en MASQUE default
        perdiendo el modo elegido). En su lugar disable() + log
        `restore_skip_mode_unknown`. El usuario prende a mano."""
        warp = FakeWarpController(
            initially_connected=True,
            initially_registered=True,
            mode="warp",
            tunnel_protocol=None,  # simula falla de parseo en settings list
        )
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

        # Flujo: disable (off run) + enable (on run) + restore fail-safe:
        #   NO set_mode, NO set_protocol, NO enable. Solo disable() para
        #   dejar WARP apagado (el usuario lo prende a mano en su modo).
        assert warp.enable_calls == 1  # solo ON run
        assert warp.disable_calls == 2  # OFF run + restore fail-safe
        assert warp.set_mode_calls == []
        assert warp.set_tunnel_protocol_calls == []

    def test_restore_no_replica_modo_si_mode_none_fail_safe(self) -> None:
        """Fail-safe simétrico: si mode=None (aunque protocolo detectado),
        el restore también entra a fail-safe — no se puede restaurar el
        modo completo solo con protocol."""
        warp = FakeWarpController(
            initially_connected=True,
            initially_registered=True,
            mode=None,  # simula falla de parseo de `Mode: <x>`
            tunnel_protocol="WireGuard",
        )
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
        assert warp.enable_calls == 1
        assert warp.disable_calls == 2
        assert warp.set_mode_calls == []
        assert warp.set_tunnel_protocol_calls == []


# --- Regla 12b.4.4 (race fix): poll de status con timeout ---


class _FakeSleeper:
    """Sleeper determinista para tests del poll de status."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class _ProgrammableTransitionSleeper(_FakeSleeper):
    """Sleeper que llama a una función en cada poll para transicionar.

    Args:
        on_sleep: callable(seconds, sleep_index) que se ejecuta en cada
            sleep. Útil para setear el estado del warp controller.
    """

    def __init__(self, on_sleep: Callable[[float, int], None]) -> None:
        super().__init__()
        self._on_sleep = on_sleep
        self._idx = 0

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._on_sleep(seconds, self._idx)
        self._idx += 1


class _FakePerfClock:
    """Clock fake que avanza simuladamente (Regla 12b.4.4).

    Por defecto avanza 1s por llamada (== poll_interval_s típico). Tests
    pueden sobreescribir ``advance_per_call`` para simular transiciones
    rápidas/lentas.
    """

    def __init__(self, advance_per_call: float = 1.0) -> None:
        self._now = 0.0
        self._advance = advance_per_call
        self._override_advance: float | None = None

    def set_advance(self, seconds: float) -> None:
        self._advance = seconds

    def set_next_advance(self, seconds: float) -> None:
        self._override_advance = seconds

    def __call__(self) -> float:
        delta = (
            self._override_advance
            if self._override_advance is not None
            else self._advance
        )
        self._override_advance = None
        self._now += delta
        return self._now


class _ProgrammableStatusWarpController:
    """Fake WarpController con estado mutable para tests del poll.

    En vez de una secuencia pre-programada, expone ``set_state()`` para
    setear connection_status en cualquier momento. Las llamadas a
    get_status/enable/disable reflejan el estado actual. Tests pueden
    simular transiciones llamando set_state() antes de los polls.
    """

    def __init__(self, *, initially_connected: bool = False) -> None:
        self._connection_status = "connected" if initially_connected else "disconnected"
        self._mode = "warp"
        self._tunnel_protocol = "WireGuard"
        self.enable_calls = 0
        self.disable_calls = 0
        self.status_calls = 0

    def set_state(self, connection_status: str) -> None:
        """Cambia el connection_status que devuelven los próximos status calls."""
        self._connection_status = connection_status

    def _current_status(self) -> WarpStatus:
        return WarpStatus(
            connected=(self._connection_status == "connected"),
            registration_status="registered",
            connection_status=self._connection_status,
            warp_plus=False,
            mode=self._mode,
            tunnel_protocol=self._tunnel_protocol,
        )

    def get_status(self) -> WarpStatus:
        self.status_calls += 1
        return self._current_status()

    def enable(self) -> WarpStatus:
        self.enable_calls += 1
        return self._current_status()

    def disable(self) -> WarpStatus:
        self.disable_calls += 1
        return self._current_status()

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_tunnel_protocol(self, protocol: str) -> None:
        self._tunnel_protocol = protocol

    @property
    def available(self) -> bool:
        return True


class _StatefulWarpController(_ProgrammableStatusWarpController):
    """Variante que transiciona a un estado objetivo en el próximo poll.

    ``target_on_poll = "connected" | "disconnected"``: cuando el sleeper
    es llamado (significa que hubo un poll sin match), transiciona el
    estado a ``target_on_poll`` después del primer sleep. Útil para
    simular que el daemon transiciona tras el primer poll.
    """

    def __init__(
        self,
        *,
        initially_connected: bool,
        target_on_poll: str | None,
    ) -> None:
        super().__init__(initially_connected=initially_connected)
        self._target_on_poll = target_on_poll
        self._poll_count = 0

    def transition_after_first_poll(self) -> None:
        """Llamar desde el sleeper después del primer sleep del poll."""
        if self._poll_count == 0:
            if self._target_on_poll is not None:
                self.set_state(self._target_on_poll)
        self._poll_count += 1


class TestWarpStatePolling:
    def test_enable_espera_connected_antes_de_ejecutar_diag(self) -> None:
        """Regla 12b.4.4: tras enable(), el poll de status debe confirmar
        'connected' antes de arrancar el diagnóstico. Bug pre-fix: el
        use case arrancaba con time.sleep(1.0) ciego y si el daemon
        estaba en 'connecting', pings/DNS fallaban reportando timeouts
        falsos (red rota cuando en realidad era estado intermedio)."""
        warp = _ProgrammableStatusWarpController(initially_connected=False)
        # Tras el primer sleep, simular que el daemon transiciona a connected.
        sleeper = _ProgrammableTransitionSleeper(
            on_sleep=lambda _s, idx: warp.set_state("connected") if idx == 0 else None
        )
        clock = _FakePerfClock(advance_per_call=0.5)

        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 70)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 90)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,  # type: ignore[arg-type]
            sleeper=sleeper,
            perf_clock=clock,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            enable_timeout_s=5.0,
            disable_timeout_s=5.0,
            poll_interval_s=0.5,
        )
        result = use_case.execute(_make_targets(), params)

        assert result.overall_verdict == "improved"
        assert len(sleeper.sleeps) >= 1
        assert sleeper.sleeps[0] == 0.5

    def test_enable_timeout_aborta_con_state_timeout(self) -> None:
        """Si el daemon no alcanza 'connected' en enable_timeout_s, abortar
        con overall_verdict='state_timeout' (NO continuar midiendo contra
        red rota). Bug pre-fix: avanzaba con sleep ciego y reportaba
        timeouts/DNS failed como resultados válidos."""
        warp = _ProgrammableStatusWarpController(initially_connected=False)

        # Disable succeeds immediately (was disconnected). Tras disable
        # exitoso, simulamos que enable queda stuck en 'connecting'.
        # Para esto, el sleeper transiciona a 'connecting' en el primer
        # poll de disable (así disable matchea, queda disconnected) y luego
        # el enable nunca alcanza 'connected'.
        def on_sleep(_seconds: float, idx: int) -> None:
            if idx == 0:
                # First sleep is during disable poll — already disconnected
                # after disable, no transition needed.
                pass
            elif idx == 1:
                # Second sleep is during enable poll — simular daemon stuck.
                warp.set_state("connecting")

        sleeper = _ProgrammableTransitionSleeper(on_sleep=on_sleep)
        clock = _FakePerfClock(advance_per_call=0.5)
        # OFF run debe existir (OFF phase debe completarse antes del OFF
        # timeout). ON phase nunca debe correr.
        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 70)
        diag = _MockDiagnostics([off_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,  # type: ignore[arg-type]
            sleeper=sleeper,
            perf_clock=clock,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            enable_timeout_s=1.0,
            disable_timeout_s=5.0,
            poll_interval_s=0.5,
        )
        result = use_case.execute(_make_targets(), params)

        assert result.overall_verdict == "state_timeout"
        assert "WARP no alcanzó estado 'connected'" in result.verdict_explanation[0]
        # OFF diag corrió (consume off_run), pero ON diag nunca (abort antes).
        assert diag._call_count == 1
        # Restore: disable se llamó igual para dejar WARP apagado.
        assert warp.disable_calls >= 1

    def test_disable_espera_disconnected(self) -> None:
        """Análogo a enable pero para disable: debe esperar 'disconnected'
        antes de arrancar el diag WARP OFF."""
        warp = _ProgrammableStatusWarpController(initially_connected=True)

        # Tras el primer sleep del poll post-disable, transicionar a disconnected.
        # El segundo poll (post-enable) necesita transicionar a connected,
        # así que diferenciamos por sleep_index.
        def on_sleep(_seconds: float, idx: int) -> None:
            if idx == 0:
                warp.set_state("disconnected")
            elif idx == 1:
                warp.set_state("connected")

        sleeper = _ProgrammableTransitionSleeper(on_sleep=on_sleep)
        clock = _FakePerfClock(advance_per_call=0.5)

        off_run = _make_run("r1", [_probe("cloudflare", "cf", 30.0)], 70)
        on_run = _make_run("r2", [_probe("cloudflare", "cf", 25.0)], 90)
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,  # type: ignore[arg-type]
            sleeper=sleeper,
            perf_clock=clock,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            enable_timeout_s=5.0,
            disable_timeout_s=5.0,
            poll_interval_s=0.5,
        )
        result = use_case.execute(_make_targets(), params)
        assert result.overall_verdict == "improved"

    def test_disable_timeout_aborta_con_state_timeout(self) -> None:
        warp = _ProgrammableStatusWarpController(initially_connected=True)
        # Stays in 'connected' forever — polls never see 'disconnected'.
        sleeper = _FakeSleeper()
        clock = _FakePerfClock(advance_per_call=0.5)
        diag = _MockDiagnostics([])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,  # type: ignore[arg-type]
            sleeper=sleeper,
            perf_clock=clock,
        )
        params = WarpComparisonParams(
            diagnostic_params=_make_params(),
            disable_timeout_s=1.0,
            poll_interval_s=0.5,
        )
        result = use_case.execute(_make_targets(), params)
        assert result.overall_verdict == "state_timeout"


# --- Regla 12b.4.5 (bug 2 fix): providers con medición fallida ---


def _failed_probe(provider: str, target: str) -> ProbeResult:
    """Probe con outcome non-SUCCESS (sin stats, Regla 4.1 + invariante modelo)."""
    return ProbeResult(
        target_name=target,
        target_ip="1.2.3.4",
        provider=provider,
        outcome=ProbeOutcomeKind.TIMEOUT,
        stats=None,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )


class TestWarpComparisonFailedProviders:
    def test_provider_falla_en_on_run_no_se_cuenta_como_mejora(self) -> None:
        """Bug 2 (pre-fix): provider con probe SUCCESS en off (avg=30ms)
        y probe TIMEOUT en on (avg=0.0) generaba delta=-30 con -100%
        'mejora perfecta'. Regla 12b.4.5: probe non-SUCCESS se EXCLUYE,
        lado on se marca None, status='failed_on', delta=None. La UI
        muestra '-' y 'FAILED' en la celda status."""
        off_run = _make_run(
            "r1",
            [
                _probe("cloudflare", "cf", 30.0),
                _probe("gateway", "gw", 5.0),
            ],
            score=85,
        )
        # cloudflare falla (TIMEOUT) bajo WARP on, gateway OK
        on_run = _make_run(
            "r2",
            [
                _failed_probe("cloudflare", "cf"),
                _probe("gateway", "gw", 4.0),
            ],
            score=90,
        )
        warp = FakeWarpController(mode="warp", tunnel_protocol="WireGuard")
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)

        cf_deltas = result.provider_deltas["cloudflare"]
        lat = next(d for d in cf_deltas if d.metric_name == "avg_latency_ms")
        assert lat.warp_off_value == 30.0
        assert lat.warp_on_value is None
        assert lat.delta is None
        assert lat.delta_pct is None
        assert lat.status == "failed_on"

        gw_deltas = result.provider_deltas["gateway"]
        gw_lat = next(d for d in gw_deltas if d.metric_name == "avg_latency_ms")
        assert gw_lat.warp_off_value == 5.0
        assert gw_lat.warp_on_value == 4.0
        assert gw_lat.delta == -1.0
        assert gw_lat.status == "ok"

        explanation_text = " ".join(result.verdict_explanation)
        assert "Mejora latencia en: cloudflare" not in explanation_text
        assert "Medición fallida" in explanation_text
        assert "cloudflare" in explanation_text

    def test_provider_falla_en_ambas_corridas_no_contamina_verdict(self) -> None:
        """Si un provider falla en AMBAS corridas, se excluye del veredicto
        y se lista en failed providers. No se computa delta porque no hay
        puntos."""
        off_run = _make_run(
            "r1",
            [
                _failed_probe("riot_public", "auth.riotgames.com"),
                _probe("gateway", "gw", 5.0),
            ],
            score=85,
        )
        on_run = _make_run(
            "r2",
            [
                _failed_probe("riot_public", "auth.riotgames.com"),
                _probe("gateway", "gw", 4.0),
            ],
            score=90,
        )
        warp = FakeWarpController(mode="warp", tunnel_protocol="WireGuard")
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)

        riot_deltas = result.provider_deltas["riot_public"]
        lat = next(d for d in riot_deltas if d.metric_name == "avg_latency_ms")
        assert lat.warp_off_value is None
        assert lat.warp_on_value is None
        assert lat.delta is None
        assert lat.status == "failed_both"

        explanation_text = " ".join(result.verdict_explanation)
        assert "Medición fallida" in explanation_text
        assert "riot_public" in explanation_text

    def test_provider_falla_solo_en_off(self) -> None:
        """Caso inverso: provider falla solo en off_run. La tabla muestra
        status='failed_off' y el lado on se computa normal."""
        off_run = _make_run(
            "r1",
            [_failed_probe("cloudflare", "cf")],
            score=80,
        )
        on_run = _make_run(
            "r2",
            [_probe("cloudflare", "cf", 25.0)],
            score=85,
        )
        warp = FakeWarpController(mode="warp", tunnel_protocol="WireGuard")
        diag = _MockDiagnostics([off_run, on_run])
        use_case = WarpComparisonUseCase(
            diagnostics_use_case=diag,  # type: ignore[arg-type]
            warp_controller=warp,
        )
        params = WarpComparisonParams(diagnostic_params=_make_params())
        result = use_case.execute(_make_targets(), params)

        cf_deltas = result.provider_deltas["cloudflare"]
        lat = next(d for d in cf_deltas if d.metric_name == "avg_latency_ms")
        assert lat.warp_off_value is None
        assert lat.warp_on_value == 25.0
        assert lat.delta is None
        assert lat.delta_pct is None
        assert lat.status == "failed_off"
