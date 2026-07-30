"""Adapter ``PlyerDesktopNotifier`` — emite notificaciones via plyer (Fase 12b.2).

IMPLEMENTATION_PLAN.md 12b.2: wrap de ``plyer.notification.notify`` que
abstrae el backend nativo del OS (Windows toast / Linux Freedesktop /
macOS NSUserNotification). El dominio no conoce plyer; el dominio habla
con el Protocol ``DesktopNotifier`` y pasa ``DesktopNotification``
(value object inmutable).

EP §1.2: el adapter NUNCA propaga excepciones a la UI. ``plyer`` levanta
``NotImplementedError`` si no encuentra backend utilizable (headless/
CI/OS sin soporte); tambien puede levantar ``ImportError`` si la lib
falta, ``OSError``/``RuntimeError`` de backends especificos. Todo esto
se captura y loguea via ``event="notification.error"`` (Regla 11.3).
La llamada ``notify`` vuelve sin tirar; el caller (MainWindow) confia
en el contrato y no hace try/except.

Protocolo 8: import de ``plyer`` DEFERIDO dentro de ``__init__``. Si la
lib no esta instalada (ej: fresh venv sin ``plyer>=2.1.0`` en CI sin
sincronizar pyproject), el constructor captura el ``ImportError`` y
marca ``_available=False``; las subsiguientes ``notify`` se vuelven
no-op con log. Asi el wiring (composition_root) nunca crashea al
arrancar por falta de plyer — el toggle de ``enabled`` en config sigue
siendo el unico control real, y un upgrade de deps la revive.

EP §5: logging estructurado. Eventos con namespace ``notification``:
- ``notification.start`` (intent emitido, pre-syscall).
- ``notification.finish`` (success post-syscall).
- ``notification.error`` (cualquier fallo capturado, con ``error`` y
  ``exc_class`` en el extra).
- ``notification.skip`` plyer ausente o disabled (no deberia llegar aca,
  el caller filtra por settings, pero defense-in-depth).

Regla 11.2: ``JsonFormatter`` omite ``None`` — no llenamos extras con
``None`` esperando que el formateador los tire; solo pasamos lo que
tenemos en cada rama.
"""

from __future__ import annotations

import logging

from gnd.models.notification import DesktopNotification

logger = logging.getLogger(__name__)


class PlyerDesktopNotifier:
    """Implementacion de ``DesktopNotifier`` sobre ``plyer.notification``.

    Args:
        app_name: nombre de la app en la toast del OS (header native
            Win10+). Default "GND".
        timeout_seconds: tiempo (s) que la toast permanece visible
            antes de auto-cerrar. Default 8.

    Import de plyer diferido en ``__init__`` (Protocolo 8). Si el import
    falla (lib faltante), ``_available=False`` y ``notify`` se vuelve
    no-op con log — nunca lanza.
    """

    def __init__(
        self,
        *,
        app_name: str = "GND",
        timeout_seconds: int = 8,
    ) -> None:
        self._app_name = app_name
        self._timeout_seconds = timeout_seconds
        self._available = False
        try:
            # Import diferido — plyer puede no estar instalado en envs
            # sin sync de pyproject. Protocolo 8 (import diferido y
            # encapsulado para adaptadores de infraestructura).
            from plyer import notification as _pn  # noqa: F401

            self._pn = _pn
            self._available = True
        except ImportError as exc:
            self._pn = None
            logger.warning(
                "plyer no disponible — notificaciones deshabilitadas",
                extra={
                    "event": "notification.error",
                    "error": "plyer import failed",
                    "exc_class": type(exc).__name__,
                },
            )

    def notify(self, notification: DesktopNotification) -> None:
        """Emite ``notification`` via plyer. Nunca lanza (EP §1.2).

        Si plyer fallo al construir el adapter (``_available=False``),
        no-op con log ``notification.skip``.
        Si la syscall de plyer levanta cualquier excepcion (incluido
        ``NotImplementedError`` de facades sin backend), captura y
        loguea ``notification.error`` sin propagar.
        """
        if not self._available or self._pn is None:
            logger.info(
                "Notificación omitida (plyer no disponible)",
                extra={
                    "event": "notification.skip",
                    "reason": "plyer_unavailable",
                    "title": notification.title,
                },
            )
            return

        logger.info(
            "Enviando notificación",
            extra={
                "event": "notification.start",
                "title": notification.title,
            },
        )
        try:
            self._pn.notify(
                title=notification.title,
                message=notification.message,
                app_name=self._app_name,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 — contrato EP §1.2
            # Plyer levanta NotImplementedError si su _notify no encuentra
            # backend (headless/CI). Tambien OSError/RuntimeError de
            # backends especificos (Win toast API en Win7, etc.). Todo
            # capturable en el boundary mas amplio.
            logger.exception(
                "Notificación falló — backend plyer levantó excepción",
                extra={
                    "event": "notification.error",
                    "error": str(exc),
                    "exc_class": type(exc).__name__,
                    "title": notification.title,
                },
            )
            return

        logger.info(
            "Notificación enviada",
            extra={
                "event": "notification.finish",
                "title": notification.title,
            },
        )
