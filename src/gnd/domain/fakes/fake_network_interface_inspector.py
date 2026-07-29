"""Fake in-memory NetworkInterfaceInspector para tests sin red (Fase 12a.3)."""

from gnd.models.network_interface import InterfaceType, NetworkInterfaceSnapshot


class FakeNetworkInterfaceInspector:
    """Inspector que devuelve snapshots pre-configurados.

    Uso típico en tests:
        inspector = FakeNetworkInterfaceInspector()
        inspector.set_snapshot(NetworkInterfaceSnapshot(type=WIFI, ...))
        snap = inspector.inspect()

    Registra las llamadas en `self.calls` para asserts de integración
    sobre orquestadores (RunFullDiagnostics).
    """

    def __init__(self) -> None:
        self._snapshot: NetworkInterfaceSnapshot | None = None
        self.calls: list[dict] = []

    def set_snapshot(self, snapshot: NetworkInterfaceSnapshot) -> None:
        self._snapshot = snapshot

    def inspect(
        self,
        *,
        default_route_iface_hint: str | None = None,
    ) -> NetworkInterfaceSnapshot:
        self.calls.append({"default_route_iface_hint": default_route_iface_hint})
        if self._snapshot is not None:
            return self._snapshot
        # Fallback: tipo OTHER con nombre "fake-if" + error informativo
        return NetworkInterfaceSnapshot(
            type=InterfaceType.OTHER,
            name="fake-if",
            is_default_route=True,
            wifi_ssid=None,
            wifi_signal_dbm=None,
            error="FakeNetworkInterfaceInspector sin snapshot configurado",
        )
