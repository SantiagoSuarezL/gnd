"""Puerto DesktopNotifier — emite notificaciones nativas del OS (Fase 12b.2).

PRD §7 could-have + IMPLEMENTATION_PLAN.md 12b.2. Implementacion real en
``notifications/plyer_notifier.py`` (wrap de ``plyer.notification``).
Fake en ``domain/fakes/fake_notifier.py`` para tests sin desktop.

EP §1.2: como todo Protocol del dominio, la implementacion NUNCA debe
lanzar excepciones a la UI. Si el backend de notificaciones esta
ausente (headless/CI, lib faltante, OS sin soporte), el adapter captura
todo y lo loguea via ``event="notification.error"`` (Regla 11.3); el
caller (MainWindow) confia en el contrato y no hace try/except.

El input es un ``DesktopNotification`` (value object del dominio con
``title`` y ``message`` ya validados no vacios) — el adapter notiene que
re-validar ni construir strings, solo mapear campos al backend.
"""

from typing import Protocol, runtime_checkable

from gnd.models.notification import DesktopNotification


@runtime_checkable
class DesktopNotifier(Protocol):
    """Emite una notificacion de escritorio nativa del OS.

    Implementaciones conocidas:
    - ``PlyerDesktopNotifier``: wrap de ``plyer.notification.notify``.
      Multiplataforma (Windows toast, Linux Freedesktop, macOS
      NSUserNotification). Convierte title/message a kwargs del backend.
    - ``FakeDesktopNotifier``: guarda en lista, no toca OS.

    El contrato garantiza que ``notify`` nunca lanza; cualquier fallo
    del backend se captura y loguea en el adapter.
    """

    def notify(self, notification: DesktopNotification) -> None:
        """Emite ``notification`` via el backend del OS.

        Nunca lanza excepciones a la UI (contrato EP §1.2). Errores del
        backend se capturan y loguean via ``event="notification.error"``.
        """
        ...
