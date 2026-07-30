"""Fake in-memory de WarpController para tests (Fase 12b.4).

Implementa el Protocol `WarpController` sin invocar subprocess real.
Permite simular cualquier secuencia de estados: conectado/desconectado,
registrado/no registrado, WARP+, errores controlados.

Cumple contrato: métodos no lanzan excepción salvo que el test configure
`fail_on_*` para forzar WarpError (simular fallos de warp-cli).
"""

from __future__ import annotations

from gnd.domain.ports.warp_controller import WarpError, WarpStatus


class FakeWarpController:
    """Fake de WarpController con estado programable.

    Constructor kwargs:
    - initially_connected: estado inicial de WARP (default False).
    - initially_registered: estado de registro inicial (default True).
    - warp_plus: WARP+ activo inicialmente (default False).
    - fail_on_enable/disable/status: forzar WarpError en esos métodos.
    - enable_result/disable_result: WarpStatus custom para esos métodos.

    Atributos públicos para aserciones:
    - enable_calls: contador de llamadas a enable().
    - disable_calls: contador de llamadas a disable().
    - status_calls: contador de llamadas a get_status().
    """

    def __init__(
        self,
        *,
        initially_connected: bool = False,
        initially_registered: bool = True,
        warp_plus: bool = False,
        fail_on_enable: bool = False,
        fail_on_disable: bool = False,
        fail_on_status: bool = False,
        enable_result: WarpStatus | None = None,
        disable_result: WarpStatus | None = None,
    ) -> None:
        self._connected = initially_connected
        self._registered = initially_registered
        self._warp_plus = warp_plus
        self._fail_on_enable = fail_on_enable
        self._fail_on_disable = fail_on_disable
        self._fail_on_status = fail_on_status
        self._enable_result = enable_result
        self._disable_result = disable_result
        # Contadores de llamadas
        self.enable_calls = 0
        self.disable_calls = 0
        self.status_calls = 0

    def get_status(self) -> WarpStatus:
        self.status_calls += 1
        if self._fail_on_status:
            raise WarpError("fake get_status error")
        reg_status = "registered" if self._registered else "unregistered"
        conn_status = "connected" if self._connected else "disconnected"
        return WarpStatus(
            connected=self._connected,
            registration_status=reg_status,
            connection_status=conn_status,
            warp_plus=self._warp_plus,
        )

    def enable(self) -> WarpStatus:
        self.enable_calls += 1
        if self._fail_on_enable:
            raise WarpError("fake enable error")
        if self._enable_result is not None:
            return self._enable_result
        if not self._registered:
            self._registered = True
        self._connected = True
        return self.get_status()

    def disable(self) -> WarpStatus:
        self.disable_calls += 1
        if self._fail_on_disable:
            raise WarpError("fake disable error")
        if self._disable_result is not None:
            return self._disable_result
        self._connected = False
        return self.get_status()

    # --- Helpers para tests que quieran mutar estado entre llamadas ---

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def set_registered(self, registered: bool) -> None:
        self._registered = registered

    def set_warp_plus(self, warp_plus: bool) -> None:
        self._warp_plus = warp_plus

    def set_fail_on_enable(self, fail: bool) -> None:
        self._fail_on_enable = fail

    def set_fail_on_disable(self, fail: bool) -> None:
        self._fail_on_disable = fail

    def set_fail_on_status(self, fail: bool) -> None:
        self._fail_on_status = fail

    # Property para compatibilidad con RealWarpController.available
    @property
    def available(self) -> bool:
        return True
