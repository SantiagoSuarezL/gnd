"""Fake in-memory ConnectionInspector para tests sin psutil real."""

from gnd.models.active_game_server import ActiveGameServerInfo


class FakeConnectionInspector:
    """ConnectionInspector que devuelve servidor activo pre-configurado."""

    def __init__(self) -> None:
        self._result: ActiveGameServerInfo | None = None
        self.calls: list[dict] = []

    def set_result(self, result: ActiveGameServerInfo | None) -> None:
        self._result = result

    def detect_active_game_server(
        self,
        process_names: set[str] | None = None,
    ) -> ActiveGameServerInfo | None:
        self.calls.append({"process_names": process_names})
        return self._result
