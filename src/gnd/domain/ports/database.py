"""Puerto DatabaseConnectionFactory — provee conexiones SQLite por hilo.

Resuelve el defecto detectado en Fase 9 (sqlite3.ProgrammingError por
uso de conexion cross-thread): sqlite3 exige que una Connection se use
exclusivamente desde el hilo donde fue creada. La solucion arquitectural
(Regla de Oro 9.1) es NO compartir una unica Connection entre el hilo
principal (composition_root) y el worker thread del controller — en su
lugar, la factory crea una conexion nueva dentro del hilo que la necesita.

ARCHITECTURE.md §2 (Infrastructure). Implementacion real en database/
(SqliteConnectionFactory); fakes devuelven conexiones :memory: o mocks.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class DatabaseConnectionFactory(Protocol):
    """Provee una ``sqlite3.Connection`` fresca lista para usar.

    Cada call a ``create_connection()`` devuelve una conexion nueva,
    creada en el hilo del caller. El caller es dueno de cerrarla
    (``conn.close()``) o de dejarla morir con el hilo. La factory NO
    cachea conexiones: si queres una, pedis una.

    Regla de Oro 9.1: nunca compartirla entre hilos. Una corrida de
    ``RunFullDiagnostics`` debe llamar ``create_connection()`` una
    sola vez al inicio del ``execute()`` (en el worker thread) y usarla
    para compute_baseline + save_run.
    """

    def create_connection(self) -> object: ...
