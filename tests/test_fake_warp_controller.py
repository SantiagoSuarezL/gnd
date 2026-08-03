"""Tests del FakeWarpController (Fase 12b.4).

El fake se usa en tests del WarpComparisonUseCase y UI integration
cuando no queremos invocar warp-cli real. Cubrimos:
- Estado inicial configurable via constructor.
- `enable()` muta estado a connected=True y registra llamada.
- `disable()` muta estado a connected=False y registra llamada.
- Implementa el Protocol WarpController (runtime_checkable).
- Modos de fallo (`fail_on_*`) para testear error handling.
- `set_*` helpers permiten mutar estado entre llamadas.
"""

from __future__ import annotations

import pytest

from gnd.domain.fakes.fake_warp_controller import FakeWarpController
from gnd.domain.ports.warp_controller import WarpController, WarpError, WarpStatus


class TestFakeWarpController:
    def test_estado_inicial_disconnected(self) -> None:
        fake = FakeWarpController()
        status = fake.get_status()
        assert status.connected is False
        assert status.registration_status == "registered"
        assert status.connection_status == "disconnected"
        assert status.warp_plus is False

    def test_estado_inicial_connected(self) -> None:
        fake = FakeWarpController(initially_connected=True, warp_plus=True)
        status = fake.get_status()
        assert status.connected is True
        assert status.warp_plus is True

    def test_enable_muta_a_connected(self) -> None:
        fake = FakeWarpController()
        assert fake.get_status().connected is False
        result = fake.enable()
        assert result.connected is True
        assert result.connection_status == "connected"
        assert fake.get_status().connected is True

    def test_disable_muta_a_disconnected(self) -> None:
        fake = FakeWarpController(initially_connected=True)
        assert fake.get_status().connected is True
        result = fake.disable()
        assert result.connected is False
        assert result.connection_status == "disconnected"
        assert fake.get_status().connected is False

    def test_enable_registra_si_no_estaba_registrado(self) -> None:
        fake = FakeWarpController(initially_registered=False)
        result = fake.enable()
        assert result.registration_status == "registered"

    def test_disable_no_pierde_registro(self) -> None:
        fake = FakeWarpController(initially_connected=True, initially_registered=True)
        fake.disable()
        assert fake.get_status().registration_status == "registered"

    def test_registra_contadores_de_llamadas(self) -> None:
        fake = FakeWarpController()
        fake.get_status()  # 1
        fake.enable()  # enable() + get_status() = 2
        fake.disable()  # disable() + get_status() = 3
        fake.get_status()  # 4
        fake.get_status()  # 5
        assert fake.status_calls == 5
        assert fake.enable_calls == 1
        assert fake.disable_calls == 1

    def test_enable_fail_on_enable_lanza_warp_error(self) -> None:
        fake = FakeWarpController(fail_on_enable=True)
        with pytest.raises(WarpError):
            fake.enable()

    def test_disable_fail_on_disable_lanza_warp_error(self) -> None:
        fake = FakeWarpController(fail_on_disable=True)
        with pytest.raises(WarpError):
            fake.disable()

    def test_get_status_fail_on_status_lanza_warp_error(self) -> None:
        fake = FakeWarpController(fail_on_status=True)
        with pytest.raises(WarpError):
            fake.get_status()

    def test_set_connected_entre_llamadas(self) -> None:
        fake = FakeWarpController()
        fake.set_connected(True)
        assert fake.get_status().connected is True
        fake.set_connected(False)
        assert fake.get_status().connected is False

    def test_set_registered_entre_llamadas(self) -> None:
        fake = FakeWarpController()
        fake.set_registered(True)
        assert fake.get_status().registration_status == "registered"

    def test_set_warp_plus_entre_llamadas(self) -> None:
        fake = FakeWarpController()
        fake.set_warp_plus(True)
        assert fake.get_status().warp_plus is True

    def test_enable_result_custom(self) -> None:
        custom = WarpStatus(
            connected=True,
            registration_status="registered",
            connection_status="connected",
            warp_plus=True,
        )
        fake = FakeWarpController(enable_result=custom)
        result = fake.enable()
        assert result is custom
        assert result.warp_plus is True

    def test_disable_result_custom(self) -> None:
        custom = WarpStatus(
            connected=False,
            registration_status="registered",
            connection_status="disconnected",
            warp_plus=False,
        )
        fake = FakeWarpController(disable_result=custom)
        result = fake.disable()
        assert result is custom

    def test_implementa_protocol_warp_controller(self) -> None:
        fake = FakeWarpController()
        assert isinstance(fake, WarpController)

    def test_enable_preserva_warp_plus(self) -> None:
        """enable() no debe perder warp_plus si ya estaba activo."""
        fake = FakeWarpController(warp_plus=True)
        fake.enable()
        assert fake.get_status().warp_plus is True

    def test_set_fail_flags_en_runtime(self) -> None:
        fake = FakeWarpController()
        fake.set_fail_on_enable(True)
        with pytest.raises(WarpError):
            fake.enable()
        fake.set_fail_on_enable(False)
        # Ahora debe funcionar
        fake.enable()
        assert fake.get_status().connected is True

    def test_disponible_es_true(self) -> None:
        """Fake siempre está disponible (a diferencia del RealWarpController)."""
        fake = FakeWarpController()
        assert fake.available is True

    # --- Regla 12b.4.2: modo/protocolo del túnel ---

    def test_estado_inicial_con_mode_y_protocol(self) -> None:
        fake = FakeWarpController(mode="warp", tunnel_protocol="WireGuard")
        status = fake.get_status()
        assert status.mode == "warp"
        assert status.tunnel_protocol == "WireGuard"

    def test_set_mode_registra_llamada(self) -> None:
        fake = FakeWarpController()
        fake.set_mode("proxy")
        assert fake.set_mode_calls == ["proxy"]
        assert fake.get_status().mode == "proxy"

    def test_set_tunnel_protocol_registra_llamada(self) -> None:
        fake = FakeWarpController()
        fake.set_tunnel_protocol("MASQUE")
        assert fake.set_tunnel_protocol_calls == ["MASQUE"]
        assert fake.get_status().tunnel_protocol == "MASQUE"

    def test_set_mode_fail_lanza_warp_error(self) -> None:
        fake = FakeWarpController(fail_on_set_mode=True)
        with pytest.raises(WarpError):
            fake.set_mode("proxy")

    def test_set_tunnel_protocol_fail_lanza_warp_error(self) -> None:
        fake = FakeWarpController(fail_on_set_tunnel_protocol=True)
        with pytest.raises(WarpError):
            fake.set_tunnel_protocol("MASQUE")

    def test_set_mode_state_helper_no_registra_call(self) -> None:
        """set_mode_state muta el estado interno sin registrar como llamada
        (para simular que el usuario cambió el modo a mano, no via API)."""
        fake = FakeWarpController()
        fake.set_mode_state("WireGuard_user_default")
        assert fake.set_mode_calls == []
        assert fake.get_status().mode == "WireGuard_user_default"
