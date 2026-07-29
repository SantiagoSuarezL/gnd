"""Snapshot de la interfaz de red activa (Fase 12a.3).

PRD §7 should-have + TECHNICAL_SPEC §8 gap: distinguir Wi-Fi vs Ethernet
e intensidad de señal — afecta directamente el diagnóstico de "problema
local". Captura el tipo de interfaz que el OS usa para la default route
+ (en Wi-Fi) SSID/signal en dBm para contexto del usuario.

`NetworkInterfaceSnapshot` es una entidad de contexto (no entra al motor
de recomendación v1 — solo se mide y persiste para observabilidad). El
motor de recomendación v2 podría usarlo para sugerir "tu Wi-Fi está con
señal débil, jitter alto es esperable" — fuera de scope de 12a.3.

El `InterfaceType` se reporta como Enum corto. El adaptador real baja a
esto; el modelo NO depende de `psutil`, `subprocess`, ni de `platform`
(Protocolo 1: separación estricta `models/`).
"""

from dataclasses import dataclass
from enum import Enum, auto

__all__ = ["NetworkInterfaceSnapshot", "InterfaceType"]


class InterfaceType(Enum):
    WIFI = auto()
    ETHERNET = auto()
    OTHER = auto()  # loopback, VPN virtual, tun, etc. — sin información.


@dataclass(frozen=True)
class NetworkInterfaceSnapshot:
    """Snapshot inmutable de la interfaz activa al momento del run.

    Invariante: si type == WIFI -> wifi_ssid NO es None (aunque sea
    string vacío en OSes que no lo exponen). Si type != WIFI, los
    campos wifi_* son None. La regla garantiza consistencia: un snapshot
    ETH nunca trae wifi_ssid no-None, evitando reads conflictivos en
    consumers futuros.

    `wifi_signal_dbm` es None en ETHERNET/OTHER. En Wi-Fi, es la potencia
    de señal medida en dBm (negativo, típicamente -30 a -90). Si el OS
    no expone el dato (ej. netsh_wlan_nosignal), es None — acceptable.
    """

    type: InterfaceType
    name: str  # nombre de la interfaz según OS (ej. "Wi-Fi", "eth0")
    is_default_route: bool
    wifi_ssid: str | None
    wifi_signal_dbm: float | None
    # Información de error/limitación si type=OTHER por fallback del SO:
    # dice por qué no se pudo determinar el tipo. None si todo OK.
    error: str | None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name no puede ser vacío")
        if self.type is InterfaceType.WIFI and self.wifi_ssid is None:
            raise ValueError(
                "wifi_ssid no puede ser None cuando type=WIFI "
                "(usar string vacío si el OS no lo expone)"
            )
        if self.type is not InterfaceType.WIFI and (
            self.wifi_ssid is not None or self.wifi_signal_dbm is not None
        ):
            raise ValueError(
                f"wifi_ssid/wifi_signal_dbm deben ser None cuando type="
                f"{self.type.name} (!= WIFI)"
            )
        if self.wifi_signal_dbm is not None and self.wifi_signal_dbm > 0:
            raise ValueError(
                f"wifi_signal_dbm debe ser negativo (dBm), no "
                f"{self.wifi_signal_dbm}"
            )
