"""Fake in-memory de WarpController para tests (Fase 12b.4).

Implementa el Protocol `WarpController` sin invocar subprocess real.
Permite simular cualquier secuencia de estados: conectado/desconectado,
registrado/no registrado, WARP+, modo (warp/proxy/doh), protocolo del
túnel (MASQUE/WireGuard), errores controlados.

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
    - mode: modo general inicial (default "warp"). None = no detectable
      (simula falla de parseo en settings list — Regla 12b.4.2 fail-safe).
    - tunnel_protocol: protocolo del túnel inicial (default None). Ej.
      "WireGuard" (lo que el usuario llama "UDP"), "MASQUE".
    - fail_on_enable/disable/status: forzar WarpError en esos métodos.
    - fail_on_set_mode/set_tunnel_protocol: forzar WarpError al setear.
    - enable_result/disable_result: WarpStatus custom para esos métodos.

    Atributos públicos para aserciones:
    - enable_calls, disable_calls, status_calls: contadores.
    - set_mode_calls: list[str] de modos seteados (en orden).
    - set_tunnel_protocol_calls: list[str] de protocolos seteados (orden).
    """

    def __init__(
        self,
        *,
        initially_connected: bool = False,
        initially_registered: bool = True,
        warp_plus: bool = False,
        mode: str | None = "warp",
        tunnel_protocol: str | None = None,
        fail_on_enable: bool = False,
        fail_on_disable: bool = False,
        fail_on_status: bool = False,
        fail_on_set_mode: bool = False,
        fail_on_set_tunnel_protocol: bool = False,
        enable_result: WarpStatus | None = None,
        disable_result: WarpStatus | None = None,
    ) -> None:
        self._connected = initially_connected
        self._registered = initially_registered
        self._warp_plus = warp_plus
        self._mode = mode
        self._tunnel_protocol = tunnel_protocol
        self._fail_on_enable = fail_on_enable
        self._fail_on_disable = fail_on_disable
        self._fail_on_status = fail_on_status
        self._fail_on_set_mode = fail_on_set_mode
        self._fail_on_set_proto = fail_on_set_tunnel_protocol
        self._enable_result = enable_result
        self._disable_result = disable_result
        # Contadores de llamadas
        self.enable_calls = 0
        self.disable_calls = 0
        self.status_calls = 0
        self.set_mode_calls: list[str] = []
        self.set_tunnel_protocol_calls: list[str] = []

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
            mode=self._mode,
            tunnel_protocol=self._tunnel_protocol,
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

    def set_mode(self, mode: str) -> None:
        self.set_mode_calls.append(mode)
        if self._fail_on_set_mode:
            raise WarpError(f"fake set_mode({mode}) error")
        self._mode = mode

    def set_tunnel_protocol(self, protocol: str) -> None:
        self.set_tunnel_protocol_calls.append(protocol)
        if self._fail_on_set_proto:
            raise WarpError(f"fake set_tunnel_protocol({protocol}) error")
        self._tunnel_protocol = protocol

    # --- Helpers para tests que quieran mutar estado entre llamadas ---

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def set_registered(self, registered: bool) -> None:
        self._registered = registered

    def set_warp_plus(self, warp_plus: bool) -> None:
        self._warp_plus = warp_plus

    def set_mode_state(self, mode: str | None) -> None:
        """Test helper: muta el modo del estado interno (NO registra call)."""
        self._mode = mode

    def set_tunnel_protocol_state(self, protocol: str | None) -> None:
        """Test helper: muta el protocolo del estado interno (NO registra call)."""
        self._tunnel_protocol = protocol

    def set_fail_on_enable(self, fail: bool) -> None:
        self._fail_on_enable = fail

    def set_fail_on_disable(self, fail: bool) -> None:
        self._fail_on_disable = fail

    def set_fail_on_status(self, fail: bool) -> None:
        self._fail_on_status = fail

    def set_fail_on_set_mode(self, fail: bool) -> None:
        self._fail_on_set_mode = fail

    def set_fail_on_set_tunnel_protocol(self, fail: bool) -> None:
        self._fail_on_set_proto = fail

    # Property para compatibilidad con RealWarpController.available.
    # Devuelve False si ``fail_on_status`` está activo (simula warp-cli
    # con fallos de status — el controller se considera no-disponible
    # para que el use case salte la comparación en vez de reventar).
    @property
    def available(self) -> bool:
        return not self._fail_on_status
