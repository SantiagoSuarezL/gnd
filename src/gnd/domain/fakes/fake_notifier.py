"""Fake in-memory DesktopNotifier para tests sin desktop (Fase 12b.2).

Mismo patron que los demas fakes (FakePingRunner, FakeDnsResolver, ...):
- No toca el OS / no abre ventanas / no requiere plyer.
- Guarda las notificaciones en ``self.notifications`` para asserts en
  tests (`assert fake.notifications[0].title == ...`).
- Implementa el Protocol ``DesktopNotifier`` implicitamente (duck typing
  en Python — no herencia explicita, basta con tener ``notify``).
"""

from gnd.models.notification import DesktopNotification


class FakeDesktopNotifier:
    """DesktopNotifier que acumula notificaciones en memoria.

    Uso tipico en tests:
        notifier = FakeDesktopNotifier()
        notifier.notify(DesktopNotification(title="GND — OK", message="..."))
        assert len(notifier.notifications) == 1
        assert notifier.notifications[0].title == "GND — OK"
    """

    def __init__(self) -> None:
        self.notifications: list[DesktopNotification] = []

    def notify(self, notification: DesktopNotification) -> None:
        # Registro inmutable (el caller podria mutar el mismo objeto despues
        # — guardamos una copia shallow via dataclass replace no aporta nada
        # porque es frozen; solo referenciamos).
        self.notifications.append(notification)
