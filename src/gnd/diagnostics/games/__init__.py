"""Sub-paquete games — módulos de diagnóstico por juego (Fase 13).

ARCHITECTURE.md §7. Cada juego implementa ``GameDiagnosticsModule`` (Protocol
de ``domain/ports/game_diagnostics_module.py``). Agregar un juego nuevo es
mayormente contenido dentro de ``games/<nuevo_juego>.py`` — el orquestador
(``RunFullDiagnostics``), ``analysis/``, ``recommendations/`` y ``database/``
no se tocan.

Registro de módulos:
  - ``league_of_legends``: LeagueOfLegendsModule — el primero. Envuelve la
    lógica Riot existente (``targets.riot_public`` + ``game_detection.process_names``
    + detección via ``ConnectionInspector`` que enumera conexiones UDP).
  - Fase 13.3: ``valorant``: ValorantModule — segundo juego, valida el DoD
    (sin tocar analysis/database/recommendations).
"""

from gnd.diagnostics.games.league_of_legends import LeagueOfLegendsModule
from gnd.diagnostics.games.valorant import ValorantModule

__all__ = ["LeagueOfLegendsModule", "ValorantModule"]
