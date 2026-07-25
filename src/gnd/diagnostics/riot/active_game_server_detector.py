"""Detector del servidor de partida activo (Riot) — camino primario via psutil.

TECHNICAL_SPEC.md §2.2. El componente distintivo del proyecto frente a un
ping tool generico: distingue la IP publica de infraestructura Riot
(login/patcher, Cloudflare/Akamai) de la IP **real** del servidor de
partida en curso, asignada dinamicamente por matchmaking y que es la
unica IP que determina el ping competitivo.

Implementacion primaria (este modulo):
- Enumera procesos via `psutil.process_iter` filtrando por `process_names`
  (default `{"League of Legends.exe"}`).
- Para cada proceso matching, lista conexiones UDP (`net_connections(kind="udp")`)
  — el trafico de partida de LoL es mayoritariamente UDP, no TCP.
- Filtra IPs privadas (RFC1918), loopback (127/8), link-local (169.254/16)
  y CGNAT (100.64/10) — son conexiones locales del cliente, no del server.
- **Excluye IPs que coincidan con `targets.riot_public` resueltas** (Cloudflare/
  Akamai) para no confundir telemetria/CDN con el game server real.
- Devuelve la primera IP publica restante como `ActiveGameServerInfo`
  con `detected_via="process_connection_scan"` y `protocol="udp"`.
- `psutil.AccessDenied` (comun en Windows sin privilegios elevados para
  ver conexiones de otro proceso) y `NoSuchProcess` (proceso murio entre
  el iter y la lectura) se capturan, se loguean y devuelven `None` —
  nunca excepcion a la UI (EP §1.2).

Diseno:
- `ProcessEnumerator(Protocol)` inyectable envuelve la llamada a
  `psutil.process_iter` para permitir tests sin tocar psutil real
  (Regla de Oro 2.1).
- `RiotPublicHostsProvider(Protocol)` inyectable para los hostnames de
  `riot_public` (evita DNS en tests; el default lee de config Pydantic).
- No se importa `psutil` a nivel modulo (deferido y encapsulado en
  `_PsutilEnumerator`): el dominio y los tests no dependen de psutil.

La confirmacion cruzada opcional via Live Client Data API
(https://127.0.0.1:2999/liveclientdata/) vive en `live_client_api.py` y
es un complemento, no un reemplazo (ver docstring de ese modulo).
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from gnd.models.active_game_server import ActiveGameServerInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtrado de IPs privadas/reservadas (RFC1918 + loopback + link-local + CGNAT)
# ---------------------------------------------------------------------------

_IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$"
)


def _looks_like_ipv4(s: str) -> bool:
    return bool(_IPV4_PATTERN.match(s))


def _ip_in_private_range(ip: str) -> bool:
    """True si `ip` (IPv4) es privada/reservada y debe filtrarse.

    Cubre:
    - Loopback 127.0.0.0/8 (RFC 5735)
    - RFC1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    - Link-local 169.254.0.0/16 (RFC 3927, DHCP fail / APIPA)
    - CGNAT 100.64.0.0/10 (RFC 6598) — algunos ISPs NAT carrier-grade
    - IETF reserved 192.0.2.0/24 (TEST-NET, RFC 5737) y 198.51.100.0/24
    - Multicast 224.0.0.0/4 — no tiene sentido como server de partida

    No filtramos 0.0.0.0 (sin IP remota) — se filtra antes por `raddr`
    ausente o ip vacia.
    """
    if not _looks_like_ipv4(ip):
        # No es IPv4 (hostname?): no la filtramos aca, el caller decide.
        return False
    parts = ip.split(".")
    o1, o2 = int(parts[0]), int(parts[1])

    if o1 == 127:  # loopback
        return True
    if o1 == 10:  # RFC1918 /8
        return True
    if o1 == 192 and o2 == 168:  # RFC1918 /16
        return True
    if o1 == 172 and 16 <= o2 <= 31:  # RFC1918 /12
        return True
    if o1 == 169 and o2 == 254:  # link-local
        return True
    if o1 == 100 and 64 <= o2 <= 127:  # CGNAT
        return True
    if o1 == 192 and o2 == 0 and int(parts[2]) == 2:  # TEST-NET-1
        return True
    if o1 == 198 and o2 == 51 and int(parts[2]) == 100:  # TEST-NET-2
        return True
    if 224 <= o1 <= 239:  # multicast
        return True
    return False


def is_public_ipv4(ip: str) -> bool:
    """True si `ip` es una IPv4 valida y NO esta en rango privado/reservado.

    Usado por el detector para decidir si una `raddr.ip` de una conexion UDP
    corresponde al servidor de partida real (IP publica) o a una conexion
    local del cliente (loopback, LAN, link-local, etc.).
    """
    if not _looks_like_ipv4(ip):
        return False
    return not _ip_in_private_range(ip)


def _raddr_to_ip_port(raddr: object) -> tuple[str, int] | None:
    """Normaliza el `raddr` de una conexion psutil a (ip, port) | None.

    psutil es polimorfico en el formato de `raddr` segun version y estado
    de la conexion (Regla de Oro 6.6):

    - `None` (psutil 5.x para conexiones listening): devolver None.
    - Tupla vacia `()` (psutil 6.x/7.x para listening UDP sin peer): None.
    - namedtuple `addr(ip=..., port=...)`: extraer por atributo.
    - Tupla con 2 items `(ip, port)`: extraer posicionalmente.
    - Cualquier otra cosa: None por seguridad.

    Es defensive parsing: nunca lanza, siempre devuelve None si el formato
    no es reconocido. EP §1.2: ningun resultado de red debe burbujear como
    excepcion; esta normalizacion cumple ese contrato para `raddr`.
    """
    if raddr is None:
        return None
    # namedtuple psutil.addr: tiene atributos '.ip' y '.port'.
    ip_attr = getattr(raddr, "ip", None)
    port_attr = getattr(raddr, "port", None)
    if ip_attr is not None and port_attr is not None:
        return (str(ip_attr), int(port_attr))
    # Tupla/lista posicional: (ip, port) o ().
    if isinstance(raddr, (tuple, list)):
        if len(raddr) == 2:
            ip, port = raddr
            if isinstance(ip, str) and isinstance(port, int):
                return (ip, port)
        return None
    return None


# ---------------------------------------------------------------------------
# Abstracciones inyectables (Protocol) para tests sin psutil/DNS real
# ---------------------------------------------------------------------------


class ProcessEnumerator(Protocol):
    """Devuelve un iterable de procesos del sistema.

    Envuelve `psutil.process_iter(attrs)`. Cada proceso del iterable debe
    exponer:
    - `info`: dict con las keys pedidas en `attrs` (ej. "name", "pid").
    - `net_connections(kind)`: callable que devuelve una lista de
      conexiones; cada conexion tiene `raddr` (objeto con `.ip` y `.port`)
      o `None`.
    """

    def __call__(self, attrs: list[str]) -> ProcIterable: ...


class ProcIterable(Protocol):
    def __iter__(self) -> Proc: ...


class Proc(Protocol):
    info: dict

    def net_connections(self, kind: str) -> list[Conn]: ...


class Conn(Protocol):
    raddr: Addr | None


class Addr(Protocol):
    ip: str
    port: int


class RiotPublicHostsProvider(Protocol):
    """Provee los hostnames configurados para `targets.riot_public`.

    El detector los resuelve a IPs y las excluye del escaneo (anti-telemetria
    Cloudflare/Akamai). Separado de `ProcessEnumerator` para poder testear
    la logica de exclusion sin tocar DNS real (Regla de Oro 6.1).
    """

    def get_hostnames(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class ActiveGameServerDetector:
    """ConnectionInspector real via enumeracion de conexiones UDP de proceso.

    Implementa `Protocol ConnectionInspector` (`domain/ports/`).

    Uso tipico (wiring en composition_root):

        inspector = ActiveGameServerDetector()  # usa psutil + config nativo
        info = inspector.detect_active_game_server({"League of Legends.exe"})
        if info is None:
            # sin partida activa o sin privilegios para leer conexiones
            ...
        else:
            # info.ip es la IP PUBLICA del server de partida real

    Comportamiento ante errores (TECHNICAL_SPEC.md §7):
    - psutil.AccessDenied (Windows: requiere admin para ver conexiones de
      otro proceso) -> log warning + None. La UI mostrara "ejecutar como
      administrador para deteccion de partida".
    - psutil.NoSuchProcess (el proceso murio entre iter y net_connections)
      -> log debug + saltar al siguiente proceso.
    - Proceso marcado zombie o sin info -> log debug + saltar.
    - Falla total de process_iter -> None (el bucle nunca arranca).

    Filtrado de conexiones:
    - `raddr is None` (conexion sin peer, listening o closed) -> skip.
    - `raddr.ip` en rango privado/reservado (RFC1918, loopback, link-local,
      CGNAT, multicast, TEST-NET) -> skip via `is_public_ipv4`.
    - `raddr.ip` que coincide con alguna IP de `targets.riot_public`
      resuelta -> skip (anti-telemetria: evita confundir CDN con game server).
    - La primera `raddr.ip` publica que NO este en la lista de exclusion
      se devuelve. Si TODAS las IPs publicas coinciden con riot_public,
      se devuelve None (no hay game server distinguible).
    """

    def __init__(
        self,
        *,
        process_enumerator: ProcessEnumerator | None = None,
        riot_public_provider: RiotPublicHostsProvider | None = None,
    ) -> None:
        # Import diferido: el dominio no debe depender de psutil (EP §1.1).
        if process_enumerator is None:
            process_enumerator = _PsutilEnumerator()
        self._enumerator: ProcessEnumerator = process_enumerator

        # Provider de hostnames riot_public (para exclusion de IPs CDN).
        if riot_public_provider is None:
            riot_public_provider = _DefaultRiotPublicHostsProvider()
        self._riot_public_provider: RiotPublicHostsProvider = riot_public_provider

    def detect_active_game_server(
        self,
        process_names: set[str],
    ) -> ActiveGameServerInfo | None:
        """Detecta el servidor de partida activo escaneando conexiones UDP.

        EP §2.L (Liskov): signature y contrato identicos al
        `FakeConnectionInspector` y al Protocol. Nunca lanza excepciones
        hacia el caller — toda falla se corresponde a un `None` con log.
        """
        if not process_names:
            logger.debug(
                "detect_active_game_server llamado con process_names vacio "
                "-> None (no hay nada que buscar)"
            )
            return None

        # Resolver hostnames de riot_public a IPs a excluir (anti-telemetria).
        riot_public_ips = self._resolve_riot_public_ips()
        if riot_public_ips:
            logger.debug(
                "IPs de riot_public a excluir del detector: %s",
                sorted(riot_public_ips),
            )

        try:
            processes = self._enumerator(["name", "pid"])
        except Exception as exc:  # noqa: BLE001
            # psutil.process_iter rara vez falla, pero si AccessDenied a
            # nivel system (politicas estrictas), cubrimos por EP §1.2.
            logger.warning(
                "process_iter fallo (process_names=%s): %r -> None",
                sorted(process_names),
                exc,
            )
            return None

        for proc in processes:
            info = getattr(proc, "info", None) or {}
            name = info.get("name")
            pid = info.get("pid")
            if name is None or name not in process_names:
                continue

            try:
                connections = proc.net_connections(kind="udp")
            except Exception as exc:  # AccessDenied / NoSuchProcess / ZombieProcess
                # AccessDenied es el caso mas comun en Windows sin admin.
                # Logueamos con nivel adecuado y seguimos al siguiente
                # proceso (puede haber multiples instancias o el LCU).
                kind = type(exc).__name__
                if "AccessDenied" in kind:
                    logger.warning(
                        "AccessDenied al leer conexiones UDP de %s (pid=%s). "
                        "Tip: ejecutar como administrador para deteccion de "
                        "partida. Saltando proceso.",
                        name,
                        pid,
                    )
                elif "NoSuchProcess" in kind:
                    logger.debug(
                        "NoSuchProcess: %s (pid=%s) murio entre iter y "
                        "net_connections. Saltando.",
                        name,
                        pid,
                    )
                else:
                    logger.exception(
                        "Error inesperado leyendo conexiones UDP de %s " "(pid=%s)",
                        name,
                        pid,
                    )
                continue

            found = self._first_public_udp_raddr(connections, riot_public_ips)
            if found is not None:
                ip, port = found
                logger.info(
                    "Servidor de partida activo detectado: %s:%d (udp) "
                    "proceso=%s pid=%s via process_connection_scan",
                    ip,
                    port,
                    name,
                    pid,
                )
                return ActiveGameServerInfo(
                    ip=ip,
                    port=port,
                    protocol="udp",
                    detected_via="process_connection_scan",
                    process_name=name,
                )

        logger.debug(
            "Ningun proceso en %s con conexion UDP publica encontrada "
            "(sin partida activa o todas locales)",
            sorted(process_names),
        )
        return None

    @staticmethod
    def _first_public_udp_raddr(
        connections: list[Conn],
        exclude_ips: set[str] | None = None,
    ) -> tuple[str, int] | None:
        """Primera `raddr` publica de la lista de conexiones UDP.

        Filtra:
        - raddr no reconocible (None, tuple vacia, etc.) -> skip via
          `_raddr_to_ip_port` (regla de Oro 6.6: raddr polimorfico).
        - ip no parseable como IPv4.
        - ip en rango privado/reservado (loopback, RFC1918, ...).
        - ip en `exclude_ips` (IPs de riot_public resueltas —
          anti-telemetria Cloudflare/Akamai).

        Devuelve None si no hay ninguna IP publica valida despues de todos
        los filtros (incluye el caso donde todas coinciden con exclude_ips).
        """
        for conn in connections:
            raddr = getattr(conn, "raddr", None)
            ip_port = _raddr_to_ip_port(raddr)
            if ip_port is None:
                continue
            ip, port = ip_port
            if not ip or port == 0:
                continue
            if not is_public_ipv4(ip):
                continue
            if exclude_ips and ip in exclude_ips:
                logger.debug(
                    "Excluyendo IP de conexion UDP (coincide con riot_public): "
                    "%s:%d",
                    ip,
                    port,
                )
                continue
            return (ip, port)
        return None

    def _resolve_riot_public_ips(self) -> set[str]:
        """Resuelve los hostnames de riot_public a IPs IPv4 para exclusion.

        Si un hostname no resuelve, se ignora (no crashea). Si todos fallan,
        devuelve set vacio (no hay exclusion).
        """
        import socket

        hostnames = self._riot_public_provider.get_hostnames()
        ips: set[str] = set()
        for host in hostnames:
            if not host:
                continue
            if _looks_like_ipv4(host):
                ips.add(host)
                continue
            try:
                infos = socket.getaddrinfo(host, None, socket.AF_INET)
                if infos:
                    ips.add(infos[0][4][0])
            except socket.gaierror:
                logger.debug(
                    "No se pudo resolver hostname riot_public: %s (ignorado)",
                    host,
                )
        return ips


# ---------------------------------------------------------------------------
# Implementaciones por defecto (usadas si el caller no inyecta fakes)
# ---------------------------------------------------------------------------


class _DefaultRiotPublicHostsProvider:
    """Lee `targets.riot_public` desde `GndSettings` (config Pydantic).

    Importa config perezosamente para no acoplar a psutil ni config en
    import-time. Si la config falla, devuelve lista vacia (sin exclusion).
    """

    def get_hostnames(self) -> list[str]:
        try:
            from gnd.config import get_settings

            settings = get_settings()
            return list(settings.targets.riot_public)
        except Exception:  # noqa: BLE001
            # Config mal formada o no disponible -> sin exclusion (seguro).
            logger.warning(
                "No se pudieron cargar riot_public hostnames de config "
                "(exclusion de telemetria desactivada)"
            )
            return []


class _PsutilEnumerator:
    """Implementacion por defecto: wrap sobre `psutil.process_iter`.

    Se instancia solo si el caller no inyecto un enumerator fake.
    Psutil se importa aca (lazily), no a nivel modulo — el dominio no
    debe depender de psutil (EP §1.1).
    """

    def __call__(self, attrs: list[str]) -> ProcIterable:
        import psutil  # import diferido

        return psutil.process_iter(attrs)
