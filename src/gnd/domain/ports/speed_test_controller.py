"""Protocol SpeedTestController — control de speed test (Fase 12b.5).

Abstrae la interacción con `ookla-speedtest` (binario externo en PATH)
para ejecutar un speed test y obtener métricas de ancho de banda. El
adapter real (``RealSpeedTestController``) invoca subprocess; este Protocol
permite tests con ``FakeSpeedTestController`` sin tocar red ni binarios
externos.

Regla de Oro 12b.2.1 generalizada: import de ``subprocess`` y ``shutil``
(para ``which``) DENTRO de ``__init__`` del adapter real — si
``speedtest`` no está en PATH, el wiring no crashea al arranque (EP §1.2).
El adapter marca ``_available=False`` y su método ``run()`` devuelve
un resultado de error + log.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gnd.models.speed_test import SpeedTestResult


class SpeedTestError(Exception):
    """Excepción lanzada por el SpeedTestController ante fallos operacionales.

    Atributos:
        message: Mensaje legible para humanos.
        original_error: Excepción original (subprocess.CalledProcessError,
            FileNotFoundError, etc.) para debugging/logging.
    """

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.original_error = original_error


@runtime_checkable
class SpeedTestController(Protocol):
    """Protocol para ejecutar speed tests via ``ookla-speedtest``.

    Contrato:
    - ``run()`` puede lanzar ``SpeedTestError`` si el comando falla
      (timeout, speedtest no encontrado, error de parsing). El caller
      decide cómo manejar (reintentar, loguear, notificar al usuario).
    - ``available`` es una property que indica si el binario está en PATH.
    - El método es idempotentente en sentido: cada llamada ejecuta un
      speed test completo (no hay estado persistente entre llamadas).
    """

    @property
    def available(self) -> bool:
        """True si el binario speedtest está en PATH y disponible."""
        ...

    def run(self) -> SpeedTestResult:
        """Ejecuta un speed test completo y devuelve las métricas.

        Lanza ``SpeedTestError`` si falla (timeout, binario no encontrado,
        parsing inválido).
        """
        ...
