"""Sub-paquete Riot — diagnostico especifico de League of Legends.

TECHNICAL_SPEC.md §2.2 y ARCHITECTURE.md §4. El componente distintivo del
proyecto: distingue la infraestructura publica Riot (Cloudflare/Akamai)
del servidor de partida activo real (IP dinamica por matchmaking).

- `active_game_server_detector`: camino primario via enumeracion de
  conexiones UDP del proceso del juego (psutil). Implementa
  `Protocol ConnectionInspector`.
- `live_client_api`: confirmacion cruzada opcional via
  https://127.0.0.1:2999/liveclientdata/ (expuesta solo durante partida
  activa por el cliente del juego). Complemento, no reemplazo del primario.

SRP (ENGINEERING_PRINCIPLES.md §2.S): `diagnostics/riot/public_endpoint_probe`
(inexistente aun) y `active_game_server_detector` son archivos/clases
separados — nunca un unico `RiotDiagnostics` monolitico.
"""

from gnd.diagnostics.riot.active_game_server_detector import (
    ActiveGameServerDetector,
    is_public_ipv4,
)
from gnd.diagnostics.riot.live_client_api import LiveClientApi

__all__ = [
    "ActiveGameServerDetector",
    "LiveClientApi",
    "is_public_ipv4",
]
