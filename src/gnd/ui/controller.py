"""Controller — orquesta el caso de uso en un thread y notifica a la UI.

PRD §6.1: "presionar un boton y en segundos saber si es seguro entrar
a ranked". DoD Fase 9 (IMPLEMENTATION_PLAN.md): "ejecutar un diagnostico
completo y ver el resultado SIN que la ventana se congele".

Patron threading + tkinter (no asyncio):
- tkinter NO es thread-safe. Actualizar widgets desde un thread que
  no es el main loop corrompe el estado. La practica estandar es:
  el worker thread hace el trabajo pesado (sondeos de red, IO bloqueante)
  y al terminar invoca `root.after(0, callback)` para agendar la
  actualizacion de UI en el main loop.
- `progress_callback` del caso de uso se invoca desde el worker thread,
  por lo que el callback en `DiagnosticsController` solo debe agendar
  actualizaciones via `root.after` — nunca tocar widgets directamente.

No conocemos ni instanciamos implementaciones concretas: recibimos el
caso de uso ya construido (composition_root). Solo conoce RunFullDiagnostics
y tkinter.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.models.diagnostic_run import DiagnosticRun

logger = logging.getLogger(__name__)


# Type alias para el callback de resultado (thread-safe: la UI implementa
# esto para agendar la actualizacion en el main loop).
ResultCallback = Callable[[DiagnosticRun], None]
ProgressCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


class DiagnosticsController:
    """Orquesta el caso de uso en un thread daemon y reporta progreso/resultado.

    Uso tipico (desde la MainWindow):

        controller = DiagnosticsController(
            root=root,
            use_case=use_case,
            targets=targets,
            params=params,
            on_result=self._on_result,
            on_progress=self._on_progress,
            on_error=self._on_error,
        )
        controller.run_async()  # no bloquea

    El controller NO toca widgets. Solo invoca los callbacks provistos.
    La MainWindow es responsable de que esos callbacks agenden UI via
    `root.after(0, ...)` (thread-safe).
    """

    def __init__(
        self,
        *,
        use_case: RunFullDiagnostics,
        targets: DiagnosticTargets,
        params: DiagnosticParams,
        on_progress: ProgressCallback,
        on_result: ResultCallback,
        on_error: ErrorCallback,
    ) -> None:
        self._use_case = use_case
        self._targets = targets
        self._params = params
        self._on_progress = on_progress
        self._on_result = on_result
        self._on_error = on_error
        self._thread: threading.Thread | None = None

    def is_running(self) -> bool:
        """True si hay un diagnostico en curso."""
        return self._thread is not None and self._thread.is_alive()

    def run_async(self) -> None:
        """Lanza el diagnostico en un thread daemon. No bloquea.

        Idempotente solo en sentido debil: si ya hay uno corriendo,
        ignora el pedido nuevo (y loguea). La UI deberia deshabilitar
        el boton mientras corre, pero este guard previene double-submit.
        """
        if self.is_running():
            logger.warning("run_async llamado con un diagnostico en curso — ignorado")
            return
        self._thread = threading.Thread(
            target=self._worker, name="gnd-diagnostics", daemon=True
        )
        self._thread.start()

    def _worker(self) -> None:
        """Worker thread: ejecuta el caso de uso y dispatcha callbacks.

        EP §1.2 arquitectural: ninguna excepcion del caso de uso debe
        propagarse al thread (matarlo silenciosamente seria peor). Toda
        falla se convierte en un callback `on_error` con mensaje claro.
        """
        try:
            run = self._use_case.execute(
                self._targets,
                self._params,
                progress_callback=lambda stage: self._on_progress(stage),
            )
            self._on_result(run)
        except Exception as exc:  # noqa: BLE001 — explicicio en docstring
            logger.exception("Diagnostics controller worker fallo")
            self._on_error(f"Error inesperado: {exc!r}")
