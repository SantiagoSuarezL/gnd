"""Puerto ConnectionInspector — inspecciona conexiones de proceso.

Diseñado para la detección del servidor de partida activo
(TECHNICAL_SPEC.md §2.2). Interface Segregation (ENGINEERING_PRINCIPLES.md §2.I):
es una interfaz separada de PingRunner — un componente que solo necesita
pinguear no depende de la capacidad de enumerar procesos.
"""

from typing import Protocol, runtime_checkable

from gnd.models.active_game_server import ActiveGameServerInfo


@runtime_checkable
class ConnectionInspector(Protocol):
    """Detecta el servidor de partida activo escaneando conexiones UDP de procesos.

    Devuelve None si no hay partida activa o si no se pudo enumerar
    (ej. AccessDenied en Windows sin privilegios elevados — el caller decide
    cómo presentarlo, nunca es excepción no controlada, EP §1.2).
    """

    def detect_active_game_server(
        self,
        process_names: set[str],
    ) -> ActiveGameServerInfo | None: ...
