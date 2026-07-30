"""Tests del FakeDesktopNotifier (Fase 12b.2).

El fake se usa en MainWindow smoke tests y events de integracion cuando no
queremos abrir toasts reales. Cubrimos:
- ``notify`` acumula el DesktopNotification en ``self.notifications`` (lista).
- Múltiples notify preservan orden (append al final).
- Implementa el Protocol DesktopNotifier (runtime_checkable).
- La lista es mutable (puede vaciarse para reuso entre tests).
"""

from __future__ import annotations

from gnd.domain.fakes import FakeDesktopNotifier
from gnd.domain.ports.notifier import DesktopNotifier
from gnd.models.notification import DesktopNotification


class TestFakeDesktopNotifier:
    def test_notify_vacio_inicialmente(self) -> None:
        n = FakeDesktopNotifier()
        assert n.notifications == []

    def test_notify_acumula_un_elemento(self) -> None:
        n = FakeDesktopNotifier()
        msg = DesktopNotification(title="t", message="m")
        n.notify(msg)
        assert len(n.notifications) == 1
        assert n.notifications[0] is msg

    def test_notify_acumula_multiples_preservando_orden(self) -> None:
        n = FakeDesktopNotifier()
        m1 = DesktopNotification(title="a", message="A")
        m2 = DesktopNotification(title="b", message="B")
        m3 = DesktopNotification(title="c", message="C")
        n.notify(m1)
        n.notify(m2)
        n.notify(m3)
        assert n.notifications == [m1, m2, m3]
        assert n.notifications[0].title == "a"
        assert n.notifications[2].title == "c"

    def test_implementa_protocol_desktop_notifier(self) -> None:
        n = FakeDesktopNotifier()
        assert isinstance(n, DesktopNotifier)

    def test_lista_es_mutable_para_reuso(self) -> None:
        n = FakeDesktopNotifier()
        n.notify(DesktopNotification(title="a", message="A"))
        n.notifications.clear()
        assert n.notifications == []
        # Reuso: nuevo notify entra limpio.
        n.notify(DesktopNotification(title="b", message="B"))
        assert len(n.notifications) == 1

    def test_notify_no_lanza_nunca(self) -> None:
        """El fake nunca falla — misión del contrato del Protocol."""
        n = FakeDesktopNotifier()
        n.notify(DesktopNotification(title="t", message="m"))
        n.notify(DesktopNotification(title="tt", message="mm"))
        # Llegamos acá sin excepción.
        assert len(n.notifications) == 2
