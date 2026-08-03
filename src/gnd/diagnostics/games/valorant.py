"""Módulo de diagnóstico para Valorant (Fase 13.3).

Segunda implementación de ``GameDiagnosticsModule`` (ARCHITECTURE.md §7).
Valida el DoD (Definition of Done) de la Fase 13: agregar un juego nuevo
es, en líneas de código, mayormente contenido dentro de
``diagnostics/games/<nuevo_juego>.py`` — NO requiere tocar ``analysis/``,
``recommendations/``, ni ``database/``.

Diferencias con LoL (``league_of_legends.py``):

- ``provider`` de ``public_endpoints``: ``"valorant_public"`` (no
  ``"riot_public"``). La capa ``analysis/`` trata el provider como string
  opaco — no necesita saber qué es. El baseline se computa por provider;
  los probes de Valorant van a su propia key de baseline, separada de LoL.
- ``process_names``: ``{"VALORANT-Win64-Shipping.exe"}`` (el ejecutable
  real de Valorant en Windows — no ``VALORANT.exe`` que es el launcher).
- ``game_server_provider()``: ``"valorant_game_server"`` (separado de
  ``"riot_game_server"`` de LoL — misma lógica anti-telemetría riot_public
  aplica porque Valorant también es de Riot, pero la detección del server
  de partida usa process_names distintos).
- Reusa el ``ConnectionInspector`` inyectado (``ActiveGameServerDetector``
  con su anti-telemetría riot_public): Valorant también es de Riot, así
  que el mismo filtro anti-CDN aplica. Para juegos no-Riot (futuras
  fases), el módulo podría no inyectar inspector o inyectar uno distinto.

Endpoints públicos de Valorant (Riot infra): reusamos los hostnames de
``targets.riot_public`` (``auth.riotgames.com`` +
``lol.secure.dyn.riotcdn.net``) porque Valorant también los usa (es del
mismo publisher). En una implementación real, esto podría especializarse
a hosts de Valorant, pero para validar el DoD el punto es: la capa de
infraestructura (analysis/database/recommendations) no se tocó nunca.
"""

from __future__ import annotations

import logging

from gnd.domain.ports.connection_inspector import ConnectionInspector
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint

logger = logging.getLogger(__name__)

# Process name del cliente de Valorant en Windows. El launcher es
# VALORANT.exe (Launcher.exe via Riot Client), pero el proceso que tiene
# las conexiones UDP al servidor de partida es el shipping build
# (VALORANT-Win64-Shipping.exe). Detectar este nombre es lo correcto
# para enumerar conexiones de partida activa Valorant.
_VALORANT_PROCESS = "VALORANT-Win64-Shipping.exe"

# Provider de infraestructura pública de Valorant. Distinto de "riot_public"
# (LoL) para que analysis/ los trate como providers separados (baseline
# propio por juego). La capa analysis no se toca: solo lee el string del
# provider como key opaca de la BD.
_VALORANT_PUBLIC_PROVIDER = "valorant_public"

# Provider del probe al server de partida activa. Distinto de
# "riot_game_server" (LoL) — distingue el baseline de Valorant del de LoL.
_VALORANT_GAME_SERVER_PROVIDER = "valorant_game_server"

# Endpoints públicos default de Valorant. Riot rota su infra; reusamos los
# hostnames de riot_public (Valorant es de Riot) como defaults sensatos.
# En config pueden overridearse. Si se quieren hosts specific de Valorant,
# el usuario los setea en config y el módulo los expone como
# GameEndpoint(provider="valorant_public").
# Fase 13.3 YAGNI: no añadimos un sub-config ``targets.valorant_public``
# todavía (Regla 9.5: ningún caller demostrado pide overridear). El
# módulo lee ``targets.riot_public`` como proxy de infra Riot (mismo CDN
# que LoL hoy) — cuando un usuario real tenga endpoints propios de
# Valorant, se promueve a sub-config en Fase 14+ si hay demanda.
_DEFAULT_VALORANT_ENDPOINTS_V4 = [
    "auth.riotgames.com",
    "lol.secure.dyn.riotcdn.net",
]


class ValorantModule:
    """Implementación ``GameDiagnosticsModule`` para Valorant.

    DoD Fase 13: este archivo + ``tests/test_valorant_module.py`` son
    TODO el código nuevo para soportar Valorant. No se tocaron
    ``analysis/``, ``recommendations/``, ni ``database/`` — el orquestador
    los consume via ``GameDiagnosticsModule`` (Protocol inyectable) y la
    capa analysis trata ``provider`` como string opaco.

    Args:
        connection_inspector: ``ConnectionInspector`` inyectado (hoy
            ``ActiveGameServerDetector``). Valorant también es de Riot,
            así que reusa el mismo detector con anti-telemetría riot_public.
            Si un futuro juego no-Riot tiene detector distinto, ese módulo
            inyecta su propio inspector.
    """

    def __init__(
        self, *, connection_inspector: ConnectionInspector | None = None
    ) -> None:
        self._inspector: ConnectionInspector | None = connection_inspector

    # --- GameDiagnosticsModule --------------------------------------------

    def public_endpoints(self) -> list[GameEndpoint]:
        """Endpoints públicos de infraestructura Riot que usa Valorant.

        Defaults reusados de Riot (``riot_public`` hostnames) con
        provider ``"valorant_public"`` (no ``"riot_public"``) para que
        ``analysis/`` los trate como baseline distinto del de LoL.
        """
        try:
            from gnd.config import get_settings

            settings = get_settings()
            hostnames = list(settings.targets.riot_public)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "No se pudo cargar config para ValorantModule endpoints: %r "
                "— usando defaults",
                exc,
            )
            hostnames = list(_DEFAULT_VALORANT_ENDPOINTS_V4)
        return [
            GameEndpoint(host=h, provider=_VALORANT_PUBLIC_PROVIDER, family="ipv4")
            for h in hostnames
        ]

    def process_names(self) -> set[str]:
        """Process name del cliente de Valorant."""
        return {_VALORANT_PROCESS}

    def detect_active_server(self) -> ActiveGameServerInfo | None:
        """Detecta el servidor de partida activa de Valorant (delega al inspector).

        EP §1.2: nunca lanza. Si el inspector no está inyectado (``None``),
        devuelve ``None`` con log ``game.detect.skip`` (caso de tests que
        no prueban detección). Valorant reparte el juego Riot infra, así
        que el mismo ``ActiveGameServerDetector`` con su
        ``RiotPublicHostsProvider`` (anti-telemetría Cloudflare/Akamai)
        aplica sin modificación.
        """
        if self._inspector is None:
            logger.debug(
                "game.detect.skip",
                extra={
                    "event": "game.detect.skip",
                    "reason": "no_connection_inspector",
                    "game": "valorant",
                },
            )
            return None
        return self._inspector.detect_active_game_server(self.process_names())

    def game_server_provider(self) -> str:
        """Provider del probe al server de partida real de Valorant."""
        return _VALORANT_GAME_SERVER_PROVIDER
