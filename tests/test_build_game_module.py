"""Tests del builder ``build_game_module`` (Fase 13.2b).

Verifican el mapping ``settings.game_detection.active_game`` ->
implementación concreta en ``diagnostics/games/``:
  - Default ``"league_of_legends"`` -> ``LeagueOfLegendsModule``.
  - Valor no reconocido -> ``ValueError`` fail-fast (config corrupta,
    no runtime de red). EP §1.2 no aplica: es config estática.
  - El módulo construido delega ``detect_active_server`` al
    ``ConnectionInspector`` inyectado (no instancea psutil real).

No tocan config global ni psutil: el ``ConnectionInspector`` se inyecta
como un fake por duck typing.
"""

from __future__ import annotations

import pytest

from gnd.composition_root import build_game_module
from gnd.diagnostics.games.league_of_legends import LeagueOfLegendsModule
from gnd.domain.ports.game_diagnostics_module import GameDiagnosticsModule


class _FakeInspector:
    """ConnectionInspector por duck typing (no usa psutil)."""

    def __init__(self) -> None:
        self.calls: list[set[str]] = []

    def detect_active_game_server(self, process_names: set[str]):
        self.calls.append(set(process_names))
        return None


class TestBuildGameModuleDefault:
    """Default config (league_of_legends) construye LeagueOfLegendsModule."""

    def test_devuelve_league_of_legends_module_por_default(self) -> None:
        # El singleton de config carga defaults -> active_game = "league_of_legends".
        module = build_game_module(connection_inspector=_FakeInspector())
        assert isinstance(module, LeagueOfLegendsModule)

    def test_el_modulo_cumple_el_protocol(self) -> None:
        module = build_game_module(connection_inspector=_FakeInspector())
        assert isinstance(module, GameDiagnosticsModule)

    def test_el_modulo_delega_detect_al_inspector_inyectado(self) -> None:
        inspector = _FakeInspector()
        module = build_game_module(connection_inspector=inspector)
        # Llamar detect_active_server debe pasar process_names al inspector.
        module.detect_active_server()
        assert len(inspector.calls) == 1
        # El process_names viene de config.game_detection.process_names
        # (default ["League of Legends.exe"]).
        assert "League of Legends.exe" in inspector.calls[0]

    def test_game_server_provider_es_riot_game_server(self) -> None:
        # LoL mantiene el provider histórico (DoD: no tocar analysis).
        module = build_game_module(connection_inspector=_FakeInspector())
        assert module.game_server_provider() == "riot_game_server"


class TestBuildGameModuleUnknownGame:
    """Config con un juego no reconocido falla fail-fast al arrancar."""

    def test_juego_desconocido_lanza_value_error_con_mensaje_claro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Forzamos un active_game no reconocido mutando el singleton de
        # config en runtime (simula config.toml con un valor raro).
        from gnd.config import get_settings

        original = get_settings()
        original_game = original.game_detection.active_game
        try:
            monkeypatch.setattr(original.game_detection, "active_game", "starcraft2")
            with pytest.raises(ValueError) as exc_info:
                build_game_module(connection_inspector=_FakeInspector())
            assert "starcraft2" in str(exc_info.value)
            assert "league_of_legends" in str(exc_info.value)
        finally:
            monkeypatch.setattr(original.game_detection, "active_game", original_game)
