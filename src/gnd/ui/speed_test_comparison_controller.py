"""Controller para speed test bajo demanda (Fase 12b.5).

Sigue el mismo patrón que ``WarpComparisonController``: ejecuta el caso de
uso en un thread daemon y notifica via callbacks (que la UI agenda en
el main loop via `root.after`).

El speed test ejecuta un diagnóstico completo + un speed test, cada uno
~10-90s. Total ~30-120s. La UI muestra progreso via ``on_progress`` para
mantener al usuario informado.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
)
from gnd.application.speed_test_comparison import (
    SpeedTestComparisonParams,
    SpeedTestComparisonUseCase,
)
from gnd.models.speed_test import SpeedTestComparisonResult

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[str], None]
ResultCallback = Callable[[SpeedTestComparisonResult], None]
ErrorCallback = Callable[[str], None]


class SpeedTestComparisonController:
    """Orquesta el speed test en thread daemon.

    Uso tipico (MainWindow):

        controller = SpeedTestComparisonController(
            use_case=use_case,
            targets=targets,
            diagnostic_params=params,
            speed_test_params=SpeedTestComparisonParams(
                diagnostic_params=params,
            ),
            on_progress=self._on_progress,
            on_result=self._on_result,
            on_error=self._on_error,
        )
        controller.run_async()  # no bloquea
    """

    def __init__(
        self,
        *,
        use_case: SpeedTestComparisonUseCase,
        targets: DiagnosticTargets,
        diagnostic_params: DiagnosticParams,
        speed_test_params: SpeedTestComparisonParams,
        on_progress: ProgressCallback,
        on_result: ResultCallback,
        on_error: ErrorCallback,
    ) -> None:
        self._use_case = use_case
        self._targets = targets
        self._diagnostic_params = diagnostic_params
        self._speed_test_params = speed_test_params
        self._on_progress = on_progress
        self._on_result = on_result
        self._on_error = on_error
        self._thread: threading.Thread | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_async(self) -> None:
        """Lanza el speed test en un thread daemon. No bloquea."""
        if self.is_running():
            logger.warning("run_async llamado con un speed test en curso — ignorado")
            return
        self._thread = threading.Thread(
            target=self._worker,
            name="gnd-speed-test-comparison",
            daemon=True,
        )
        self._thread.start()

    def _worker(self) -> None:
        """Worker thread: ejecuta el caso de uso y dispatcha callbacks.

        EP §1.2: ninguna excepción se propaga al thread. Toda falla se
        convierte en `on_error` con mensaje claro.
        """
        try:
            result = self._use_case.execute(
                self._targets,
                self._speed_test_params,
            )
            self._on_result(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Speed test comparison controller worker fallo")
            self._on_error(f"Error inesperado en speed test: {exc!r}")
