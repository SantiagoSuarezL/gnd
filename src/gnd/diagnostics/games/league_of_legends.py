"""Módulo de diagnóstico para League of Legends (Fase 13.1).

Primer implementación de ``GameDiagnosticsModule`` (ARCHITECTURE.md §7).
Envuelve la lógica Riot existente SIN tocarla — es un adapter fino sobre
lo que ya hace el orquestador ``RunFullDiagnostics`` (pre-Fase 13) y sobre
``ActiveGameServerDetector`` (``diagnostics/riot/``).

Decisiones de diseño (Fase 13.1):

- NO re-implementa la detección del servidor activo: delega al
  ``ConnectionInspector`` inyectado (que hoy es ``ActiveGameServerDetector``,
  con su lógica anti-telemetría Cloudflare/Akamai via
  ``RiotPublicHostsProvider``). El módulo solo conoce los ``process_names``
  del juego y los endpoints públicos del publisher — el inspector es
  agnóstico al juego y solo enumera conexiones UDP de procesos.
- Lee config de ``GndSettings`` perezosamente (igual que
  ``_DefaultRiotPublicHostsProvider`` en ``active_game_server_detector.py``)
  para no acoplar el dominio a Pydantic en import-time. Si config falla,
  degrada a listas vacías con log (EP §1.2 desde el constructor).
- ``process_names()`` lee ``game_detection.process_names`` (default
  ``["League of Legends.exe"]``). Devuelve como ``set`` (el contrato del
  Protocol) — el inspector original recibía ``set[str]``.
- ``public_endpoints()`` concatena ``targets.riot_public`` (v4) y
  ``targets.riot_public_ipv6`` (v6 opt-in, Fase 12a.4) para que el
  orquestador los pase como specs de ping/traceroute. Si el usuario no
  configuró IPv6, ``riot_public_ipv6`` es ``[]`` y solo se exponen v4.

Backwards-compat (Fase 13.2): cuando el orquestador migre a consumir un
``GameDiagnosticsModule`` optional, si ``None`` (tests pre-13.2), cae al
path Riot hardcodeado. La impl ``LeagueOfLegendsModule`` recibe ``None``
como ``connection_inspector`` en tests y ``detect_active_server`` devuelve
``None`` con log (no crashea).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gnd.domain.ports.connection_inspector import ConnectionInspector
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint

if TYPE_CHECKING:
    from gnd.config import GndSettings

logger = logging.getLogger(__name__)


class LeagueOfLegendsModule:
    """Implementación ``GameDiagnosticsModule`` para League of Legends.

    Envuelve la lógica Riot (``targets.riot_public`` + ``game_detection``
    + ``ConnectionInspector`` que enumera conexiones UDP con
    anti-telemetría Cloudflare/Akamai). No reescribe nada: delega al
    inspector inyectado, que pre-Fase 13 es ``ActiveGameServerDetector``.

    Uso (wiring en ``composition_root``, Fase 13.2b):

        module = LeagueOfLegendsModule(connection_inspector=detector)
        # en RunFullDiagnostics:
        for ep in module.public_endpoints():
            ...  # specs de ping/traceroute
        active = module.detect_active_server()  # delega a detector

    Args:
        connection_inspector: ``ConnectionInspector`` inyectado (hoy
            ``ActiveGameServerDetector``). ``None`` en tests que no
            prueban detección de partida — ``detect_active_server``
            devuelve ``None`` con log.
        settings: ``GndSettings`` opcional para lectura perezosa de
            ``targets.riot_public``/``riot_public_ipv6`` y
            ``game_detection.process_names``. Si ``None`` (default),
            se lee via ``get_settings()`` al primer call — así el módulo
            no acopla al módulo de config en import-time ni obliga a
            tener config cargada para instanciarlo (EP §4: DI de la
            fuente de settings, no del singleton global).
    """

    def __init__(
        self,
        *,
        connection_inspector: ConnectionInspector | None = None,
        settings: GndSettings | None = None,
    ) -> None:
        self._inspector: ConnectionInspector | None = connection_inspector
        self._settings: GndSettings | None = settings

    # --- GameDiagnosticsModule --------------------------------------------

    def public_endpoints(self) -> list[GameEndpoint]:
        """Endpoints públicos de infraestructura de Riot para LoL.

        Construye ``GameEndpoint`` (host + provider + family) desde
        ``targets.riot_public`` (v4, provider ``"riot_public"``) y
        ``targets.riot_public_ipv6`` (v6 opt-in, Fase 12a.4, mismo
        provider). Si config falla, lista vacía con log (EP §1.2 — el
        orquestador salta specs Riot sin crashear).

        El provider ``"riot_public"`` se mantiene al valor histórico
        para que ``analysis/`` (baselines) y ``recommendations/`` sigan
        funcionando sin tocarlos (DoD Fase 13).
        """
        settings = self._get_settings()
        if settings is None:
            return []
        v4 = [
            GameEndpoint(host=h, provider="riot_public", family="ipv4")
            for h in settings.targets.riot_public
        ]
        v6 = [
            GameEndpoint(host=h, provider="riot_public", family="ipv6")
            for h in settings.targets.riot_public_ipv6
        ]
        return v4 + v6

    def process_names(self) -> set[str]:
        """Nombres de proceso del cliente de LoL (para escaneo UDP).

        Lee ``game_detection.process_names`` (default
        ``["League of Legends.exe"]``). Si config falla, set vacío con log
        — el orquestador salta la detección de partida activa sin crashear.
        """
        settings = self._get_settings()
        if settings is None:
            return set()
        return set(settings.game_detection.process_names)

    def detect_active_server(self) -> ActiveGameServerInfo | None:
        """Detecta el servidor de partida activo de LoL (delega al inspector).

        EP §1.2: nunca lanza. Si el inspector no está inyectado (``None``),
        devuelve ``None`` con log ``game.detect.skip`` + ``reason`` — caso
        de tests que no prueban detección. Si el inspector falla, él mismo
        traduce a ``None``; este método no envuelve en try/except extra
        porque el contrato del ``ConnectionInspector`` ya garantiza
        no-raise (ver ``run_full_diagnostics._safe_detect_active_server``
        para el belt-and-suspenders del orquestador).
        """
        if self._inspector is None:
            logger.debug(
                "game.detect.skip",
                extra={
                    "event": "game.detect.skip",
                    "reason": "no_connection_inspector",
                    "game": "league_of_legends",
                },
            )
            return None
        return self._inspector.detect_active_game_server(self.process_names())

    def game_server_provider(self) -> str:
        """Provider del probe al servidor de partida real de LoL.

        Mantiene el valor histórico ``"riot_game_server"`` para que
        ``analysis/`` (baselines) y ``recommendations/`` sigan con la
        key existente — no tocar analysis (DoD Fase 13).
        """
        return "riot_game_server"

    # --- Internos ---------------------------------------------------------

    def _get_settings(self) -> GndSettings | None:
        """Lee ``GndSettings`` perezosamente (primer call).

        Si el caller inyectó ``settings`` en el constructor, lo reusa.
        Si no, pide el singleton via ``get_settings()``. Cualquier falla
        de config se captura y devuelve ``None`` con log — el módulo
        nunca crashea al arrancar por config mal formada (EP §1.2 desde
        el constructor, no desde el caller).
        """
        if self._settings is not None:
            return self._settings
        try:
            from gnd.config import get_settings

            return get_settings()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "No se pudo cargar GndSettings para LeagueOfLegendsModule: %r "
                "— public_endpoints/process_names devolverán vacíos",
                exc,
            )
            return None
