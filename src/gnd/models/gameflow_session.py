"""Value Object ``GameflowSession`` — vista mínima del LCU ``/lol-gameflow/v1/session``.

Fase 14.0a. TECHNICAL_SPEC.md §2.2. El cliente de League expone una API
HTTP local (LCU) mientras está corriendo; el endpoint
``GET /lol-gameflow/v1/session`` devuelve un JSON grande con el estado
del cliente (phase, gameClient, map, etc.). NO existe spec oficial de
Riot — la comunidad inversa el esquema.

Este VO captura SOLO los 3 campos que GND usa para detectar la IP del
servidor de partida real::

    map.platformId  -> region_tag (ej. "NA1", "EUW1", "LA1", "LA2", "BR1")
    gameClient.serverIp -> ip del game server cuando partida InProgress
    gameClient.serverPort -> puerto del game server

NO se modela el esquema completo. La razón: el JSON del LCU puede
cambiar entre patches (Riot lo llama "no oficialmente soportado"). Si
GND depende de campos que no usa, cualquier cambio rompe el VO. Con
una vista mínima, los cambios no relevantes (nuevo field, rename de
un field que no nos importa) no afectan el adapter LCU.

Invariante:
- ``region_tag`` puede ser ``None`` (phase Lobby/None → platformId
  vacío) o un string no vacío. ``""`` se rechaza.
- ``server_ip`` y ``server_port`` pueden ser ``None`` (cuando la
  partida no está InProgress todavía). Si ambos están presentes,
  ``port`` debe estar en [1, 65535] y ``ip`` no vacío.
- NO se validan otros campos de la phase (``Lobby``, ``Matchmaking``,
  ``ChampSelect``, ``InProgress``, ``Reconnect``, ``None``, etc.) — el
  valor crudo se guarda en ``phase`` sin validación, porque la lista
  de phases cambia entre versiones del cliente.

El ``ip`` de ``server_ip`` no se valida como IP literal: el adapter LCU
puede devolver IPv4 punto-decimal, IPv6, o algo inesperado. La
validación real (parsing a ``ipaddress``) ocurre en ``RunFullDiagnostics``
cuando construye el spec de ping — el VO solo exige no vacío si está
presente.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameflowSession:
    """Vista mínima de ``/lol-gameflow/v1/session`` del LCU.

    Atributos:
        phase: valor crudo del campo ``phase`` del JSON
            (ej. ``"Lobby"``, ``"Matchmaking"``, ``"ChampSelect"``,
            ``"InProgress"``, ``"Reconnect"``, ``"None"``). Se guarda
            sin validación de dominio cerrado para no romper cuando
            Riot añade o renombra phases en futuros patches.
        region_tag: valor del campo ``map.platformId`` si es un string
            no vacío; ``None`` si no estaba o era vacío. Metadata
            persistida como ``region_tag`` en ``ActiveGameServerInfo``.
        server_ip: valor de ``gameClient.serverIp`` si es no vacío;
            ``None`` si el gameClient no está activo (phases previas a
            InProgress).
        server_port: valor de ``gameClient.serverPort`` entero si está;
            ``None`` si no estaba. Si ambos ``server_ip`` y
            ``server_port`` están presentes, se valida el rango del
            puerto.

    Modelo de dominio inmutable (Protocolo 5). El adapter LCU real
    (``network/lcu_client_http.py``, sub-fase 14.0c) parsea el JSON y
    construye este VO — nunca devuelve el JSON crudo al dominio.
    """

    phase: str
    region_tag: str | None
    server_ip: str | None
    server_port: int | None

    def __post_init__(self) -> None:
        if not self.phase:
            raise ValueError("phase no puede ser vacío")
        if self.region_tag is not None and not self.region_tag:
            raise ValueError("region_tag debe ser None o un str no vacío")
        if self.server_ip is not None and not self.server_ip:
            raise ValueError("server_ip debe ser None o un str no vacío")
        if self.server_port is not None and not (1 <= self.server_port <= 65535):
            raise ValueError(
                f"server_port debe estar en [1, 65535], fue {self.server_port}"
            )
        # Consistencia: ip y port van juntos. Si uno está presente, el
        # otro también. El adapter LCU debe construir el VO así; si
        # viene solo uno, el JSON estaba inconsistente y se rechaza
        # (fail-safe temprano, no propagation de VO degenerado).
        if (self.server_ip is None) != (self.server_port is None):
            raise ValueError(
                "server_ip y server_port deben ambos estar presentes o ambos None"
            )

    def has_active_game_server(self) -> bool:
        """True si ``server_ip`` y ``server_port`` están poblados.

        El caller (``LeagueOfLegendsModule.detect_active_server``,
        sub-fase 14.0d) usa este helper para decidir si despachar el
        tier ``exact_ip`` o caer al fallback ``proxy_login``.
        """
        return self.server_ip is not None and self.server_port is not None
