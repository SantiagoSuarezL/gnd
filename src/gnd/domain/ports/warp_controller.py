"""Protocol WarpController — control de Cloudflare WARP (Fase 12b.4).

Abstrae la interacción con `warp-cli` (binario externo en PATH) para
habilitar/deshabilitar WARP y consultar su estado. El adapter real
(`RealWarpController`) invoca subprocess; este Protocol permite tests con
`FakeWarpController` sin tocar red ni binarios externos.

Regla de Oro 12b.2.1 generalizada: import de `subprocess` y `shutil` (para
`which`) DENTRO de `__init__` del adapter real — si `warp-cli` no está
en PATH, el wiring no crashea al arrancar (EP §1.2). El adapter marca
`_available=False` y sus métodos devuelven estado degradado + log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WarpStatus:
    """Estado actual de WARP.

    Atributos:
        connected: True si WARP está conectado (túnel activo).
        registration_status: "registered" | "unregistered" | "error".
        connection_status: "connected" | "disconnected" | "connecting" | "error".
        warp_plus: True si la cuenta tiene WARP+ (mejora de routing).
    """

    connected: bool
    registration_status: str
    connection_status: str
    warp_plus: bool


class WarpError(Exception):
    """Excepción lanzada por el WarpController ante fallos operacionales.

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
class WarpController(Protocol):
    """Protocol para controlar Cloudflare WARP via `warp-cli`.

    Contrato:
    - `get_status()` nunca lanza: devuelve WarpStatus con estado actual.
      Si hay error interno (warp-cli no responde, parsing falla), devuelve
      WarpStatus con `connected=False` y status "error" + log.
    - `enable()` / `disable()` pueden lanzar `WarpError` si el comando
      falla (timeout, warp-cli no encontrado, error de permiso). El caller
      decide cómo manejar (reintentar, loguear, notificar al usuario).
    - Todos los métodos son idempotentes: llamar `enable()` con WARP ya
      activo no falla; llamar `disable()` con WARP ya apagado no falla.
    """

    def get_status(self) -> WarpStatus:
        """Consulta estado actual de WARP (sin mutar estado)."""
        ...

    def enable(self) -> WarpStatus:
        """Activa WARP (equivalente a `warp-cli connect`).

        Devuelve el estado tras la activación. Lanza WarpError si falla.
        """
        ...

    def disable(self) -> WarpStatus:
        """Desactiva WARP (equivalente a `warp-cli disconnect`).

        Devuelve el estado tras la desactivación. Lanza WarpError si falla.
        """
        ...
