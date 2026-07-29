"""Adaptador real NetworkInterfaceInspector (Fase 12a.3).

PRD §7 should-have, TECHNICAL_SPEC §8 gap. Implementa
`NetworkInterfaceInspector` (Protocol) detectando tipo de interfaz + SSID
+ dBm en Windows via `netsh wlan show interfaces`. En otros OS
(fuera de scope v1) devuelve un snapshot `type=OTHER` informativo con
error explicando la limitación — sin lanzar excepciones.

Protocolo 1 (modelos sin subprocess/psutil): este módulo es
infrastructure (`network/`) y SÍ importa esos. El Protocol y los modelos
NO.

Protocolo 8 (psutil import diferido): import dentro de métodos, no a
nivel módulo — replica el patrón de `active_game_server_detector.py`.

Criterios de detección de SO y timeout (plan Fase 12a.3 aclaraciones):
1. `platform.system() == "Windows"` se checa ANTES de construir el
   comando `netsh` — no hay intento fallido de subprocess en
   Linux/macOS (evita `FileNotFoundError` y ramas rotas).
2. `subprocess.run(timeout=netsh_timeout_ms/1000)` — timeout explícito
   default 3000ms. Si el driver WLAN cuelga, no blocka la corrida.
3. EP §1.2: cualquier error (subprocess, OSError, parser fail) se
   traduce a `type=OTHER` con `error=str(exc)` — nunca excepción al
   caller.

Mapeo `netsh %` -> dBm: Windows reporta signal como porcentaje 0-100
(relativo). Conversión a dBm aproximada con la fórmula estándar
de calidad de señal RSSI:
    dBm = quality / 2 - 100
(donde quality 0%  -> -100 dBm, quality 100% -> -50 dBm). Standard
de Microsoft para wlan signal quality.

Limitación v1: Linux/macOS solo reportan `type=OTHER`. Una implementación
post-v1 (12a.4+ si priorizado) podría usar `iwconfig`/`nmcli` en Linux
y `networksetup -getairportnetwork`/`ipconfig getsummary` en macOS.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess

from gnd.models.network_interface import InterfaceType, NetworkInterfaceSnapshot

logger = logging.getLogger(__name__)

# Timeout default del subprocess netsh (sanea tiempos largos del driver WLAN).
_DEFAULT_NETSH_TIMEOUT_MS = 3000


class RealNetworkInterfaceInspector:
    """Inspector real cross-platform. Completo en Windows, limitado en otros OS.

    No acepta dependencias via constructor; los parámetros de timeout son
    kwargs del método para alinear con el Protocol (DI de los detalles de
    infraestructura solo se hace en tests mediante Fake, no via este adaptador).
    """

    def inspect(
        self,
        *,
        default_route_iface_hint: str | None = None,
    ) -> NetworkInterfaceSnapshot:
        if platform.system() != "Windows":
            # No-Windows (Linux/macOS): limitación v1 documentada.
            return NetworkInterfaceSnapshot(
                type=InterfaceType.OTHER,
                name=default_route_iface_hint or "unknown-non-windows",
                is_default_route=default_route_iface_hint is not None,
                wifi_ssid=None,
                wifi_signal_dbm=None,
                error=(
                    "deteccion de interfaz solo implementada en Windows "
                    "(v1); Linux/macOS requieren wiring distinto "
                    "(iwconfig/nmcli/networksetup)"
                ),
            )

        # Windows: si no pasaron hint del nombre de la default-route
        # iface, lo detectamos via socket-shot (mismo truco que usa
        # composition_root._resolve_gateway_ip). Eso nos da la IP local
        # del socket UDP "hacia" 8.8.8.8 — buscamos esa IP en
        # psutil.net_if_addrs para ver qué iface la posee. Si nada
        # funciona (IP no encontrada, psutil no disponible), seguimos
        # sin hint y dejamos que el parser caiga a OTHER informativo.
        if default_route_iface_hint is None:
            default_route_iface_hint = _detect_default_route_iface_name_windows()
        # Windows: intentar netsh wlan show interfaces con timeout.
        try:
            proc = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                timeout=_DEFAULT_NETSH_TIMEOUT_MS / 1000.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "netsh wlan show interfaces expiró (timeout=%dms) -> "
                "fallback type=OTHER",
                _DEFAULT_NETSH_TIMEOUT_MS,
            )
            return NetworkInterfaceSnapshot(
                type=InterfaceType.OTHER,
                name=default_route_iface_hint or "netsh-timeout",
                is_default_route=default_route_iface_hint is not None,
                wifi_ssid=None,
                wifi_signal_dbm=None,
                error=f"netsh timeout {_DEFAULT_NETSH_TIMEOUT_MS}ms",
            )
        except OSError as exc:
            # netsh.exe no encontrado — raro en Windows, pero cobertura.
            logger.warning("netsh OSError (no encontrado?): %r -> type=OTHER", exc)
            return NetworkInterfaceSnapshot(
                type=InterfaceType.OTHER,
                name=default_route_iface_hint or "netsh-oserror",
                is_default_route=default_route_iface_hint is not None,
                wifi_ssid=None,
                wifi_signal_dbm=None,
                error=f"netsh OSError: {exc!r}",
            )

        # texto vacío / "No hay datos..." -> probable Ethernet o sin Wi-Fi.
        return _parse_netsh_output(
            proc.stdout,
            default_route_iface_hint,
        )


def _detect_default_route_iface_name_windows() -> str | None:
    """Detecta el nombre OS de la interfaz de default-route en Windows.

    Usa el truco del socket UDP "conectado" a 8.8.8.8 para obtener la
    IP local de origen, y consulta `psutil.net_if_addrs` para ver qué
    iface la posee. Si cualquier falla, devuelve None — el caller opera
    en modo sin hint (parser cae a OTHER informativo, no crashea).

    Protocolo 8 (psutil import diferido) — importa dentro del método.
    EP §1.2: cualquier error devuelve None (no propaga excepción).
    """
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 53))
            local_ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None

    try:
        import psutil  # import diferido (Protocolo 8)
    except ImportError:
        return None

    try:
        addrs = psutil.net_if_addrs()
    except Exception:  # noqa: BLE001
        return None

    for name, addr_list in addrs.items():
        for a in addr_list:
            if a.family == socket.AF_INET and a.address == local_ip:
                return name
    return None


# ---------------------------------------------------------------------------
# Parser de `netsh wlan show interfaces` output (Windows EN/ES locale)
# ---------------------------------------------------------------------------

# netsh emite líneas tipo:
#     SSID : MyNetwork
#     Signal : 87%
# (locale EN) o
#     SSID                    : MyNetwork
#     Señal                   : 87%
# (locale ES). El parser captura los campos en regex separados por
# nombre de campo (SSID vs Signal/Señal) para distinguir value.
_SSID_NAME_RE = re.compile(
    r"^\s*ssid[\s:]*:\s*(?P<val>.+?)\s*$",
    flags=re.IGNORECASE,
)
_SIGNAL_RE = re.compile(
    r"^\s*(?:signal|señal)[\s:]*:\s*(?P<val>\d+)\s*%?\s*$",
    flags=re.IGNORECASE,
)


def _parse_netsh_output(
    text: str,
    default_route_iface_hint: str | None,
) -> NetworkInterfaceSnapshot:
    """Traduce el output de `netsh wlan show interfaces` a NetworkInterfaceSnapshot.

    Si el SSID NN aparece con valor no vacío -> type=WIFI, ssid=valor,
    signal=dBm convertido. Si el output dice "No hay datos" o sin
    `SSID :` -> asumimos Ethernet si hay default route hint, sino OTHER.
    """
    if not text.strip():
        # Output vacio = Wi-Fi apagado o sin interfaz Wi-Fi. Tentativo
        # ETHERNET si hay default-route hint, sino OTHER.
        if default_route_iface_hint:
            return NetworkInterfaceSnapshot(
                type=InterfaceType.ETHERNET,
                name=default_route_iface_hint,
                is_default_route=True,
                wifi_ssid=None,
                wifi_signal_dbm=None,
                error=None,
            )
        return NetworkInterfaceSnapshot(
            type=InterfaceType.OTHER,
            name="netsh-empty-no-hint",
            is_default_route=False,
            wifi_ssid=None,
            wifi_signal_dbm=None,
            error="netsh output vacio y sin hint de default route",
        )

    ssid: str | None = None
    signal_pct: int | None = None
    for line in text.splitlines():
        if ssid is None:
            m = _SSID_NAME_RE.match(line)
            if m and m.group("val").strip():
                # Filtrar strings informativos como "No hay datos
                # disponibles para este adaptador" en ES Windows. Si el
                # valor no parece un SSID (contiene "no hay", "no data"),
                # dejamos ssid None y dejamos que OTHER/ETH fallback
                # se ocupe más abajo.
                val = m.group("val").strip()
                lower_val = val.lower()
                if not (
                    "no hay" in lower_val
                    or "no data" in lower_val
                    or "no information" in lower_val
                ):
                    ssid = val
        if signal_pct is None:
            sm = _SIGNAL_RE.match(line)
            if sm:
                try:
                    signal_pct = int(sm.group("val"))
                except ValueError:
                    signal_pct = None

    if ssid is not None:
        # type=WIFI — exposición de SSID + señal.
        signal_dbm: float | None
        if signal_pct is not None:
            # Conversión estándar Microsoft (0%->-100dBm, 100%->-50dBm).
            signal_dbm = float(signal_pct) / 2.0 - 100.0
        else:
            signal_dbm = None
        return NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name=default_route_iface_hint or "Wi-Fi",
            is_default_route=default_route_iface_hint is not None,
            wifi_ssid=ssid,
            wifi_signal_dbm=signal_dbm,
            error=None,
        )

    # Sin SSID parseado: asumimos ETHERNET si hay default-route hint
    # (el run corría, hay conexión; lo más probable Ethernet o Wi-Fi
    # apagada). Sino OTHER.
    if default_route_iface_hint:
        return NetworkInterfaceSnapshot(
            type=InterfaceType.ETHERNET,
            name=default_route_iface_hint,
            is_default_route=True,
            wifi_ssid=None,
            wifi_signal_dbm=None,
            error=None,
        )
    return NetworkInterfaceSnapshot(
        type=InterfaceType.OTHER,
        name="netsh-no-ssid-no-hint",
        is_default_route=False,
        wifi_ssid=None,
        wifi_signal_dbm=None,
        error="netsh sin SSID reconocido ni hint de default route",
    )
