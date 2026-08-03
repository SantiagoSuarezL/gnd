"""Tests de ``GameflowSession`` (Fase 14.0a).

Cubre:
- Constructor válido (todos los combos de None/presente consistentes).
- Invariante ``phase`` no vacío.
- Invariante ``region_tag`` None | str no vacío (``""`` rechazado).
- Invariante ``server_ip`` None | str no vacío.
- Invariante ``server_port`` rango [1, 65535] si está presente.
- Consistencia: ``server_ip`` y ``server_port`` ambos o ninguno.
- ``has_active_game_server`` según estado populado.
"""

import pytest

from gnd.models.gameflow_session import GameflowSession


class TestGameflowSession:
    def test_lobby_phase_sin_game_server(self) -> None:
        """Phase Lobby: sin region_tag, sin serverIp/Port (caso Lobby)."""
        s = GameflowSession(
            phase="Lobby", region_tag=None, server_ip=None, server_port=None
        )
        assert s.phase == "Lobby"
        assert s.region_tag is None
        assert not s.has_active_game_server()

    def test_champselect_con_region_tag_sin_server(self) -> None:
        """ChampSelect: ya hay platformId pero no hay serverIp todavía."""
        s = GameflowSession(
            phase="ChampSelect",
            region_tag="LA1",
            server_ip=None,
            server_port=None,
        )
        assert s.region_tag == "LA1"
        assert not s.has_active_game_server()

    def test_inprogress_con_game_server(self) -> None:
        """InProgress: serverIp + serverPort poblados."""
        s = GameflowSession(
            phase="InProgress",
            region_tag="LA1",
            server_ip="138.0.12.10",
            server_port=5000,
        )
        assert s.has_active_game_server()
        assert s.server_ip == "138.0.12.10"
        assert s.server_port == 5000


class TestGameflowSessionInvariante:
    def test_phase_vacio_rechaza(self) -> None:
        with pytest.raises(ValueError, match="phase no puede ser vacío"):
            GameflowSession(phase="", region_tag=None, server_ip=None, server_port=None)

    def test_region_tag_vacio_rechaza(self) -> None:
        with pytest.raises(
            ValueError, match="region_tag debe ser None o un str no vacío"
        ):
            GameflowSession(
                phase="Lobby", region_tag="", server_ip=None, server_port=None
            )

    def test_server_ip_vacio_rechaza(self) -> None:
        with pytest.raises(
            ValueError, match="server_ip debe ser None o un str no vacío"
        ):
            GameflowSession(
                phase="InProgress",
                region_tag=None,
                server_ip="",
                server_port=5000,
            )

    def test_server_port_fuera_de_rango_rechaza(self) -> None:
        with pytest.raises(ValueError, match=r"server_port debe estar en \[1, 65535\]"):
            GameflowSession(
                phase="InProgress", region_tag=None, server_ip="1.2.3.4", server_port=0
            )
        with pytest.raises(ValueError, match=r"server_port debe estar en \[1, 65535\]"):
            GameflowSession(
                phase="InProgress",
                region_tag=None,
                server_ip="1.2.3.4",
                server_port=65536,
            )

    def test_inconsistencia_ip_sin_port_rechaza(self) -> None:
        with pytest.raises(
            ValueError,
            match="server_ip y server_port deben ambos estar presentes o ambos None",
        ):
            GameflowSession(
                phase="InProgress",
                region_tag=None,
                server_ip="1.2.3.4",
                server_port=None,
            )

    def test_inconsistencia_port_sin_ip_rechaza(self) -> None:
        with pytest.raises(
            ValueError,
            match="server_ip y server_port deben ambos estar presentes o ambos None",
        ):
            GameflowSession(
                phase="InProgress",
                region_tag=None,
                server_ip=None,
                server_port=5000,
            )
