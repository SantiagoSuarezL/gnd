"""Tests unitarios de los fakes de monitoreo para tests.

Estos fakes son use case-specific: sirven para armar capas superiores
(casos de uso de Application, futura UI) sin tocar el RouteMonitor real.
Como son metacodigo, sus tests son simples sanity/liskov checks.
"""

from __future__ import annotations

from datetime import datetime

from gnd.domain.fakes.fake_route_monitor import (
    FakeMonitoringRepository,
    FakeRouteMonitor,
)
from gnd.domain.ports.route_monitor import MonitoringRepository, RouteMonitor
from gnd.models.monitoring import HopStats, MonitoringSample, MonitoringSession


def _session(run_id: str = "r1") -> MonitoringSession:
    t = datetime(2026, 7, 25)
    return MonitoringSession(
        run_id=run_id,
        target_ip="8.8.8.8",
        target_provider="test",
        started_at=t,
        finished_at=t,
        interval_s=1.0,
        samples=[MonitoringSample(0, 1, 1.0)],
        hop_stats=[
            HopStats(
                hop_number=1,
                ip="1.1.1.1",
                hostname=None,
                best_ms=1.0,
                worst_ms=1.0,
                avg_ms=1.0,
                jitter_ms=0.0,
                loss_pct=0.0,
                samples=1,
                success_count=1,
            ),
        ],
    )


def test_fake_route_monitor_implements_protocol():
    assert isinstance(FakeRouteMonitor(), RouteMonitor)


def test_fake_monitoring_repository_implements_protocol():
    assert isinstance(FakeMonitoringRepository(), MonitoringRepository)


class TestFakeRouteMonitor:
    def test_default_devuelve_sesion_vacia_minima(self):
        mon = FakeRouteMonitor()
        session = mon.monitor(
            target_ip="x",
            target_provider="t",
            run_id="r",
            interval_s=1.0,
            duration_s=1.0,
            max_hops=5,
            timeout_ms=100,
        )
        assert session.samples == []
        assert session.hop_stats == []
        assert len(mon.calls) == 1

    def test_set_default_session_devuelve_esa(self):
        mon = FakeRouteMonitor()
        s = _session()
        mon.set_default_session(s)
        result = mon.monitor(
            target_ip="x",
            target_provider="t",
            run_id="r",
            interval_s=1.0,
            duration_s=1.0,
            max_hops=5,
            timeout_ms=100,
        )
        assert result is s

    def test_set_session_for_run_id_devuelve_esa(self):
        mon = FakeRouteMonitor()
        s = _session(run_id="run-X")
        mon.set_session_for_run_id("run-X", s)
        result = mon.monitor(
            target_ip="x",
            target_provider="t",
            run_id="run-X",
            interval_s=1.0,
            duration_s=1.0,
            max_hops=5,
            timeout_ms=100,
        )
        assert result is s
        # Otro run_id no usa esa sesion, cae en default:
        mon.set_default_session(_session(run_id="another"))
        result = mon.monitor(
            target_ip="x",
            target_provider="t",
            run_id="run-other",
            interval_s=1.0,
            duration_s=1.0,
            max_hops=5,
            timeout_ms=100,
        )
        assert result.run_id == "another"

    def test_calls_registran_parametros(self):
        mon = FakeRouteMonitor()
        mon.monitor(
            target_ip="9.9.9.9",
            target_provider="quad9",
            run_id="r",
            interval_s=2.5,
            duration_s=10.0,
            max_hops=20,
            timeout_ms=500,
        )
        call = mon.calls[0]
        assert call == {
            "target_ip": "9.9.9.9",
            "target_provider": "quad9",
            "run_id": "r",
            "interval_s": 2.5,
            "duration_s": 10.0,
            "max_hops": 20,
            "timeout_ms": 500,
        }


class TestFakeMonitoringRepository:
    def test_save_and_get(self):
        repo = FakeMonitoringRepository()
        s = _session(run_id="r-A")
        repo.save_session(s)
        result = repo.get_sessions_by_run("r-A")
        assert result == [s]
        assert len(repo.calls) == 2

    def test_get_inexistente_devuelve_vacia(self):
        repo = FakeMonitoringRepository()
        assert repo.get_sessions_by_run("nope") == []

    def test_multiples_sesiones_filtran_por_run_id(self):
        repo = FakeMonitoringRepository()
        s1 = _session(run_id="r-1")
        s2 = _session(run_id="r-1")
        s3 = _session(run_id="r-2")
        for s in [s1, s2, s3]:
            repo.save_session(s)
        result = repo.get_sessions_by_run("r-1")
        assert result == [s1, s2]
        assert repo.get_sessions_by_run("r-2") == [s3]
