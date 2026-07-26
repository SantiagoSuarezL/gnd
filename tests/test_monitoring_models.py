"""Tests unitarios de modelos de dominio MonitoringSession / HopStats / MonitoringSample.

EP §1.6 (inmutabilidad), EP §1.1 (no infraestructura). Verifica las
invariantes documentadas en ``models/monitoring.py``.

Estos tests cubren el caso feliz + todos los bordes documentados en los
``__post_init__`` (valor de frontera y casos de error).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from gnd.models.monitoring import HopStats, MonitoringSample, MonitoringSession
from gnd.models.traceroute import TracerouteHop, TracerouteResult

# --------------------------------------------------------------------------- #
# HopStats
# --------------------------------------------------------------------------- #


def _good_hop_stats(**overrides) -> HopStats:
    base = dict(
        hop_number=1,
        ip="1.2.3.4",
        hostname=None,
        best_ms=10.0,
        worst_ms=20.0,
        avg_ms=15.0,
        jitter_ms=3.5,
        loss_pct=10.0,
        samples=10,
        success_count=9,
    )
    base.update(overrides)
    return HopStats(**base)


class TestHopStatsHappy:
    def test_construccion_valida(self):
        hs = _good_hop_stats()
        assert hs.hop_number == 1
        assert hs.best_ms == 10.0
        assert hs.avg_ms == 15.0
        assert hs.worst_ms == 20.0
        assert hs.success_count == 9

    def test_hop_sin_respuestas_puros(self):
        hs = HopStats(
            hop_number=5,
            ip=None,
            hostname=None,
            best_ms=None,
            worst_ms=None,
            avg_ms=None,
            jitter_ms=0.0,
            loss_pct=100.0,
            samples=4,
            success_count=0,
        )
        assert hs.loss_pct == 100.0
        assert hs.best_ms is None
        assert hs.avg_ms is None

    def test_una_sola_muestra_respondida(self):
        # 1 sample, 1 success: best=worst=avg, jitter=0
        hs = HopStats(
            hop_number=2,
            ip="8.8.8.8",
            hostname=None,
            best_ms=12.0,
            worst_ms=12.0,
            avg_ms=12.0,
            jitter_ms=0.0,
            loss_pct=0.0,
            samples=1,
            success_count=1,
        )
        assert hs.best_ms == hs.avg_ms == hs.worst_ms


class TestHopStatsInvariants:
    def test_hop_number_cero_rechazado(self):
        with pytest.raises(ValueError, match="hop_number debe ser >= 1"):
            _good_hop_stats(hop_number=0)

    def test_hop_number_negativo_rechazado(self):
        with pytest.raises(ValueError, match="hop_number debe ser >= 1"):
            _good_hop_stats(hop_number=-1)

    def test_samples_cero_rechazado(self):
        with pytest.raises(ValueError, match="samples debe ser >= 1"):
            _good_hop_stats(samples=0)

    def test_loss_pct_fuera_rango(self):
        with pytest.raises(ValueError, match="loss_pct"):
            _good_hop_stats(loss_pct=-0.1)
        with pytest.raises(ValueError, match="loss_pct"):
            _good_hop_stats(loss_pct=100.1)

    def test_jitter_negativo_rechazado(self):
        with pytest.raises(ValueError, match="jitter_ms"):
            _good_hop_stats(jitter_ms=-0.01)

    def test_success_count_mayor_que_samples(self):
        with pytest.raises(ValueError, match="success_count fuera de rango"):
            _good_hop_stats(success_count=11, samples=10)

    def test_success_count_negativo(self):
        with pytest.raises(ValueError, match="success_count fuera de rango"):
            _good_hop_stats(success_count=-1, samples=10)

    def test_best_avg_worst_none_cuando_success_count_cero(self):
        # Si success_count==0 y alguno no es None -> error.
        bad_combos = [
            {"best_ms": 10.0, "worst_ms": None, "avg_ms": None},
            {"best_ms": None, "worst_ms": 20.0, "avg_ms": None},
            {"best_ms": None, "worst_ms": None, "avg_ms": 15.0},
        ]
        for bad in bad_combos:
            with pytest.raises(ValueError, match="best/worst/avg deben ser None"):
                _good_hop_stats(
                    success_count=0,
                    loss_pct=100.0,
                    **bad,
                )

    def test_none_cuando_success_count_mayor_cero(self):
        # Si success_count>=1 y alguno es None -> error
        for field in ["best_ms", "worst_ms", "avg_ms"]:
            with pytest.raises(ValueError, match="best/worst/avg deben tener valor"):
                _good_hop_stats(**{field: None})

    def test_orden_best_avg_worst_violado(self):
        with pytest.raises(ValueError, match="best<=avg<=worst"):
            _good_hop_stats(best_ms=20.0, avg_ms=15.0, worst_ms=10.0)

    def test_avg_fuera_de_orden(self):
        with pytest.raises(ValueError, match="best<=avg<=worst"):
            _good_hop_stats(best_ms=10.0, avg_ms=5.0, worst_ms=20.0)

    def test_rtt_negativo(self):
        with pytest.raises(ValueError, match="rtt values deben ser >= 0"):
            _good_hop_stats(best_ms=-1.0, avg_ms=15.0, worst_ms=20.0)


def test_hop_stats_frozen():
    hs = _good_hop_stats()
    with pytest.raises(FrozenInstanceError):
        hs.hop_number = 999  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# MonitoringSample
# --------------------------------------------------------------------------- #


class TestMonitoringSample:
    def test_construccion_valida(self):
        s = MonitoringSample(sample_index=0, hop_number=1, rtt_ms=15.5)
        assert s.sample_index == 0
        assert s.hop_number == 1
        assert s.rtt_ms == 15.5

    def test_rtt_none_valido(self):
        s = MonitoringSample(sample_index=3, hop_number=2, rtt_ms=None)
        assert s.rtt_ms is None

    def test_sample_index_negativo(self):
        with pytest.raises(ValueError, match="sample_index debe ser >= 0"):
            MonitoringSample(sample_index=-1, hop_number=1, rtt_ms=1.0)

    def test_hop_number_cero(self):
        with pytest.raises(ValueError, match="hop_number"):
            MonitoringSample(sample_index=0, hop_number=0, rtt_ms=1.0)

    def test_rtt_negativo(self):
        with pytest.raises(ValueError, match="rtt_ms debe ser >= 0"):
            MonitoringSample(sample_index=0, hop_number=1, rtt_ms=-0.1)

    def test_frozen(self):
        s = MonitoringSample(sample_index=0, hop_number=1, rtt_ms=1.0)
        with pytest.raises(FrozenInstanceError):
            s.rtt_ms = 999.0  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# MonitoringSession
# --------------------------------------------------------------------------- #


def _make_traceroute_result() -> TracerouteResult:
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


def _good_session(**overrides) -> MonitoringSession:
    t0 = datetime(2026, 7, 25, 12, 0, 0)
    t1 = datetime(2026, 7, 25, 12, 1, 0)
    base = dict(
        run_id="run-1",
        target_ip="8.8.8.8",
        target_provider="google",
        started_at=t0,
        finished_at=t1,
        interval_s=5.0,
        samples=[
            MonitoringSample(sample_index=0, hop_number=1, rtt_ms=2.0),
            MonitoringSample(sample_index=0, hop_number=2, rtt_ms=18.0),
            MonitoringSample(sample_index=1, hop_number=1, rtt_ms=3.0),
            MonitoringSample(sample_index=1, hop_number=2, rtt_ms=20.0),
        ],
        hop_stats=[
            HopStats(
                hop_number=1,
                ip="192.168.0.1",
                hostname=None,
                best_ms=2.0,
                worst_ms=3.0,
                avg_ms=2.5,
                jitter_ms=0.5,
                loss_pct=0.0,
                samples=2,
                success_count=2,
            ),
            HopStats(
                hop_number=2,
                ip="8.8.8.8",
                hostname=None,
                best_ms=18.0,
                worst_ms=20.0,
                avg_ms=19.0,
                jitter_ms=1.0,
                loss_pct=0.0,
                samples=2,
                success_count=2,
            ),
        ],
    )
    base.update(overrides)
    return MonitoringSession(**base)


class TestMonitoringSessionHappy:
    def test_construccion_valida(self):
        s = _good_session()
        assert s.run_id == "run-1"
        assert len(s.samples) == 4
        assert len(s.hop_stats) == 2

    def test_empty_session_valida(self):
        t = datetime(2026, 7, 25)
        s = MonitoringSession(
            run_id="run-2",
            target_ip="x",
            target_provider="test",
            started_at=t,
            finished_at=t,
            interval_s=1.0,
            samples=[],
            hop_stats=[],
        )
        assert s.samples == []
        assert s.hop_stats == []


class TestMonitoringSessionInvariants:
    def test_run_id_vacio(self):
        with pytest.raises(ValueError, match="run_id"):
            _good_session(run_id="")

    def test_target_ip_vacio(self):
        with pytest.raises(ValueError, match="target_ip"):
            _good_session(target_ip="")

    def test_target_provider_vacio(self):
        with pytest.raises(ValueError, match="target_provider"):
            _good_session(target_provider="")

    def test_interval_negativo(self):
        with pytest.raises(ValueError, match="interval_s"):
            _good_session(interval_s=-0.1)

    def test_finished_at_antes_started_at(self):
        with pytest.raises(ValueError, match="finished_at no puede ser anterior"):
            _good_session(
                started_at=datetime(2026, 7, 25, 12, 0, 30),
                finished_at=datetime(2026, 7, 25, 12, 0, 0),
            )

    def test_samples_con_hop_stats_vacio(self):
        # Si hay samples, hop_stats no puede ser vacio.
        with pytest.raises(ValueError, match="si hay samples, hop_stats"):
            _good_session(samples=[MonitoringSample(0, 1, 1.0)], hop_stats=[])

    def test_samples_vacio_con_hop_stats_es_valido(self):
        # Snapshot reconstruido de la DB: solo stats, no crudas.
        from datetime import datetime

        h = HopStats(
            hop_number=1,
            ip="1.1.1.1",
            hostname=None,
            best_ms=10.0,
            worst_ms=10.0,
            avg_ms=10.0,
            jitter_ms=0.0,
            loss_pct=0.0,
            samples=1,
            success_count=1,
        )
        s = MonitoringSession(
            run_id="r-snap",
            target_ip="x",
            target_provider="t",
            started_at=datetime(2026, 7, 25),
            finished_at=datetime(2026, 7, 25, 0, 0, 1),
            interval_s=1.0,
            samples=[],
            hop_stats=[h],
        )
        assert s.samples == []
        assert len(s.hop_stats) == 1

    def test_hop_stats_desordenado(self):
        h1, h2 = _good_session().hop_stats
        with pytest.raises(ValueError, match="ordenado por hop_number"):
            _good_session(hop_stats=[h2, h1])

    def test_hop_stats_hop_number_duplicado(self):
        h1 = HopStats(
            hop_number=1,
            ip="1.1.1.1",
            hostname=None,
            best_ms=10.0,
            worst_ms=10.0,
            avg_ms=10.0,
            jitter_ms=0.0,
            loss_pct=0.0,
            samples=1,
            success_count=1,
        )
        h_dup = HopStats(
            hop_number=1,
            ip="2.2.2.2",
            hostname=None,
            best_ms=20.0,
            worst_ms=20.0,
            avg_ms=20.0,
            jitter_ms=0.0,
            loss_pct=0.0,
            samples=1,
            success_count=1,
        )
        with pytest.raises(ValueError, match="hop_number duplicado"):
            _good_session(hop_stats=[h1, h_dup])

    def test_frozen(self):
        s = _good_session()
        with pytest.raises(FrozenInstanceError):
            s.run_id = "otro"  # type: ignore[misc]
