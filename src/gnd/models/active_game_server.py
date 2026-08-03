"""Información del servidor de partida activo detectado.

TECHNICAL_SPEC.md §1 y §2.2. La detección ocurre vía enumeración de
conexiones UDP del proceso del juego (process_connection_scan) o confirmada
cruzada con la Live Client Data API (live_client_api_confirmed).

Fase 14.0a: extensión con ``precision_tier`` y ``region_tag``. El tier
dice qué tan precisa es la IP/port que tiene este VO:

- ``"exact_ip"``: la IP/port vino de ``gameClient.serverIp``/``serverPort``
  del LCU — servidor real de la partida actualmente en curso. Detectado via
  ``"lcu_gameflow"``. La máxima precisión posible sin Npcap.
- ``"proxy_login"`` (default, backwards-compat): no se obtuvo IP real
  (sin lockfile, sin LCU, sin partida activa).   El caller debe caer al
  proxy ``riot_public`` histórico (behavior pre-Fase 14).

``region_tag`` (opcional, default ``None``): ``platformId`` del LCU
(ej. ``"LA1"``, ``"NA1"``, ``"EUW1"``). Se captura gratis del mismo
endpoint LCU y se persiste como metadata — alimentará una futura Fase
14.0b con ``precision_tier="regional_edge"`` (ping a edges regionales
Riot-direct). 14.0a no despacha specs por region_tag — solo se guarda."""

from dataclasses import dataclass

# Valores válidos para ``precision_tier``. Orden: del mas preciso al
# menos preciso. El caller (``LeagueOfLegendsModule.detect_active_server``,
# ``RunFullDiagnostics``) usa esta jerarquía para decidir el target del
# probe al servidor de Riot.
PRECISION_TIERS: frozenset[str] = frozenset({"exact_ip", "proxy_login"})


@dataclass(frozen=True)
class ActiveGameServerInfo:
    ip: str
    port: int
    protocol: str  # "udp" | "tcp"
    # "process_connection_scan" | "live_client_api_confirmed" | "lcu_gameflow"
    detected_via: str
    process_name: str
    # Fase 14.0a: defaults backwards-compat (todos los callers pre-Fase 14
    # siguen funcionando sin tocarlos).
    precision_tier: str = "proxy_login"
    region_tag: str | None = None

    def __post_init__(self) -> None:
        if not self.ip:
            raise ValueError("ip no puede ser vacío")
        if not self.process_name:
            raise ValueError("process_name no puede ser vacío")
        if self.protocol not in ("udp", "tcp"):
            raise ValueError(f"protocol debe ser 'udp' o 'tcp', fue {self.protocol!r}")
        if self.detected_via not in (
            "process_connection_scan",
            "live_client_api_confirmed",
            "lcu_gameflow",
        ):
            raise ValueError(f"detected_via inválido: {self.detected_via!r}")
        if self.precision_tier not in PRECISION_TIERS:
            raise ValueError(
                f"precision_tier debe ser uno de {sorted(PRECISION_TIERS)!r}, "
                f"fue {self.precision_tier!r}"
            )
        if not (1 <= self.port <= 65535):
            raise ValueError(f"port debe estar en [1, 65535], fue {self.port}")
        # region_tag es str | None. Si viene, no puede ser string vacío
        # (None es la señal correcta de "desconocido").
        if self.region_tag is not None and not self.region_tag:
            raise ValueError("region_tag debe ser None o un str no vacío")
