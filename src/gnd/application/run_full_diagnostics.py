"""Caso de uso RunFullDiagnostics — orquesta una corrida completa.

Application layer de ARCHITECTURE.md §2. Consume los Protocol del
dominio inyectados por constructor (EP §3 DI). El wiring de qué
implementacion concreta usar vive en `composition_root`.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from gnd.analysis.baseline import compute_baseline
from gnd.analysis.score import compute_network_score
from gnd.domain.ports.connection_inspector import ConnectionInspector
from gnd.domain.ports.database import DatabaseConnectionFactory
from gnd.domain.ports.diagnostics_repository import DiagnosticsRepository
from gnd.domain.ports.dns_resolver import DnsResolver
from gnd.domain.ports.game_diagnostics_module import GameDiagnosticsModule
from gnd.domain.ports.network_interface_inspector import (
    NetworkInterfaceInspector,
)
from gnd.domain.ports.ping_runner import PingRunner
from gnd.domain.ports.traceroute_runner import TracerouteRunner
from gnd.logging import RunContextAdapter
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.dns_measurement import DnsOutcome, DnsResolution
from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.network_interface import NetworkInterfaceSnapshot
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.traceroute import TracerouteResult
from gnd.recommendations.engine import evaluate_recommendation

logger = logging.getLogger(__name__)

# Workers paralelos para probes + traceroutes. ARCHITECTURE.md §6 sugería
# asyncio, pero subprocess de `ping`/`tracert` es bloqueante (GIL-release).
# `ThreadPoolExecutor` es la opción idiomática para IO subprocess-bound en
# CPython y cumple el mismo principio (no bloquear hilo de UI). 6+2 workers
# son sobrados: 6 pings concurrentes + 2 traceroutes concurrentes no saturan.
_PROBE_WORKERS = 6
_TRACEROUTE_WORKERS = 2


# --- Providers conocidos (TECHNICAL_SPEC.md §1) ---
_PROVIDER_LOCAL = "local"
_PROVIDER_GOOGLE = "google"
_PROVIDER_CLOUDFLARE = "cloudflare"
_PROVIDER_QUAD9 = "quad9"
_PROVIDER_RIOT_PUBLIC = "riot_public"
_PROVIDER_RIOT_GAME_SERVER = "riot_game_server"


def _looks_like_ip_literal(s: str) -> bool:
    """Heur: True si `s` parece una IP literal (no un hostname a resolver).

    Evita pedirle a `DnsResolver` que resuelva "8.8.8.8" — getaddrinfo lo
    haría trivialmente sin tocar DNS, falseando el tiempo medido.

    Cobertura: IPv4 (4 octetos numéricos) e IPv6 (contiene ':'). Hostnames
    legítimos como `auth.riotgames.com` son False. Edge cases raros
    (ej: hostname con trailing dot `host.`) quedan cubiertos.
    """
    if not s:
        return False
    if ":" in s:  # IPv6 o IPv4-mapped
        return True
    parts = s.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return True
    return False


@dataclass(frozen=True)
class DiagnosticTargets:
    """Targets de la corrida, derivados de config (inyectados por el caller).

    Mantener estos valores fuera del caso de uso permite que el
    composition_root los lea de `GndSettings` y que los tests inyecten
    valores fijos sin tocar config real (EP §4).

    Fase 12a.4: los campos `*_ipv6` son opt-in. Si TODOS son None/[]
    (estado default), la corrida se comporta como pre-12a.4: solo probes
    IPv4. Setear al menos uno habilita la duplicacion de specs IPv6 — sin
    flag extra (TDA: los datos determinan, el flag es redundante). En
    config: `targets.google_dns_ipv6="2606:4700:4700::1111"` etc.
    """

    gateway_ip: str
    google_dns: str
    cloudflare: str
    quad9: str
    riot_public: list[str]
    game_process_names: set[str]
    # Fase 12a.4: targets IPv6 opt-in ( külön de los IPv4).
    # None / [] => no se duplica spec v6 para ese provider.
    google_dns_ipv6: str | None = None
    cloudflare_ipv6: str | None = None
    quad9_ipv6: str | None = None
    riot_public_ipv6: list[str] = field(default_factory=list)

    def has_any_ipv6_target(self) -> bool:
        """True si al menos un target IPv6 esta seteado (habilita specs v6)."""
        return any(
            (
                self.google_dns_ipv6 is not None,
                self.cloudflare_ipv6 is not None,
                self.quad9_ipv6 is not None,
                bool(self.riot_public_ipv6),
            )
        )


@dataclass(frozen=True)
class DiagnosticParams:
    """Parametros de ejecucion (count, timeouts, max_hops, baseline window)."""

    ping_count: int
    ping_timeout_ms: int
    traceroute_max_hops: int
    traceroute_timeout_ms: int
    baseline_period_days: int
    # Thresholds pasados al motor de recomendacion (TECHNICAL_SPEC.md §5)
    packet_loss_warning_pct: float
    packet_loss_critical_pct: float
    jitter_warning_ms: float
    jitter_critical_ms: float
    # Fase 12a.2: medicion DNS opt-in. Defaults backwards-compatibles
    # (dns_enabled=False -> etapa DNS se salta, sin overhead de tiempo).
    dns_enabled: bool = False
    dns_hosts: tuple[str, ...] = ()
    dns_timeout_ms: int = 1000
    dns_include_ipv6: bool = False
    # Fase 12a.3: snapshot de interfaz de red opt-in. Si
    # `inspect_interface_enabled=False`, la etapa se salta (sin overhead).
    # `default_route_iface_hint`: nombre OS de la default-route iface para
    # inyectar al inspector (evita que el adaptador real redetecte la ruta).
    # Por defecto None -> el adaptador lo detecta por si mismo.
    inspect_interface_enabled: bool = False
    default_route_iface_hint: str | None = None


class RunFullDiagnostics:
    """Orquesta una corrida completa end-to-end (ARCHITECTURE.md §5).

    DI completa (EP §3): ninguna dependencia se instancia aca dentro.
    El clock es inyectable para tests deterministas (EP §4: sin reloj real).

    El caso de uso es agnostico de la UI y de las implementaciones
    concretas — solo habla con Protocol.
    """

    def __init__(
        self,
        *,
        ping_runner: PingRunner,
        traceroute_runner: TracerouteRunner,
        connection_inspector: ConnectionInspector,
        repository: DiagnosticsRepository,
        db_factory: DatabaseConnectionFactory | None = None,
        dns_resolver: DnsResolver | None = None,
        interface_inspector: NetworkInterfaceInspector | None = None,
        # Fase 13.2: módulo de juego opcional. Si está presente, el
        # orquestador consume ``module.public_endpoints()`` para las specs
        # de Riot y ``module.process_names()`` + ``module.detect_active_server()``
        # para la detección de partida activa — ignorando los campos
        # Riot-hardcodeados de ``DiagnosticTargets`` (``riot_public``,
        # ``riot_public_ipv6``, ``game_process_names``). Si es ``None``
        # (backwards-compat con tests pre-13.2 y prod hasta 13.2b), cae al
        # path Riot hardcodeado de hoy: usa ``connection_inspector`` +
        # ``targets.game_process_names`` + ``targets.riot_public``. Esto
        # permite migrar callers incrementalmente sin romper los 843 tests.
        game_module: GameDiagnosticsModule | None = None,
    ) -> None:
        self._ping = ping_runner
        self._tracer = traceroute_runner
        self._inspector = connection_inspector
        self._repo = repository
        # Factory de conexiones SQLite (Regla de Oro 9.1). Se pide UNA
        # nueva conexion dentro del execute() — el hilo que corre el
        # caso de uso es el dueno de esa conn. sqlite3 prohibe compartir
        # entre hilos; la factory evita el bug en lugar de parche con
        # check_same_thread=False + Lock (segun Regla de Oro 9.1).
        # None en tests que no persisten historico ni leen baseline.
        self._db_factory = db_factory
        # Fase 12a.2: resolver DNS opt-in. None = feature apagada (la
        # etapa dns se salta en execute()). Inyectado por composition_root
        # como RealDnsResolver en prod, FakeDnsResolver en tests.
        self._dns_resolver = dns_resolver
        # Fase 12a.3: inspector de interfaz de red opt-in. None = feature
        # apagada (la etapa interface se salta). Inyectado por
        # composition_root como RealNetworkInterfaceInspector en prod,
        # FakeNetworkInterfaceInspector en tests.
        self._interface_inspector = interface_inspector
        # Fase 13.2: módulo de juego (multi-juego). None = path Riot
        # hardcodeado de hoy (backwards-compat). Inyectado por
        # composition_root como LeagueOfLegendsModule en prod (Fase 13.2b),
        # FakeGameDiagnosticsModule en tests del orquestador multi-juego.
        self._game_module = game_module
        # Cache publica para que la UI lea baselines sin tocar DB despues
        # de execute() (evita nuevo cross-thread en root.after()). Se
        # setea en execute() al final de la Etapa 5.
        self.last_baselines: dict[str, HistoricalBaseline] = {}

    def execute(
        self,
        targets: DiagnosticTargets,
        params: DiagnosticParams,
        *,
        clock: type[datetime] | None = None,
        run_id: str | None = None,
        progress_callback: object | None = None,
    ) -> DiagnosticRun:
        """Ejecuta la corrida completa y devuelve el DiagnosticRun.

        Args:
            targets: IPs/hostnames/config a sondear.
            params: count, timeouts, thresholds.
            clock: callable () -> datetime (default datetime.now). Inyectable
                para tests sin reloj real (EP §4).
            run_id: identificador de la corrida (genera UUID si None).
            progress_callback: callable (stage: str) -> None opcional para
                que la UI muestre progreso sin conocer detalles internos.
                Se invoca entre etapas; el caso de uso NO sabe si la UI
                lo usa o no (Liskov: None = no-op).

        Returns:
            DiagnosticRun completo con probes, traceroutes, active_game_server
            y recommendation calculada.

        EP §1.2: ninguna etapa puede lanzar excepcion a la UI. Si un
        sondeo individual falla, se registra como ProbeResult con outcome
        apropiado (TIMEOUT/UNREACHABLE) y la corrida continua.
        """
        now = clock or datetime
        rid = run_id or uuid.uuid4().hex[:12]
        notify = progress_callback or (lambda stage: None)
        # Fase 11: LoggerAdapter vincula el run_id a cada evento de la
        # corrida (EP §5: run_id en cada log). El adapter no modifica los
        # loggers de los sub-componentes (que siguen emitiendo via el
        # suyo propio), solo los eventos estructurados que emitiamos aca.
        log = RunContextAdapter(logger, run_id=rid)

        started_at = now.now()
        probes: list[ProbeResult] = []
        traceroutes: list[TracerouteResult] = []

        log.info(
            "run.start",
            extra={
                "event": "run.start",
                "ping_count": len(targets.riot_public) + 4,  # 4 fixos + riot_public
                "traceroute_count": 1 + (1 if targets.riot_public else 0),
                "dns_enabled": params.dns_enabled,
                "inspect_interface_enabled": params.inspect_interface_enabled,
                # Fase 12a.4: si hay targets IPv6 seteados, el run incluye
                # specs v6 (pings + traceroutes) ademas de los v4.
                "ipv6_enabled": targets.has_any_ipv6_target(),
                "params": {
                    "ping_count": params.ping_count,
                    "ping_timeout_ms": params.ping_timeout_ms,
                    "traceroute_max_hops": params.traceroute_max_hops,
                    "baseline_period_days": params.baseline_period_days,
                    "dns_enabled": params.dns_enabled,
                    "dns_hosts": list(params.dns_hosts),
                    "dns_timeout_ms": params.dns_timeout_ms,
                    "dns_include_ipv6": params.dns_include_ipv6,
                    "inspect_interface_enabled": (params.inspect_interface_enabled),
                },
            },
        )

        # --- Etapa 1-3: pings en paralelo ---
        # ARCHITECTURE.md §6: paralelizar sondeos. Cada ping es subprocess
        # blocking (~19s con count=20), correrlos en serie da 115s+ para 6
        # probes. ThreadPoolExecutor los lanza en paralelo: tiempo total
        # ~= max(individual) ~= ~8-10s (con count=8) en vez de 6x*8s.
        # Cada worker es thread-safe: RealPingRunner no comparte estado,
        # socket.create_connection y subprocess.run son thread-safe en
        # CPython. EP §1.2 preservado: un probe que falla devuelve su
        # ProbeResult con outcome adecuado, no aborta el pool.

        # Lista de specs: (target_ip, target_name, provider, family)
        # Fase 12a.4: specs IPv6 se dupliquen a partir de targets.*_ipv6
        # (opt-in). El family se propaga a PingRunner.ping(family=...) que
        # construye args -4/-6 (Windows) o ping6/ping (POSIX).
        ping_specs: list[tuple[str, str, str, str]] = [
            (targets.gateway_ip, "gateway", _PROVIDER_LOCAL, "ipv4"),
            (targets.google_dns, "google_dns", _PROVIDER_GOOGLE, "ipv4"),
            (targets.cloudflare, "cloudflare", _PROVIDER_CLOUDFLARE, "ipv4"),
            (targets.quad9, "quad9", _PROVIDER_QUAD9, "ipv4"),
        ]
        # Fase 13.2: specs de infraestructura del juego/publisher. Si hay
        # ``game_module`` inyectado, los endpoints provienen de
        # ``module.public_endpoints()`` (list[GameEndpoint] — el módulo es
        # dueño del host + provider + family). Si no, backwards-compat:
        # cae al path Riot hardcodeado (``targets.riot_public`` v4 +
        # ``targets.riot_public_ipv6`` v6) — preserva el esquema de
        # target_name ``riot_public:{host}`` (v4) y ``riot_public:{host}:v6``
        # que analysis/UI ya dependen.
        if self._game_module is not None:
            for ep in self._game_module.public_endpoints():
                suffix = ":v6" if ep.family == "ipv6" else ""
                ping_specs.append(
                    (
                        ep.host,
                        f"{ep.provider}:{ep.host}{suffix}",
                        ep.provider,
                        ep.family,
                    )
                )
        else:
            for host in targets.riot_public:
                ping_specs.append(
                    (host, f"riot_public:{host}", _PROVIDER_RIOT_PUBLIC, "ipv4")
                )
        # Specs IPv6 de internet health: solo si el usuario seteo
        # targets.*_ipv6 en config (estos no son del juego, son probes de
        # salud de Internet — google/cloudflare/quad9). Duplicamos con
        # sufijo ':v6' en target_name para distinguirlo en logs/UI sin
        # colisionar con el proveedor (provider sigue siendo 'google' /
        # 'cloudflare' etc. — el target_name los diferencia).
        if targets.google_dns_ipv6 is not None:
            ping_specs.append(
                (
                    targets.google_dns_ipv6,
                    "google_dns:v6",
                    _PROVIDER_GOOGLE,
                    "ipv6",
                )
            )
        if targets.cloudflare_ipv6 is not None:
            ping_specs.append(
                (
                    targets.cloudflare_ipv6,
                    "cloudflare:v6",
                    _PROVIDER_CLOUDFLARE,
                    "ipv6",
                )
            )
        if targets.quad9_ipv6 is not None:
            ping_specs.append((targets.quad9_ipv6, "quad9:v6", _PROVIDER_QUAD9, "ipv6"))
        # Specs v6 del juego: si no hay game_module, cae a riot_public_ipv6
        # (backwards-compat). Si hay game_module, los endpoints v6 ya
        # vienen incluidos en module.public_endpoints() (el módulo los
        # construye con family='ipv6') — no duplicar.
        if self._game_module is None:
            for host in targets.riot_public_ipv6:
                ping_specs.append(
                    (
                        host,
                        f"riot_public:{host}:v6",
                        _PROVIDER_RIOT_PUBLIC,
                        "ipv6",
                    )
                )

        notify(f"Pings en paralelo: {len(ping_specs)} probes")
        log.info("stage.start pings", extra={"event": "stage.start", "stage": "pings"})
        ping_results = self._run_pings_in_parallel(
            ping_specs, params.ping_count, params.ping_timeout_ms
        )
        probes.extend(ping_results)
        log.info(
            "stage.finish pings",
            extra={
                "event": "stage.finish",
                "stage": "pings",
                "n_probes": len(ping_results),
            },
        )

        # --- Etapa 2b: medicion DNS serial (Fase 12a.2) ---
        # CORRE SERIE (no ThreadPoolExecutor, Regla 9.2 no aplica aca):
        # getaddrinfo es syscall bloqueante corta (~30-80ms por host en
        # OS con DNS cacheado). N=4-6 hosts serial -> ~150-500ms de
        # overhead total ~= 1-3% del run corriente (14s). Paralelizar en
        # pool aportaria ahorro marginal con +complejidad de sync — no
        # vale la pena en v1. Los pings ya corrieron ANTES, DNS no los
        # condiciona (solo aporta un log record por host para
        # debug/observabilidad).
        dns_results: tuple[DnsResolution, ...] = ()
        if params.dns_enabled and self._dns_resolver is not None:
            hosts_for_dns = self._resolve_dns_hosts(params, targets)
            notify(f"Resolucion DNS: {len(hosts_for_dns)} hosts")
            log.info(
                "stage.start dns",
                extra={
                    "event": "stage.start",
                    "stage": "dns",
                    "n_hosts": len(hosts_for_dns),
                    "include_ipv6": params.dns_include_ipv6,
                    "timeout_ms": params.dns_timeout_ms,
                },
            )
            dns_results = self._resolve_dns_in_series(
                hosts_for_dns,
                params.dns_timeout_ms,
                params.dns_include_ipv6,
            )
            n_resolved = sum(1 for d in dns_results if d.outcome == DnsOutcome.SUCCESS)
            log.info(
                "stage.finish dns",
                extra={
                    "event": "stage.finish",
                    "stage": "dns",
                    "n_resolved": n_resolved,
                    "n_failed": len(dns_results) - n_resolved,
                    "n_total": len(dns_results),
                    "slowest_ms": max(
                        (d.elapsed_ms for d in dns_results if d.elapsed_ms),
                        default=None,
                    ),
                },
            )
        elif params.dns_enabled and self._dns_resolver is None:
            # Config pide DNS pero composition_root no inyecto resolver —
            # log warning, no falla (EP §1.2). Estado interno inconsistente
            # del wiring, no propagable al usuario.
            log.warning("dns.enabled=True pero dns_resolver=None — se salta etapa")

        # --- Etapa 3b: deteccion de game server + (si hay) ping al server ---
        notify("Deteccion de partida activa")
        log.info(
            "stage.start detect_game_server",
            extra={"event": "stage.start", "stage": "detect_game_server"},
        )
        # Fase 13.2: si hay ``game_module`` inyectado, la detección la hace
        # el módulo (que delega a su ConnectionInspector y conoce los
        # process_names del juego + anti-telemetría del publisher). Si no,
        # backwards-compat: el orquestador usa su ``connection_inspector``
        # + ``targets.game_process_names`` (path Riot hardcodeado de hoy).
        if self._game_module is not None:
            active_game_server = self._safe_detect_active_server_via_module(
                self._game_module
            )
            # El provider del probe al server lo decide el módulo (ej.
            # "riot_game_server" para LoL) — así no tocamos analysis.
            game_server_provider = self._game_module.game_server_provider()
        else:
            active_game_server = self._safe_detect_active_server(
                targets.game_process_names
            )
            game_server_provider = _PROVIDER_RIOT_GAME_SERVER

        if active_game_server is not None:
            notify("Riot: servidor de partida real")
            probes.append(
                self._ping.ping(
                    target_ip=active_game_server.ip,
                    target_name=game_server_provider,
                    provider=game_server_provider,
                    count=params.ping_count,
                    timeout_ms=params.ping_timeout_ms,
                    family="ipv4",
                )
            )
        gs_extra: dict[str, object] = {}
        if active_game_server is not None:
            gs_extra["game_server_ip"] = active_game_server.ip
        log.info(
            "stage.finish detect_game_server",
            extra={
                "event": "stage.finish",
                "stage": "detect_game_server",
                "game_server_detected": active_game_server is not None,
                **gs_extra,
            },
        )

        # --- Etapa 4: traceroutes en paralelo ---
        # Heuristic: traceroute a cloudflare (proxy de ruta internacional)
        # y al primer endpoint del juego (proxy de ruta al publisher).
        # 2 en paralelo = ~7s vs ~14s en serie.
        # Fase 13.2: si hay game_module, el primer endpoint del juego
        # viene de module.public_endpoints()[0] (respetando el provider
        # del módulo — ej. "riot_public" para LoL). Si no, cae al
        # targets.riot_public[0] hardcodeado (backwards-compat).
        # Fase 12a.4: si hay targets IPv6 seteados, duplicamos specs v6.
        traceroute_specs: list[tuple[str, str, str]] = [
            (targets.cloudflare, _PROVIDER_CLOUDFLARE, "ipv4"),
        ]
        if self._game_module is not None:
            game_endpoints = self._game_module.public_endpoints()
            for ep in game_endpoints:
                if ep.family == "ipv4":
                    traceroute_specs.append((ep.host, ep.provider, "ipv4"))
                    break  # solo el primer v4 del juego como proxy de ruta
        elif targets.riot_public:
            traceroute_specs.append(
                (targets.riot_public[0], _PROVIDER_RIOT_PUBLIC, "ipv4")
            )
        # Specs v6 (opt-in): Cloudflare DNS v6 siempre es buen proxy de
        # ruta internacional IPv6. El endpoint v6 del juego: si hay
        # game_module viene incluido en public_endpoints (tomamos el 1er
        # ipv6); si no, cae a targets.riot_public_ipv6[0] (backwards-compat).
        if targets.cloudflare_ipv6 is not None:
            traceroute_specs.append(
                (targets.cloudflare_ipv6, _PROVIDER_CLOUDFLARE, "ipv6")
            )
        if self._game_module is not None:
            for ep in game_endpoints:
                if ep.family == "ipv6":
                    traceroute_specs.append((ep.host, ep.provider, "ipv6"))
                    break
        elif targets.riot_public_ipv6:
            traceroute_specs.append(
                (targets.riot_public_ipv6[0], _PROVIDER_RIOT_PUBLIC, "ipv6")
            )

        notify(f"Traceroutes en paralelo: {len(traceroute_specs)} rutas")
        log.info(
            "stage.start traceroutes",
            extra={"event": "stage.start", "stage": "traceroutes"},
        )
        traceroutes.extend(
            self._run_traceroutes_in_parallel(
                traceroute_specs,
                params.traceroute_max_hops,
                params.traceroute_timeout_ms,
            )
        )
        log.info(
            "stage.finish traceroutes",
            extra={
                "event": "stage.finish",
                "stage": "traceroutes",
                "n_traceroutes": len(traceroutes),
            },
        )

        # --- Etapa 5: baseline historico por provider ---
        notify("Calculo de baseline historico")
        log.info(
            "stage.start baseline",
            extra={"event": "stage.start", "stage": "baseline"},
        )
        baselines: dict[str, HistoricalBaseline] = {}
        # Pedir una conexion NUEVA aqui (en el hilo del execute) — Regla
        # de Oro 9.1. compute_baseline lee de probe_results. La conn se
        # cierra al terminar la Etapa 5 (read-only, no necesitamos
        # compartirla con save_run que pide la suya).
        # Si db_factory es None (tests), baselines queda vacio (skip).
        if self._db_factory is not None:
            baseline_conn = self._db_factory.create_connection()
            try:
                for provider in (
                    _PROVIDER_LOCAL,
                    _PROVIDER_GOOGLE,
                    _PROVIDER_CLOUDFLARE,
                    _PROVIDER_QUAD9,
                    _PROVIDER_RIOT_PUBLIC,
                    _PROVIDER_RIOT_GAME_SERVER,
                ):
                    baselines[provider] = compute_baseline(
                        baseline_conn,
                        provider=provider,
                        period_days=params.baseline_period_days,
                    )
            finally:
                baseline_conn.close()
        self.last_baselines = baselines  # cache publica para UI
        log.info(
            "stage.finish baseline",
            extra={
                "event": "stage.finish",
                "stage": "baseline",
                "n_baselines": len(baselines),
                "db_available": self._db_factory is not None,
            },
        )

        # --- Etapa 6: motor de recomendacion ---
        notify("Motor de recomendacion")
        log.info(
            "stage.start recommendation",
            extra={"event": "stage.start", "stage": "recommendation"},
        )
        recommendation = evaluate_recommendation(
            probes,
            active_game_server=active_game_server is not None,
            baselines=baselines,
            packet_loss_warning_pct=params.packet_loss_warning_pct,
            packet_loss_critical_pct=params.packet_loss_critical_pct,
            jitter_warning_ms=params.jitter_warning_ms,
            jitter_critical_ms=params.jitter_critical_ms,
        )

        # Completar el score (el engine devuelve 0 como placeholder; el
        # score real viene de analysis/score.py).
        score = compute_network_score(probes, baselines)
        from dataclasses import replace

        recommendation = replace(recommendation, score=score)
        log.info(
            "stage.finish recommendation",
            extra={
                "event": "stage.finish",
                "stage": "recommendation",
                "verdict": recommendation.verdict,
                "score": score,
                "n_explanations": len(recommendation.explanation),
            },
        )

        # --- Etapa 6b: snapshot de interfaz de red serial (Fase 12a.3) ---
        # Plan 12a.3: corre DESPUES de recommendation (no afecta decisiones
        # del motor v1) y ANTES de persistence. Si netsh cuelga (raro, hasta
        # timeout 3000ms), no retrasa pings/traceroutes ni el calculo del
        # veredicto — solo la persistencia al final. EP §1.2: el inspector
        # nunca lanza (contrato Protocol); por belt-and-suspenders envolvemos
        # en try/except por si un inspector buggy lo hace — fallback None.
        interface_snapshot: NetworkInterfaceSnapshot | None = None
        if params.inspect_interface_enabled and self._interface_inspector is not None:
            notify("Deteccion de interfaz de red")
            log.info(
                "stage.start interface",
                extra={
                    "event": "stage.start",
                    "stage": "interface",
                    "default_route_hint": params.default_route_iface_hint,
                },
            )
            interface_snapshot = self._safe_inspect_interface(
                params.default_route_iface_hint
            )
            ints_extra: dict[str, object] = {"interface_type": None}
            if interface_snapshot is not None:
                ints_extra["interface_type"] = interface_snapshot.type.name
                ints_extra["interface_name"] = interface_snapshot.name
                ints_extra["wifi_ssid"] = interface_snapshot.wifi_ssid
                ints_extra["wifi_signal_dbm"] = interface_snapshot.wifi_signal_dbm
            log.info(
                "stage.finish interface",
                extra={
                    "event": "stage.finish",
                    "stage": "interface",
                    **ints_extra,
                },
            )
        elif params.inspect_interface_enabled and (self._interface_inspector is None):
            log.warning(
                "inspect_interface=True pero interface_inspector=None "
                "— se salta etapa"
            )

        finished_at = now.now()
        run = DiagnosticRun(
            run_id=rid,
            started_at=started_at,
            finished_at=finished_at,
            probes=probes,
            traceroutes=traceroutes,
            active_game_server=active_game_server,
            recommendation=recommendation,
            dns_results=dns_results,
            interface_snapshot=interface_snapshot,
        )

        # --- Etapa 7: persistencia ---
        notify("Persistencia")
        log.info(
            "stage.start persistence",
            extra={"event": "stage.start", "stage": "persistence"},
        )
        persistence_ok = True
        try:
            self._repo.save_run(run)
        except Exception:  # noqa: BLE001
            # EP §7: DB corrupta/inaccesible no pierde la corrida en memoria.
            persistence_ok = False
            log.exception(
                "stage.error persistence",
                extra={"event": "stage.error", "stage": "persistence"},
            )
        log.info(
            "stage.finish persistence",
            extra={
                "event": "stage.finish",
                "stage": "persistence",
                "success": persistence_ok,
            },
        )

        duration_ms = (finished_at - started_at).total_seconds() * 1000.0
        interface_type_for_log = (
            interface_snapshot.type.name if interface_snapshot else None
        )
        log.info(
            "run.finish",
            extra={
                "event": "run.finish",
                "duration_ms": round(duration_ms, 2),
                "n_probes": len(probes),
                "n_traceroutes": len(traceroutes),
                "n_dns": len(dns_results),
                "interface_type": interface_type_for_log,
                "verdict": recommendation.verdict,
                "score": score,
                "persistence_ok": persistence_ok,
            },
        )

        notify("Listo")
        return run

    def _safe_detect_active_server(
        self, process_names: set[str]
    ) -> ActiveGameServerInfo | None:
        """Wrapper defensivo sobre ConnectionInspector.

        EP §1.2: cualquier fallo del inspector se traduce a None con log,
        nunca excepcion a la UI. El inspector real (ActiveGameServerDetector)
        ya cumple este contrato, pero este wrapper cubre cualquier bug
        futuro o implementacion alternativa.
        """
        try:
            return self._inspector.detect_active_game_server(process_names)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "ConnectionInspector fallo inesperadamente: %r -> None", exc
            )
            return None

    def _safe_detect_active_server_via_module(
        self, module: GameDiagnosticsModule
    ) -> ActiveGameServerInfo | None:
        """Wrapper defensivo sobre ``GameDiagnosticsModule.detect_active_server``.

        Fase 13.2: belt-and-suspenders sobre el contrato del módulo, que
        ya garantiza no-raise (EP §1.2). Si un módulo buggy levanta, lo
        traducimos a ``None`` con log — la corrida continúa sin partida
        activa (mejor que crashear la UI).
        """
        try:
            return module.detect_active_server()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "GameDiagnosticsModule.detect_active_server fallo: %r -> None", exc
            )
            return None

    def _safe_inspect_interface(
        self, default_route_iface_hint: str | None
    ) -> NetworkInterfaceSnapshot | None:
        """Wrapper defensivo sobre NetworkInterfaceInspector (Fase 12a.3).

        EP §1.2: el contrato del Protocol garantiza que `inspect()` nunca
        lanza — traduce todo a `type=OTHER` con error. Por
        belt-and-suspenders envolvemos en try/except por si un inspector
        buggy levanta excepcion; devolvemos None y la corrida continúa
        (interface_snapshot queda None, no se persiste fila en
        interface_snapshots — acceptaable falla graceful).
        """
        try:
            return self._interface_inspector.inspect(  # type: ignore[union-attr]
                default_route_iface_hint=default_route_iface_hint,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "NetworkInterfaceInspector fallo inesperadamente: %r -> None",
                exc,
            )
            return None

    def _resolve_dns_hosts(
        self,
        params: DiagnosticParams,
        targets: DiagnosticTargets,
    ) -> tuple[str, ...]:
        """Determina qué hosts resolver en la etapa DNS (Fase 12a.2).

        Prioridad:
        1. Si `params.dns_hosts` no es vacío, usarlo (override del usuario).
        2. Si no, caer a `targets.riot_public` (sensato default: Riot rota
           hostname dentro de CDN/hosting, util saber si DNS responde lento).
        Se omiten strings que perezcan IPs literales (no tiene sentido
        medir DNS sobre una IP — `socket.getaddrinfo` lo resuelve trivial).
        """
        candidate: tuple[str, ...]
        if params.dns_hosts:
            candidate = params.dns_hosts
        else:
            candidate = tuple(targets.riot_public)
        # Filtrar IP-ish literales (v4 o v6 contiene ':' o solo dígitos/puntos).
        # Sencillo heur: si el primer char es dígito o contiene ':', skip.
        return tuple(h for h in candidate if not _looks_like_ip_literal(h))

    def _resolve_dns_in_series(
        self,
        hosts: tuple[str, ...],
        timeout_ms: int,
        include_ipv6: bool,
    ) -> tuple[DnsResolution, ...]:
        """Resuelve.Hosts serial con el DnsResolver inyectado.

        EP §1.2: el contrato de `DnsResolver.resolve` garantiza que nunca
        lanza (traduce todo a DnsResolution con outcome apropiado). Por
        belt-and-suspenders, envolvemos cada call en try/except — un
        resolver buggy que levante excepcion se traduce a un placeholder
        DnsResolution(outcome=ERROR, ...) sin abortar la etapa.
        """
        results: list[DnsResolution] = []
        families = ("ipv4", "ipv6") if include_ipv6 else ("ipv4",)
        for host in hosts:
            for fam in families:
                try:
                    results.append(
                        self._dns_resolver.resolve(  # type: ignore[union-attr]
                            host, family=fam, timeout_ms=timeout_ms
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "DnsResolver fallo inesperadamente para %s/%s: %r",
                        host,
                        fam,
                        exc,
                    )
                    results.append(
                        DnsResolution(
                            hostname=host,
                            resolved_ip=None,
                            outcome=DnsOutcome.ERROR,
                            elapsed_ms=None,
                            family=fam,
                            error=f"resolver bug: {exc!r}",
                        )
                    )
        return tuple(results)

    def _run_pings_in_parallel(
        self,
        specs: list[tuple[str, str, str, str]],
        count: int,
        timeout_ms: int,
    ) -> list[ProbeResult]:
        """Lanza todos los pings en paralelo con ThreadPoolExecutor.

        Cada spec es (target_ip, target_name, provider, family). El family
        se propaga a ``PingRunner.ping(family=...)`` (Fase 12a.4); si todas
        las specs son 'ipv4' el comportamiento es idéntico a pre-12a.4.

        EP §1.2: un ping individual que falle no aborta los demas. Cada
        ``PingRunner.ping()`` ya captura excepciones y devuelve un
        ``ProbeResult`` con outcome TIMEOUT/UNREACHABLE. Adicionalmente,
        envolvemos cada call en try/except para robustez extra: si el
        runner LISKORR fuera buggy, devolvemos un Placeholder TIMEOUT
        sin tirar el pool entero.

        Devuelve los ``ProbeResult`` en el MISMO orden que ``specs`` (semaforo
        via indice). Esto permite que la UI los presente por provider en
        orden estable.
        """
        results: list[ProbeResult | None] = [None] * len(specs)

        def _do_one(
            idx: int, target_ip: str, target_name: str, provider: str, family: str
        ) -> None:
            try:
                results[idx] = self._ping.ping(
                    target_ip=target_ip,
                    target_name=target_name,
                    provider=provider,
                    count=count,
                    timeout_ms=timeout_ms,
                    family=family,
                )
            except Exception as exc:  # noqa: BLE001
                # Defense-in-depth: si un runner buggy levanta excepcion,
                # dejamos un Probe TIMEOUT en su lugar. No propagar.
                logger.exception(
                    "PingRunner fallo inesperadamente para %s/%s (%s): %r",
                    provider,
                    target_ip,
                    family,
                    exc,
                )
                results[idx] = self._placeholder_timeout(
                    target_ip, target_name, provider, family=family
                )

        with ThreadPoolExecutor(
            max_workers=_PROBE_WORKERS, thread_name_prefix="gnd-ping"
        ) as pool:
            futures = [
                pool.submit(_do_one, i, ip, name, prov, fam)
                for i, (ip, name, prov, fam) in enumerate(specs)
            ]
            for f in futures:
                f.result()  # propaga excepciones del _do_one (ya try/except)
        # Por patron defense-in-depth, filter-None no debe ser necesario.
        return [r for r in results if r is not None]

    def _run_traceroutes_in_parallel(
        self,
        specs: list[tuple[str, str, str]],
        max_hops: int,
        timeout_ms: int,
    ) -> list[TracerouteResult]:
        """Lanza traceroutes en paralelo. Mismo patron que pings.

        Cada spec es (target_ip, target_provider, family). El family se
        propaga a ``TracerouteRunner.traceroute(family=...)`` (Fase 12a.4).
        """
        results: list[TracerouteResult | None] = [None] * len(specs)

        def _do_one(
            idx: int, target_ip: str, target_provider: str, family: str
        ) -> None:
            try:
                results[idx] = self._tracer.traceroute(
                    target_ip=target_ip,
                    target_provider=target_provider,
                    max_hops=max_hops,
                    timeout_ms=timeout_ms,
                    family=family,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "TracerouteRunner fallo inesperadamente para %s (%s): %r",
                    target_provider,
                    family,
                    exc,
                )
                results[idx] = TracerouteResult(
                    target_provider=target_provider,
                    hops=[],
                    culprit_hop_index=None,
                    family=family,
                )

        with ThreadPoolExecutor(
            max_workers=_TRACEROUTE_WORKERS, thread_name_prefix="gnd-tracer"
        ) as pool:
            futures = [
                pool.submit(_do_one, i, ip, prov, fam)
                for i, (ip, prov, fam) in enumerate(specs)
            ]
            for f in futures:
                f.result()
        return [r for r in results if r is not None]

    def _placeholder_timeout(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        *,
        family: str = "ipv4",
    ) -> ProbeResult:
        """Crea un ProbeResult TIMEOUT placeholder (defense-in-depth)."""
        return ProbeResult(
            target_name=target_name,
            target_ip=target_ip,
            provider=provider,
            outcome=ProbeOutcomeKind.TIMEOUT,
            stats=None,
            timestamp=datetime.now(),
            family=family,
        )
