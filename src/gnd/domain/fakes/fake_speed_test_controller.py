"""Fake in-memory de SpeedTestController para tests (Fase 12b.5).

Implementa el Protocol `SpeedTestController` sin invocar subprocess real.
Permite simular resultados de speed test programables + fallos controlados.

Cumple contrato: métodos no lanzan excepción salvo que el test configure
`fail_on_run` para forzar SpeedTestError (simular fallos de speedtest).
"""

from __future__ import annotations

from gnd.domain.ports.speed_test_controller import SpeedTestError
from gnd.models.speed_test import SpeedTestResult


class FakeSpeedTestController:
    """Fake de SpeedTestController con resultados programables.

    Constructor kwargs:
    - result: SpeedTestResult a devolver en run() (default: resultado fijo).
    - fail_on_run: forzar SpeedTestError en run().
    - available: valor de la property `available` (default True).

    Atributos públicos para aserciones:
    - run_calls: contador de llamadas a run().
    """

    def __init__(
        self,
        *,
        result: SpeedTestResult | None = None,
        fail_on_run: bool = False,
        available: bool = True,
    ) -> None:
        self._result = result or SpeedTestResult(
            latency_ms=15.0,
            jitter_ms=2.0,
            download_mbps=100.0,
            upload_mbps=50.0,
            packet_loss_pct=0.0,
            server_name="Test Server",
            server_country="Test Country",
            isp="Test ISP",
        )
        self._fail_on_run = fail_on_run
        self._available = available
        self.run_calls = 0

    @property
    def available(self) -> bool:
        return self._available

    def run(self) -> SpeedTestResult:
        self.run_calls += 1
        if self._fail_on_run:
            raise SpeedTestError("fake run error")
        return self._result

    def set_result(self, result: SpeedTestResult) -> None:
        """Cambia el resultado que run() devolverá en llamadas futuras."""
        self._result = result

    def set_fail_on_run(self, fail: bool) -> None:
        self._fail_on_run = fail
