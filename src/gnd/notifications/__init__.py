"""Paquete notifications — notificaciones de escritorio (Fase 12b.2).

Implementacion real (``PlyerDesktopNotifier``) en ``plyer_notifier.py``;
formatter pura (``build_run_notification``) en ``run_formatter.py``.

Patrones respetados:
- Protocolo 1 (separacion models/domain): este modulo importa de
  ``models/`` y define un adapter que habla con el OS via ``plyer`` —
  nada de psutil/sqlite3/subprocess en los helpers de formato.
- Protocolo 6 (DI por constructor): ``PlyerDesktopNotifier`` recibe
  configuracion (app_name, timeout) en el wiring (composition_root) y
  se inyecta en MainWindow via kwargs opcionales.
- Protocolo 8 (import diferido): plyer se importa dentro del ``__init__``
  del adapter, no top-of-file — asi el adapter es robusto a fresh venv
  sin la dep sincronizada.
- Regla 11.3 (eventos estructurados): el adapter emite
  ``notification.start`` / ``notification.finish`` / ``notification.error``
  / ``notification.skip`` con namespace ``notification``.
- Regla 9.5 (YAGNI): no pre-construir un scheduler de notificaciones
  recurrentes (eso es 12b.3 Reportes). La notif es reactiva al evento
  de terminar un run.
"""

from gnd.notifications.plyer_notifier import PlyerDesktopNotifier
from gnd.notifications.run_formatter import build_run_notification

__all__ = ["PlyerDesktopNotifier", "build_run_notification"]
