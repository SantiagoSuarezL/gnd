"""Tests unitarios del orquestador ``monitoring.route_monitor.RouteMonitor``.

Sin red, sin subprocess, sin reloj (EP §4). Usa:
- ``FakeTracerouteRunner`` ya existente (Fase 1) para devolver
  ``TracerouteResult`` controlados por test.
- ``FakeSleeper`` + ``FakeMonotonic`` para simular ``time.sleep`` + ``time.monotonic``.
- ``FakeClock`` (devuelve timestamps predecibles para assertions).

Cubre:
- Liskov: RouteMonitor cumple ``Protocol RouteMonitor``.
- Logica de cuenta de muestras dinamica (wall-clock duration_s).
- Flujo end-to-end del monitor: N tomas -> N muestras -> HopStats.
- Manejo de TracerouteResult vacio (placeholder hop 1 responded=False).
- Identidad de intervalos / duracion / timestamps.
- Sample_index incremental.
- Variabilidad de IPs por hop (ELASTIC CASE) -> HopStats.ip es la moda.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from gnd.domain.fakes.fake_traceroute_runner import FakeTracerouteRunner
from gnd.domain.ports.route_monitor import RouteMonitor
from gnd.models.traceroute import TracerouteHop, TracerouteResult
from gnd.monitoring.route_monitor import RouteMonitor as RealRouteMonitor

# --------------------------------------------------------------------------- #
# Helpers de DI
# --------------------------------------------------------------------------- #


class FakeMonotonic:
    """Simula ``time.monotonic()`` para tests.

    Devuelve el mismo valor hasta que se llama ``advance()``.
    """

    def __init__(self, t0: float = 0.0) -> None:
        self.value = t0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeSleeper:
    def __init__(self, monotonic: FakeMonotonic) -> None:
        self._monotonic = monotonic
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self._monotonic.advance(seconds)


def _patch_monotonic(monotonic: FakeMonotonic):
    """Context manager para parchar ``time.monotonic`` con un ``FakeMonotonic``."""
    return patch("time.monotonic", monotonic)


class FakeClock:
    """Clock que incrementa cada vez que se llama.

    Empezamos en t0 (default 2000-01-01) y cada llamado suma ``step_s``
    segundos. Default step = 1ms. Suficiente para que finished_at >
    started_at siempre (invariante del modelo).
    """

    def __init__(
        self,
        *,
        t0: datetime | None = None,
        step_s: float = 0.001,
    ) -> None:
        self.t0 = t0 or datetime(2026, 7, 25, 12, 0, 0)
        self.step = timedelta(seconds=step_s)
        self.n_calls = 0

    def __call__(self) -> datetime:
        v = self.t0 + (self.step * self.n_calls)
        self.n_calls += 1
        return v


class RotatingTracerouteRunner:
    """Runner que devuelve resultados pre-configurados en secuencia.

    Cada llamada a ``traceroute()`` devuelve el siguiente resultado en
    la lista. Permite tests donde cada "toma" del monitor recibe un
    TracerouteResult distinto (variabilidad de IPs, mezcla de timeouts).
    """

    def __init__(self, results: list[TracerouteResult]) -> None:
        self._results = results
        self.calls: list[dict] = []
        self._i = 0

    def traceroute(
        self,
        *,
        target_ip: str,
        target_provider: str,
        max_hops: int,
        timeout_ms: int,
    ) -> TracerouteResult:
        self.calls.append(
            {
                "target_ip": target_ip,
                "target_provider": target_provider,
                "max_hops": max_hops,
                "timeout_ms": timeout_ms,
                "take_index": self._i,
            }
        )
        if self._i >= len(self._results):
            raise IndexError(
                f"RotatingTracerouteRunner ran out: i={self._i} "
                f"len={len(self._results)}"
            )
        r = self._results[self._i]
        self._i += 1
        return r


class TimedTracerouteRunner:
    """Wrapper que avanza ``time.monotonic()`` en cada llamada a traceroute.

    Permite tests deterministas de la logica de interval/duration sin
    depender de auto_advance impreciso.
    """

    def __init__(
        self,
        inner: FakeTracerouteRunner | RotatingTracerouteRunner,
        monotonic: FakeMonotonic,
        advance_per_call: float = 1.0,
    ) -> None:
        self._inner = inner
        self._monotonic = monotonic
        self._advance = advance_per_call

    def traceroute(
        self,
        *,
        target_ip: str,
        target_provider: str,
        max_hops: int,
        timeout_ms: int,
    ) -> TracerouteResult:
        result = self._inner.traceroute(
            target_ip=target_ip,
            target_provider=target_provider,
            max_hops=max_hops,
            timeout_ms=timeout_ms,
        )
        # Avanzar el reloj DESPUÉS de la llamada para simular el tiempo
        # que tarda el traceroute en ejecutarse
        self._monotonic.advance(self._advance)
        return result


# --------------------------------------------------------------------------- #
# Liskov
# --------------------------------------------------------------------------- #


def test_route_monitor_implements_protocol():
    monitor = RealRouteMonitor(traceroute_runner=FakeTracerouteRunner())
    assert isinstance(monitor, RouteMonitor)


# --------------------------------------------------------------------------- #
# Cuenta de muestras dinamica (wall-clock duration_s)
# --------------------------------------------------------------------------- #


class TestSampleCountLogic:
    def test_cuatro_tomas_interval_2s_duracion_8s(self):
        """interval=2s, duration=8s -> 4 tomas (t=0,2,4,6). La 5ta seria en t=8 que es >= duration."""
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        base_runner = FakeTracerouteRunner()
        base_runner.set_default_result(_make_sample_tracert())
        # Avanza 1s por llamada (traceroute tarda 1s, interval=2s -> 1s de sleep)
        runner = TimedTracerouteRunner(base_runner, mono, advance_per_call=1.0)

        with _patch_monotonic(mono):
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=2.0,
                duration_s=8.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # 4 tomas * 2 hops = 8 samples
            assert len(session.samples) == 8
            assert [s.sample_index for s in session.samples] == [0, 0, 1, 1, 2, 2, 3, 3]
            # 3 sleeps entre 4 tomas (cada sleep = 1s = interval 2s - traceroute 1s)
            assert sleeper.calls == [1.0, 1.0, 1.0]

    def test_tres_tomas_interval_1s_duracion_3s(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        base_runner = FakeTracerouteRunner()
        base_runner.set_default_result(_make_sample_tracert())
        # Avanza 0.5s por llamada -> 3 tomas en 3s con interval=1
        runner = TimedTracerouteRunner(base_runner, mono, advance_per_call=0.5)

        with _patch_monotonic(mono):
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=3.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # 3 tomas * 2 hops = 6 samples
            assert len(session.samples) == 6
            assert [s.sample_index for s in session.samples] == [0, 0, 1, 1, 2, 2]
            # 2 sleeps entre 3 tomas (cada sleep = 0.5s = interval 1s - traceroute 0.5s)
            assert sleeper.calls == [0.5, 0.5]

    def test_una_sola_toma_si_duracion_menor_que_intervalo(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        base_runner = FakeTracerouteRunner()
        base_runner.set_default_result(_make_sample_tracert())
        runner = TimedTracerouteRunner(base_runner, mono, advance_per_call=10.0)

        with _patch_monotonic(mono):
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=10.0,
                duration_s=5.0,
                max_hops=30,
                timeout_ms=1000,
            )
            assert len(session.samples) == 2  # 1 toma * 2 hops
            assert sleeper.calls == []

    def test_interval_cero_o_negativo_default_a_1s_no_sleep_infinito(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        base_runner = FakeTracerouteRunner()
        base_runner.set_default_result(_make_sample_tracert())
        # Avanza 0.5s por llamada -> 5 tomas en 5s con interval=1
        runner = TimedTracerouteRunner(base_runner, mono, advance_per_call=0.5)

        with _patch_monotonic(mono):
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            # interval=0, duration=5 -> se comporta como interval=1
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=0.0,
                duration_s=5.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # Con interval=1s y duration=5s, trazador tarda 0.5s:
            # Take 0 en t=0, termina 0.5
            # Take 1 en t=1, termina 1.5
            # Take 2 en t=2, termina 2.5
            # Take 3 en t=3, termina 3.5
            # Take 4 en t=4, termina 4.5
            # Take 5 en t=5 -> next_take_at=5 >= duration=5 -> break SIN hacer la toma
            # 5 tomas * 2 hops = 10 samples
            assert len(session.samples) == 10
            # 4 sleeps de 0.5s cada uno (entre tomas 0-1, 1-2, 2-3, 3-4)
            assert sleeper.calls == [0.5, 0.5, 0.5, 0.5]

    def test_duration_cero_devuelve_una_sola_toma(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        base_runner = FakeTracerouteRunner()
        base_runner.set_default_result(_make_sample_tracert())
        runner = TimedTracerouteRunner(base_runner, mono, advance_per_call=1.0)

        with _patch_monotonic(mono):
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=0.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # duration=0 -> 1 toma
            assert len(session.samples) == 2
            assert sleeper.calls == []

    def test_toma_lenta_no_espera_extra_si_paso_intervalo(self):
        """Si una toma tarda mas que interval_s, el monitor no duerme extra."""
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        base_runner = FakeTracerouteRunner()
        base_runner.set_default_result(_make_sample_tracert())
        # Avanza 2s por llamada -> cada toma "tarda" 2s
        runner = TimedTracerouteRunner(base_runner, mono, advance_per_call=2.0)

        with _patch_monotonic(mono):
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            # interval=1s, duration=10s, pero cada toma "tarda" 2s
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=10.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # interval=1s, duration=10s, trazador tarda 2s -> 5 tomas (t=0,2,4,6,8)
            # siguiente seria t=10 >= duration=10 -> break
            # 5 tomas * 2 hops = 10 samples
            assert len(session.samples) == 10
            # 4 sleeps entre 5 tomas, pero elapsed_this_take=2s > interval=1s -> sleep_s <= 0
            assert sleeper.calls == []


# --------------------------------------------------------------------------- #
# Llamadas y flujo completo
# --------------------------------------------------------------------------- #


def _make_sample_tracert() -> TracerouteResult:
    """TracerouteResult estable de 2 hops, igual en cada take."""
    return TracerouteResult(
        target_provider="test",
        hops=[
            TracerouteHop(
                hop_number=1,
                ip="192.168.0.1",
                hostname=None,
                rtt_ms=2.0,
                responded=True,
            ),
            TracerouteHop(
                hop_number=2,
                ip="8.8.8.8",
                hostname=None,
                rtt_ms=18.0,
                responded=True,
            ),
        ],
        culprit_hop_index=1,
    )


class TestMonitorFlow:
    def test_cuatro_tomas_produce_cuatro_samples_por_hop(self):
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = FakeTracerouteRunner()
            runner.set_default_result(_make_sample_tracert())
            mono = FakeMonotonic()
            sleeper = FakeSleeper(mono)
            clock = FakeClock()

            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="run-1",
                interval_s=2.0,
                duration_s=8.0,
                max_hops=30,
                timeout_ms=1000,
            )

            # duration=8, interval=2 -> 4 tomas, 2 hops cada una = 8 muestras
            assert len(session.samples) == 8
            assert [s.sample_index for s in session.samples] == [0, 0, 1, 1, 2, 2, 3, 3]
            assert len(runner.calls) == 4

    def test_sleeper_se_llama_entre_tomas_no_antes_de_la_primera(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        with _patch_monotonic(mono):
            runner = FakeTracerouteRunner()
            runner.set_default_result(_make_sample_tracert())

            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=3.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # duration=3, interval=1 -> 3 tomas -> 2 sleeps entre medias
            assert sleeper.calls == [1.0, 1.0]

    def test_una_sola_toma_no_duerme(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        with _patch_monotonic(mono):
            runner = FakeTracerouteRunner()
            runner.set_default_result(_make_sample_tracert())

            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=10.0,
                duration_s=10.0,
                max_hops=30,
                timeout_ms=1000,
            )
            assert len(sleeper.calls) == 0

    def test_session_campos_se_propagan(self):
        mono = FakeMonotonic()
        sleeper = FakeSleeper(mono)
        clock = FakeClock()

        with _patch_monotonic(mono):
            runner = FakeTracerouteRunner()
            runner.set_default_result(_make_sample_tracert())
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=sleeper,
                clock=clock,
            )
            session = monitor.monitor(
                target_ip="9.9.9.9",
                target_provider="quad9",
                run_id="run-X",
                interval_s=1.0,
                duration_s=2.0,
                max_hops=15,
                timeout_ms=500,
            )
            assert session.run_id == "run-X"
            assert session.target_ip == "9.9.9.9"
            assert session.target_provider == "quad9"
            assert session.interval_s == 1.0

    def test_hop_stats_se_calculan_para_cada_hop(self):
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = FakeTracerouteRunner()
            runner.set_default_result(_make_sample_tracert())
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=FakeSleeper(FakeMonotonic()),
                clock=FakeClock(),
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=4.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # 4 tomas identicas -> hop 1 y hop 2 con los mismos rtts en cada una.
            assert len(session.hop_stats) == 2
            h1 = session.hop_stats[0]
            h2 = session.hop_stats[1]
            assert h1.hop_number == 1
            assert h2.hop_number == 2
            # best=worst=avg en tomas identicas -> jitter=0
            assert h1.best_ms == 2.0
            assert h1.worst_ms == 2.0
            assert h1.avg_ms == 2.0
            assert h1.jitter_ms == 0.0
            assert h1.loss_pct == 0.0
            assert h1.samples == 4

    def test_moda_ip_se_propaga_a_hop_stats(self):
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = FakeTracerouteRunner()
            runner.set_default_result(_make_sample_tracert())
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=FakeSleeper(FakeMonotonic()),
                clock=FakeClock(),
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=3.0,
                max_hops=30,
                timeout_ms=1000,
            )
            h1 = session.hop_stats[0]
            h2 = session.hop_stats[1]
            assert h1.ip == "192.168.0.1"
            assert h2.ip == "8.8.8.8"


# --------------------------------------------------------------------------- #
# Variabilidad: ECMP (IPs distintos entre muestras para mismo hop_number)
# --------------------------------------------------------------------------- #


class TestRouteMonitorIPElasticity:
    def test_ecmp_diferentes_ips_hopnumber_estable_agrega_bien(self):
        """Cada toma el hop 2 tiene IP distinta. Agregacion por hop_number
        metrica correcta; la HopStats.ip es la moda."""
        # take results: hop 2 rota IPs, hop 1 estable.
        ips = ["10.0.0.1", "10.0.0.2", "10.0.0.1"]  # 10.0.0.1 aparece 2 veces
        take_results = [
            TracerouteResult(
                target_provider="test",
                hops=[
                    TracerouteHop(1, "192.168.0.1", None, 2.0, True),
                    TracerouteHop(2, ips[i], None, 18.0, True),
                ],
                culprit_hop_index=1,
            )
            for i in range(3)
        ]
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = RotatingTracerouteRunner(take_results)
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=FakeSleeper(FakeMonotonic()),
                clock=FakeClock(),
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=3.0,
                max_hops=30,
                timeout_ms=1000,
            )
            h2 = session.hop_stats[1]
            assert h2.hop_number == 2
            assert h2.samples == 3
            # La moda: "10.0.0.1" aparece 2 veces -> es la moda.
            assert h2.ip == "10.0.0.1"
            # Latencias constantes -> jitter 0
            assert h2.jitter_ms == 0.0
            assert h2.avg_ms == 18.0


# --------------------------------------------------------------------------- #
# Traceroute result vacio (sin ruta)
# --------------------------------------------------------------------------- #


class TestMonitorEmptyTraceroutes:
    def test_un_placeholder_respondido_false_registra_loss(self):
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = FakeTracerouteRunner()
            empty_result = TracerouteResult(
                target_provider="test",
                hops=[
                    TracerouteHop(
                        hop_number=1,
                        ip=None,
                        hostname=None,
                        rtt_ms=None,
                        responded=False,
                    ),
                ],
                culprit_hop_index=None,
            )
            runner.set_default_result(empty_result)
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=FakeSleeper(FakeMonotonic()),
                clock=FakeClock(),
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=2.0,
                max_hops=30,
                timeout_ms=1000,
            )
            # 2 tomas, cada una con 1 hop placeholder = 2 samples.
            assert len(session.samples) == 2
            assert len(session.hop_stats) == 1
            hs = session.hop_stats[0]
            assert hs.hop_number == 1
            assert hs.success_count == 0
            assert hs.loss_pct == 100.0
            assert hs.samples == 2

    def test_ruta_perdida_una_sola_toma_produce_stats_con_un_sample(self):
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = FakeTracerouteRunner()
            runner.set_default_result(
                TracerouteResult(
                    target_provider="test",
                    hops=[TracerouteHop(1, None, None, None, False)],
                    culprit_hop_index=None,
                )
            )
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=FakeSleeper(FakeMonotonic()),
                clock=FakeClock(),
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=10.0,
                duration_s=5.0,  # 1 sola muestra
                max_hops=30,
                timeout_ms=1000,
            )
            hs = session.hop_stats[0]
            assert hs.samples == 1
            assert hs.success_count == 0
            assert hs.loss_pct == 100.0


# --------------------------------------------------------------------------- #
# DoD: stats agregadas son coherentes con las muestras individuales
# --------------------------------------------------------------------------- #


class TestMonitorDoDCoherence:
    def test_estadisticas_agregadas_son_coherentes_con_las_muestras(self):
        """DoD Fase 8: estadisticas agregadas por hop coherentes con las
        muestras individuales. Esta prueba valida intraconsistencia de
        la sesion generada: para cada hop_stats, sus campos estan derivados
        de las muestras correctas (mismo hop_number).

        take 0: hop1=2.0, hop2=18.0
        take 1: hop1=3.0, hop2=timeout
        take 2: hop1=2.5, hop2=22.0
        """
        # take 0: hop1 ok 2.0, hop2 ok 18.0
        # take 1: hop1 ok 3.0, hop2 timeout
        # take 2: hop1 ok 2.5, hop2 ok 22.0
        take_results = [
            TracerouteResult(
                target_provider="g",
                hops=[
                    TracerouteHop(1, "192.168.0.1", None, 2.0, True),
                    TracerouteHop(2, "8.8.8.8", None, 18.0, True),
                ],
                culprit_hop_index=1,
            ),
            TracerouteResult(
                target_provider="g",
                hops=[
                    TracerouteHop(1, "192.168.0.1", None, 3.0, True),
                    TracerouteHop(2, None, None, None, False),
                ],
                culprit_hop_index=None,
            ),
            TracerouteResult(
                target_provider="g",
                hops=[
                    TracerouteHop(1, "192.168.0.1", None, 2.5, True),
                    TracerouteHop(2, "8.8.8.8", None, 22.0, True),
                ],
                culprit_hop_index=None,
            ),
        ]
        with _patch_monotonic(FakeMonotonic()) as _mock_mono:
            runner = RotatingTracerouteRunner(take_results)
            monitor = RealRouteMonitor(
                traceroute_runner=runner,
                sleeper=FakeSleeper(FakeMonotonic()),
                clock=FakeClock(),
            )
            session = monitor.monitor(
                target_ip="8.8.8.8",
                target_provider="google",
                run_id="r",
                interval_s=1.0,
                duration_s=3.0,
                max_hops=30,
                timeout_ms=1000,
            )

        # Hop 1: todos responded, rtts [2.0, 3.0, 2.5]
        h1 = session.hop_stats[0]
        assert h1.hop_number == 1
        assert h1.samples == 3
        assert h1.success_count == 3
        assert h1.best_ms == 2.0
        assert h1.worst_ms == 3.0
        assert h1.avg_ms == pytest.approx((2.0 + 3.0 + 2.5) / 3.0, rel=1e-9)
        assert h1.jitter_ms == pytest.approx(
            statistics.stdev([2.0, 3.0, 2.5]),
            rel=1e-9,
        )
        assert h1.loss_pct == 0.0
        assert h1.ip == "192.168.0.1"

        # Hop 2: 2 responded (18.0, 22.0), 1 timeout
        h2 = session.hop_stats[1]
        assert h2.hop_number == 2
        assert h2.samples == 3
        assert h2.success_count == 2
        assert h2.best_ms == 18.0
        assert h2.worst_ms == 22.0
        assert h2.avg_ms == pytest.approx((18.0 + 22.0) / 2.0, rel=1e-9)
        assert h2.jitter_ms == pytest.approx(
            statistics.stdev([18.0, 22.0]),
            rel=1e-9,
        )
        assert h2.loss_pct == pytest.approx(100.0 / 3.0, rel=1e-9)
        # Moda: "8.8.8.8" aparece 2 veces, None 1 vez -> ip == "8.8.8.8"
        assert h2.ip == "8.8.8.8"

        # Verificacion puntual DoD: las muestras realmente conocidas
        # por hop 2 son las 3 tomas con rtts [18.0, None, 22.0].
        h2_samples = [s for s in session.samples if s.hop_number == 2]
        assert [s.rtt_ms for s in h2_samples] == [18.0, None, 22.0]
