"""Fake ``DatabaseConnectionFactory`` para tests sin disco.

Patrones de uso (todos viven en el mismo hilo del test):

1. ``FakeDatabaseConnectionFactory()`` — devuelve una ``sqlite3.connect(":memory:")``
   nueva vacia por cada call (schema aplicado). Sirve para tests que quier
   validar el flujo de ``RunFullDiagnostics`` con escritura real SQLite pero
   sin persistir entre runs.

2. ``FakeDatabaseConnectionFactory(conn)`` — devuelve SIEMPRE la misma conn
   compartida. Util cuando el test necesita sembrar datos en una conn y
   despuas pedir otra conexion al factory para validar el baseline. Solo
   valido dentro del mismo hilo (sqlite3 check_same_thread por defecto).
"""

from __future__ import annotations

import sqlite3

from gnd.database.schema import ensure_schema


class FakeDatabaseConnectionFactory:
    """Factory que devuelve ``sqlite3.Connection`` para tests.

    A diferencia de ``SqliteConnectionFactory``, acepta una conn precreada
    para reusar. Si no se pasa ninguna, abre ``:memory:`` nueva por call.

    Implementa ``Protocol DatabaseConnectionFactory`` (Liskov: el
    ``RunFullDiagnostics`` la consume sin notar la diferencia con la real).
    """

    def __init__(self, shared: sqlite3.Connection | None = None) -> None:
        """Args:
        shared: si no es None, ``create_connection()`` devuelve siempre
            esa misma. Si es None, abre ``:memory:`` nueva por call.
        """
        self._shared = shared
        self.calls = 0

    def create_connection(self) -> sqlite3.Connection:
        self.calls += 1
        if self._shared is not None:
            # No reconfiguramos row_factory en una conn que el caller
            # pudo compartir con otros tests / repos; si la caller la
            # configuro (o no) se respeta.
            return self._shared
        conn = sqlite3.connect(":memory:")
        # Igual que SqliteConnectionFactory real: row_factory=Row para que
        # ``row["col"]`` funcione.
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        return conn
