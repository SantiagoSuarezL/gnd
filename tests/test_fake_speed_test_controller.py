"""Tests del FakeSpeedTestController (Fase 12b.5).

El fake se usa en tests del SpeedTestComparisonUseCase y UI integration
cuando no queremos invocar speedtest real. Cubrimos:
- Estado configurable via constructor.
- `run()` devuelve el resultado programable.
- Implementa el Protocol SpeedTestController (runtime_checkable).
- Modos de fallo (`fail_on_run`) para testear error handling.
- `set_result` / `set_fail_on_run` helpers permiten mutar estado entre llamadas.
- `available` property configurable.
"""

from __future__ import annotations

import pytest

from gnd.domain.fakes.fake_speed_test_controller import FakeSpeedTestController
from gnd.domain.ports.speed_test_controller import (
    SpeedTestController,
    SpeedTestError,
)
from gnd.models.speed_test import SpeedTestResult


def _result() -> SpeedTestResult:
    return SpeedTestResult(
        latency_ms=15.0,
        jitter_ms=2.0,
        download_mbps=100.0,
        upload_mbps=50.0,
        packet_loss_pct=0.0,
        server_name="Test Server",
        server_country="Test Country",
        isp="Test ISP",
    )


class TestFakeSpeedTestController:
    def test_estado_inicial_disponible(self) -> None:
        fake = FakeSpeedTestController()
        assert fake.available is True

    def test_estado_inicial_no_disponible(self) -> None:
        fake = FakeSpeedTestController(available=False)
        assert fake.available is False

    def test_run_devuelve_resultado_default(self) -> None:
        fake = FakeSpeedTestController()
        result = fake.run()
        assert result.latency_ms == 15.0
        assert result.download_mbps == 100.0

    def test_run_devuelve_resultado_programable(self) -> None:
        custom = _result()
        custom = SpeedTestResult(
            latency_ms=99.0,
            jitter_ms=5.0,
            download_mbps=200.0,
            upload_mbps=100.0,
            packet_loss_pct=1.0,
            server_name="Custom Server",
            server_country="Custom Country",
            isp="Custom ISP",
        )
        fake = FakeSpeedTestController(result=custom)
        result = fake.run()
        assert result.latency_ms == 99.0
        assert result.download_mbps == 200.0
        assert result.server_name == "Custom Server"

    def test_run_registra_contador_de_llamadas(self) -> None:
        fake = FakeSpeedTestController()
        assert fake.run_calls == 0
        fake.run()
        assert fake.run_calls == 1
        fake.run()
        assert fake.run_calls == 2

    def test_fail_on_run_lanza_speed_test_error(self) -> None:
        fake = FakeSpeedTestController(fail_on_run=True)
        with pytest.raises(SpeedTestError):
            fake.run()

    def test_set_result_cambia_resultado(self) -> None:
        fake = FakeSpeedTestController()
        assert fake.run().latency_ms == 15.0
        new_result = SpeedTestResult(
            latency_ms=50.0,
            jitter_ms=3.0,
            download_mbps=50.0,
            upload_mbps=25.0,
            packet_loss_pct=0.5,
            server_name="New Server",
            server_country="New Country",
            isp="New ISP",
        )
        fake.set_result(new_result)
        result = fake.run()
        assert result.latency_ms == 50.0
        assert result.server_name == "New Server"

    def test_set_fail_on_run_en_runtime(self) -> None:
        fake = FakeSpeedTestController()
        fake.run()  # funciona
        fake.set_fail_on_run(True)
        with pytest.raises(SpeedTestError):
            fake.run()
        fake.set_fail_on_run(False)
        fake.run()  # funciona de nuevo

    def test_implementa_protocol_speed_test_controller(self) -> None:
        fake = FakeSpeedTestController()
        assert isinstance(fake, SpeedTestController)

    def test_speed_test_error_tiene_atributos(self) -> None:
        try:
            raise SpeedTestError("test message", original_error=ValueError("orig"))
        except SpeedTestError as exc:
            assert exc.message == "test message"
            assert isinstance(exc.original_error, ValueError)
            assert str(exc) == "test message"
