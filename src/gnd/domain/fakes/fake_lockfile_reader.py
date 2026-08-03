"""Fake in-memory ``LockfileReader`` para tests sin filesystem.

Fase 14.0a. Permite testear el cascada de
``LeagueOfLegendsModule.detect_active_server`` (sub-fase 14.0d) sin
tocar disco real. El fake es programable: el caller setea el
``LockfileData`` que quiere devolver (o ``None`` para simular "LoL no
corriendo") y registra las llamadas para asserts.
"""

from __future__ import annotations

from gnd.models.lockfile_data import LockfileData


class FakeLockfileReader:
    """``LockfileReader`` programable para tests.

    Defaults backwards-compat: simula "no hay lockfile" (``None``)
    — el cascada en ``LeagueOfLegendsModule.detect_active_server``
    cae al ``ConnectionInspector`` histórico. El caller explicitamente
    programa el estado que quiere probar via ``set_result``.

    Attributes:
        read_calls: contador de llamadas a ``read`` para tests de
            invocación (cuántas veces se consultó el lockfile en una
            corrida del orquestador).
    """

    def __init__(self) -> None:
        self._result: LockfileData | None = None
        self.read_calls: int = 0

    def set_result(self, result: LockfileData | None) -> None:
        """Programa el resultado de la próxima llamada a ``read``.

        ``None`` simula "lockfile no disponible". Un ``LockfileData``
        válido simula "LoL corriendo con este port/password".
        """
        self._result = result

    def read(self) -> LockfileData | None:
        self.read_calls += 1
        return self._result
