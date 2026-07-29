"""Composition root — wiring unico (EP §2.D y §3).

Punto unico donde se decide QUE implementacion concreta instanciar:
- Real vs fake (tests inyectan fakes, no usan este modulo).
- Configuracion: lee GndSettings (config Pydantic).
- Conexion SQLite real (file path) vs :memory: (tests).

Ni la UI ni los casos de uso deciden que implementacion usar — eso
vive aca. ARCHITECTURE.md §2 y ENGINEERING_PRINCIPLES.md §2.D.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.config import get_settings
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository
from gnd.diagnostics.riot.active_game_server_detector import (
    ActiveGameServerDetector,
)
from gnd.network.real_dns_resolver import RealDnsResolver
from gnd.network.real_network_interface_inspector import (
    RealNetworkInterfaceInspector,
)
from gnd.network.real_ping_runner import RealPingRunner
from gnd.network.real_traceroute_runner import RealTracerouteRunner
from gnd.visualization import SqliteSeriesDataSource

logger = logging.getLogger(__name__)


def _resolve_db_path(path: str) -> str:
    """Expande %APPDATA% y variables de entorno en el path de DB.

    Default de config: "%APPDATA%/GND/history.db". Crea el directorio
    padre si no existe (no queremos crashear al primer arranque).
    """
    expanded = os.path.expandvars(path)
    p = Path(expanded)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "No se pudo crear el directorio padre de la DB %s: %r. "
            "Se intentara abrir igual (fallara en save_run con mensaje claro).",
            p,
            exc,
        )
    return str(p)


def build_series_source() -> SqliteSeriesDataSource:
    """Construye el SeriesDataSource para la pestaña Charts (Fase 10).

    Reusa el path GndSettings.database.path — misma DB que el
    SqliteDiagnosticsRepository, via una SqliteConnectionFactory nueva.
    Devuelve una implementación de ``SeriesDataSource`` (Protocol).

    Patron separado de ``build_run_full_diagnostics`` para no romper
    callers existentes (3-tupla). La MainWindow recibe este source
    como kwarg opcional ``series_source``.
    """
    settings = get_settings()
    db_path = _resolve_db_path(settings.database.path)
    db_factory = SqliteConnectionFactory(db_path)
    return SqliteSeriesDataSource(db_factory)


def build_run_full_diagnostics() -> (
    tuple[RunFullDiagnostics, DiagnosticTargets, DiagnosticParams]
):
    """Wiring completo: devuelve el caso de uso listo para ejecutar.

    Lee GndSettings, instancia las implementaciones reales (RealPingRunner,
    RealTracerouteRunner, ActiveGameServerDetector, SqliteDiagnosticsRepository)
    y las inyecta en RunFullDiagnostics.

    Returns:
        (use_case, targets, params) lista para `use_case.execute(targets, params)`.
        El caller (UI) solo necesita el caso de uso y los targets/params —
        no sabe Quien implementa cada Protocol.
    """
    settings = get_settings()

    # --- Targets (TECHNICAL_SPEC.md §6) ---
    # Fase 12a.4: targets IPv6 opt-in. Si estan seteados en config, el
    # use case duplica specs IPv6 (pings + traceroutes). Si todos son
    # None/[] (default), la corrida solo hace IPv4 (backwards-compat total
    # con runs pre-12a.4). FakeConnectionInspector para smoke sigue igual.
    targets = DiagnosticTargets(
        gateway_ip=_resolve_gateway_ip(),
        google_dns=settings.targets.google_dns,
        cloudflare=settings.targets.cloudflare,
        quad9=settings.targets.quad9,
        riot_public=list(settings.targets.riot_public),
        game_process_names=set(settings.game_detection.process_names),
        # Fase 12a.4: IPv6 opt-in desde config.targets.*_ipv6.
        # None / [] -> no spec v6 para ese provider.
        google_dns_ipv6=settings.targets.google_dns_ipv6,
        cloudflare_ipv6=settings.targets.cloudflare_ipv6,
        quad9_ipv6=settings.targets.quad9_ipv6,
        riot_public_ipv6=list(settings.targets.riot_public_ipv6),
    )

    # --- Parametros (de config) ---
    params = DiagnosticParams(
        ping_count=settings.probes.ping_count,
        ping_timeout_ms=settings.probes.timeout_ms,
        traceroute_max_hops=settings.probes.traceroute_max_hops,
        traceroute_timeout_ms=settings.probes.timeout_ms,
        baseline_period_days=30,
        packet_loss_warning_pct=settings.thresholds.packet_loss_warning_pct,
        packet_loss_critical_pct=settings.thresholds.packet_loss_critical_pct,
        jitter_warning_ms=settings.thresholds.jitter_warning_ms,
        jitter_critical_ms=settings.thresholds.jitter_critical_ms,
        # Fase 12a.2: metrica DNS opt-in. Si dns.enabled=False en config,
        # la etapa se salta (sin overhead). Hosts vacios -> el use case
        # cae a targets.riot_public como default sensato.
        dns_enabled=settings.dns.enabled,
        dns_hosts=tuple(settings.dns.hosts),
        dns_timeout_ms=settings.dns.timeout_ms,
        dns_include_ipv6=settings.dns.include_ipv6,
        # Fase 12a.3: snapshot de interfaz de red opt-in. Si
        # inspect_interface=False, etapa se salta. En v1 no se inyecta
        # el nombre de la default-route iface (el adaptador real lo
        # detecta en runtime); default None.
        inspect_interface_enabled=settings.network.inspect_interface,
        default_route_iface_hint=None,
    )

    # --- Adaptadores reales (Infrastructure layer) ---
    ping_runner = RealPingRunner()
    traceroute_runner = RealTracerouteRunner(
        jump_threshold_ms=settings.thresholds.hop_jump_threshold_ms,
    )
    connection_inspector = ActiveGameServerDetector()
    # Fase 12a.2: DnsResolver real, siempre construido (aun con
    # dns.enabled=False — el use case decide si la etapa corre). El
    # resolver es stateless y barato; crearlo siempre simplifica DI y
    # evita sorpresas si el usuario togglea `enabled` en runtime futuro.
    dns_resolver = RealDnsResolver()
    # Fase 12a.3: NetworkInterfaceInspector real (stateless). Mismo
    # patron que dns_resolver: se construye siempre, el orquestador
    # decide si la etapa corre segun params.inspect_interface_enabled.
    interface_inspector = RealNetworkInterfaceInspector()

    # --- Persistencia ---
    # Regla de Oro 9.1 (Fase 9, bug threading SQLite): la factory crea una
    # conexion nueva por call al execute() (hilo worker del controller).
    # El threading bug anterior era: conn creada en hilo principal +
    # controller.execute() en thread daemon = ProgrammingError. Ahora
    # composition_root solo construye la FACTORY; el use case pide la conn
    # cuando la necesita (en su propio hilo).
    db_path = _resolve_db_path(settings.database.path)
    db_factory = SqliteConnectionFactory(db_path)
    repository = SqliteDiagnosticsRepository(db_factory)

    # --- Caso de uso (Application layer) ---
    use_case = RunFullDiagnostics(
        ping_runner=ping_runner,
        traceroute_runner=traceroute_runner,
        connection_inspector=connection_inspector,
        repository=repository,
        db_factory=db_factory,
        dns_resolver=dns_resolver,
        interface_inspector=interface_inspector,
    )

    return use_case, targets, params


def _resolve_gateway_ip() -> str:
    """Descubre la IP del gateway local (router).

    Metodo robusto multiplataforma sin psutil: abre un socket UDP hacia
    una IP publica arbitraria (no requiere que el paquete llegue) y lee
    la IP local que el kernel eligio como origen. Si faila, fallback al
    gateway tipico 192.168.1.1.
    """
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No envia paquetes: connect solo configura el peer default.
            # 8.8.8.8 es arbitrario; cualquier IP routable force a
            # que el kernel seleccione la interfaz de salida.
            s.connect(("8.8.8.8", 53))
            local_ip = s.getsockname()[0]
        finally:
            s.close()
        # Heuristic: gateway tipico es la .1 del mismo /24 del local.
        # En redes no tipicas esto puede no ser correcto, pero es un
        # proxy razonable para v1. Si el usuario cambia de gateway,
        # puede overridear via config (TODO v1.1: config.targets.gateway).
        parts = local_ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.1"
        return "192.168.1.1"
    except OSError as exc:
        logger.warning(
            "No se pudo auto-detectar gateway IP: %r -> fallback 192.168.1.1", exc
        )
        return "192.168.1.1"
