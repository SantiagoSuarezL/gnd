"""Fake in-memory ``LcuClient`` para tests sin cliente de LoL corriendo.

Fase 14.0a. Permite testear el cascada de
``LeagueOfLegendsModule.detect_active_server`` (sub-fase 14.0d) sin
abrir HTTP localhost. El fake es programable: el caller setea el
``GameflowSession`` que quiere devolver (o ``None`` para simular "LCU
no respondió").
"""

from __future__ import annotations

from gnd.models.gameflow_session import GameflowSession
from gnd.models.lockfile_data import LockfileData


class FakeLcuClient:
    """``LcuClient`` programable para tests.

    Defaults backwards-compat: simula "LCU no respondió" (``None``) —
    el cascada cae al ``ConnectionInspector`` histórico. El caller
    programa el caso que quiere probar via ``set_result``.

    Attributes:
        get_session_calls: registros de cada llamada (con el
            ``LockfileData`` recibido) para asserts sobre invocación
            y sobre qué lockfile se usó en cada call.
    """

    def __init__(self) -> None:
        self._result: GameflowSession | None = None
        self.get_session_calls: list[LockfileData] = []

    def set_result(self, result: GameflowSession | None) -> None:
        """Programa el resultado de la próxima llamada a ``get_gameflow_session``."""
        self._result = result

    def get_gameflow_session(self, lockfile: LockfileData) -> GameflowSession | None:
        self.get_session_calls.append(lockfile)
        return self._result
