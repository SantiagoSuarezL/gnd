"""Tests de integracion del orquestador ``RouteMonitor`` contra red real.

Marcados con ``@pytest.mark.integration`` para no correr en CI offline
(Regla de Oro 2.3). Para correrlos explicitamente:
    pytest -m integration

Cubren:
- Sesion corta (3-4 tomas a 1s de intervalo) contra 1.1.1.1 (estable,
  ICMP amigable). Verifica que el monitor end-to-end produce HopStats
  con todos los campos llenos (best <= avg <= worst, jitter > 0 si la
  red fluctua, loss_pct dentro de rangos razonables).
- coherencia intraconsistencia: para cada hop, sus muestras crudas son
  lasregistradas y las stats se derivan de ellas (DoD Fase 8).

Estos tests pueden ser lentos (~10-20s c/u). Se asume que 1.1.1.1 es
reach en cualquier entorno dev.
"""

from __future__ import annotations

import statistics

import pytest

from gnd.monitoring.route_monitor import RouteMonitor
from gnd.network.real_traceroute_runner import RealTracerouteRunner

pytestmark = pytest.mark.integration


def test_short_monitoring_session_1_1_1_1():
    """DoD Fase 8: sesion corta de 3 tomas a interval=1s contra 1.1.1.1.

    Verifica:
    - Se ejecuto el numero esperado de tomas (>= 1).
    - Hay hop_stats no vacio.
    - Las HopStats cumplen invariantes (best<=avg<=worst, jitter>=0,
      loss_pct en [0,100], samples>=1).
    - Las muestras individuales son coherentes con las stats agregadas
      (mismo count de improvements == success_count para ese hop).
    """
    runner = RealTracerouteRunner(jump_threshold_ms=40.0)
    monitor = RouteMonitor(traceroute_runner=runner)

    session = monitor.monitor(
        target_ip="1.1.1.1",
        target_provider="cloudflare",
        run_id="integration-1",
        interval_s=1.0,
        duration_s=3.0,  # 3 tomas
        max_hops=10,
        timeout_ms=1000,
    )

    assert session.run_id == "integration-1"
    assert session.target_ip == "1.1.1.1"
    assert session.target_provider == "cloudflare"
    assert session.interval_s == 1.0
    # duration=3, interval=1 -> 3 muestras planeadas. Cada traceroute a
    # 1.1.1.1 deberia tener entre 3 y 10 hops. Verificamos que hay muestras:
    assert len(session.samples) > 0
    assert len(session.hop_stats) > 0

    for hs in session.hop_stats:
        assert hs.samples >= 1
        assert 0.0 <= hs.loss_pct <= 100.0
        assert hs.jitter_ms >= 0.0
        assert 0 <= hs.success_count <= hs.samples
        if hs.success_count > 0:
            assert hs.best_ms is not None
            assert hs.avg_ms is not None
            assert hs.worst_ms is not None
            assert hs.best_ms <= hs.avg_ms <= hs.worst_ms

    # Coherencia: para cada hop, los samples de sessionSamples con ese
    # hop_number son exactamente hs.samples en count.
    for hs in session.hop_stats:
        matching_samples = [s for s in session.samples if s.hop_number == hs.hop_number]
        assert len(matching_samples) == hs.samples
        # Coherencia de success_count (rtts no None = success).
        assert (
            sum(1 for s in matching_samples if s.rtt_ms is not None) == hs.success_count
        )


def test_monitoring_session_aggregated_stats_match_manual_aggregation():
    """DoD explicito: las estadisticas agregadas por hop son coherentes con
    las muestras individuales. Computa manualmente best/worst/avg/jitter/
    loss a partir de session.samples y compara con session.hop_stats."""
    runner = RealTracerouteRunner(jump_threshold_ms=40.0)
    monitor = RouteMonitor(traceroute_runner=runner)
    session = monitor.monitor(
        target_ip="1.1.1.1",
        target_provider="cloudflare",
        run_id="integration-2",
        interval_s=1.0,
        duration_s=3.0,
        max_hops=10,
        timeout_ms=1000,
    )

    # Indexar hop_stats por hop_number para lookup en O(1):
    hs_by_hop = {hs.hop_number: hs for hs in session.hop_stats}

    # Indexar muestras por hop_number.
    samples_by_hop: dict[int, list[float | None]] = {}
    for s in session.samples:
        samples_by_hop.setdefault(s.hop_number, []).append(s.rtt_ms)

    # Para cada hop_number observado, validar que las stats agregadas
    # coinciden con el calculo manual.
    for hop_num, rtts in samples_by_hop.items():
        hs = hs_by_hop[hop_num]
        assert hs is not None
        successes = [r for r in rtts if r is not None]
        assert hs.samples == len(rtts)
        assert hs.success_count == len(successes)

        # Loss:
        expected_loss = 100.0 * (len(rtts) - len(successes)) / len(rtts)
        assert hs.loss_pct == pytest.approx(expected_loss, rel=1e-9)

        # Best/worst/avg/jitter con datos:
        if successes:
            assert hs.best_ms == pytest.approx(min(successes), rel=1e-6)
            assert hs.worst_ms == pytest.approx(max(successes), rel=1e-6)
            assert hs.avg_ms == pytest.approx(statistics.fmean(successes), rel=1e-6)
            expected_jitter = statistics.stdev(successes) if len(successes) > 1 else 0.0
            assert hs.jitter_ms == pytest.approx(expected_jitter, abs=1e-6)
        else:
            assert hs.best_ms is None
            assert hs.worst_ms is None
            assert hs.avg_ms is None
            assert hs.jitter_ms == 0.0
