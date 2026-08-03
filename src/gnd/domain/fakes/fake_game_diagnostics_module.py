"""Fake in-memory GameDiagnosticsModule para tests sin config/inspector real.

Fase 13.1: permite testear el orquestador ``RunFullDiagnostics`` (cuando
migre a consumir un ``GameDiagnosticsModule`` en Fase 13.2) y cualquier
composición superior sin depender de ``GndSettings`` ni
``ConnectionInspector`` real. El fake es programable: el caller setea
``public_endpoints``/``process_names``/``detect_active_server`` y el fake
los reproduce deterministamente, registrando las llamadas.
"""

from __future__ import annotations

from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint


class FakeGameDiagnosticsModule:
    """GameDiagnosticsModule programable para tests.

    Defaults backwards-compat (Fase 13.2): simula un módulo sin endpoints
    públicos, sin process_names, y ``detect_active_server`` devuelve
    ``None`` (feature apagada). El caller explicitamente programa el
    estado que quiera probar — no hay behavior implícito.
    """

    def __init__(
        self,
        *,
        public_endpoints_result: list[GameEndpoint] | None = None,
        process_names_result: set[str] | None = None,
        detect_result: ActiveGameServerInfo | None = None,
        game_server_provider_result: str = "game_server",
    ) -> None:
        self._public_endpoints: list[GameEndpoint] = list(public_endpoints_result or [])
        self._process_names: set[str] = set(process_names_result or set())
        self._detect_result: ActiveGameServerInfo | None = detect_result
        self._game_server_provider: str = game_server_provider_result
        # Registros de llamadas para asserts en tests.
        self.public_endpoints_calls: int = 0
        self.process_names_calls: int = 0
        self.detect_calls: int = 0
        self.game_server_provider_calls: int = 0

    # --- Setters para programar el estado del fake ------------------------

    def set_public_endpoints(self, endpoints: list[GameEndpoint]) -> None:
        self._public_endpoints = list(endpoints)

    def set_process_names(self, names: set[str]) -> None:
        self._process_names = set(names)

    def set_detect_result(self, result: ActiveGameServerInfo | None) -> None:
        self._detect_result = result

    def set_game_server_provider(self, provider: str) -> None:
        self._game_server_provider = provider

    # --- GameDiagnosticsModule --------------------------------------------

    def public_endpoints(self) -> list[GameEndpoint]:
        self.public_endpoints_calls += 1
        return list(self._public_endpoints)

    def process_names(self) -> set[str]:
        self.process_names_calls += 1
        return set(self._process_names)

    def detect_active_server(self) -> ActiveGameServerInfo | None:
        self.detect_calls += 1
        return self._detect_result

    def game_server_provider(self) -> str:
        self.game_server_provider_calls += 1
        return self._game_server_provider
