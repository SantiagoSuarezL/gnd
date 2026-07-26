"""Caso de uso RunFullDiagnostics — orquesta una corrida completa.

Application layer de ARCHITECTURE.md §2. Consume los Protocol del
dominio inyectados por constructor (EP §3 DI). El wiring de qué
implementacion concreta usar vive en `composition_root`.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from gnd.analysis.baseline import compute_baseline
from gnd.analysis.score import compute_network_score
from gnd.domain.ports.connection_inspector import ConnectionInspector
from gnd.domain.ports.database import DatabaseConnectionFactory
from gnd.domain.ports.diagnostics_repository import DiagnosticsRepository
from gnd.domain.ports.ping_runner import PingRunner
from gnd.domain.ports.traceroute_runner import TracerouteRunner
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.historical_baseline import HistoricalBaseline
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


@dataclass(frozen=True)
class DiagnosticTargets:
    """Targets de la corrida, derivados de config (inyectados por el caller).

    Mantener estos valores fuera del caso de uso permite que el
    composition_root los lea de `GndSettings` y que los tests inyecten
    valores fijos sin tocar config real (EP §4).
    """

    gateway_ip: str
    google_dns: str
    cloudflare: str
    quad9: str
    riot_public: list[str]
    game_process_names: set[str]


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

        started_at = now.now()
        probes: list[ProbeResult] = []
        traceroutes: list[TracerouteResult] = []

        # --- Etapa 1-3: pings en paralelo ---
        # ARCHITECTURE.md §6: paralelizar sondeos. Cada ping es subprocess
        # blocking (~19s con count=20), correrlos en serie da 115s+ para 6
        # probes. ThreadPoolExecutor los lanza en paralelo: tiempo total
        # ~= max(individual) ~= ~8-10s (con count=8) en vez de 6x*8s.
        # Cada worker es thread-safe: RealPingRunner no comparte estado,
        # socket.create_connection y subprocess.run son thread-safe en
        # CPython. EP §1.2 preservado: un probe que falla devuelve su
        # ProbeResult con outcome adecuado, no aborta el pool.

        # Lista de specs: (target_ip, target_name, provider)
        ping_specs: list[tuple[str, str, str]] = [
            (targets.gateway_ip, "gateway", _PROVIDER_LOCAL),
            (targets.google_dns, "google_dns", _PROVIDER_GOOGLE),
            (targets.cloudflare, "cloudflare", _PROVIDER_CLOUDFLARE),
            (targets.quad9, "quad9", _PROVIDER_QUAD9),
        ]
        for host in targets.riot_public:
            ping_specs.append((host, f"riot_public:{host}", _PROVIDER_RIOT_PUBLIC))

        notify(f"Pings en paralelo: {len(ping_specs)} probes")
        ping_results = self._run_pings_in_parallel(
            ping_specs, params.ping_count, params.ping_timeout_ms
        )
        probes.extend(ping_results)

        # --- Etapa 3b: deteccion de game server + (si hay) ping al server ---
        notify("Deteccion de partida activa")
        active_game_server = self._safe_detect_active_server(targets.game_process_names)

        if active_game_server is not None:
            notify("Riot: servidor de partida real")
            probes.append(
                self._ping.ping(
                    target_ip=active_game_server.ip,
                    target_name="riot_game_server",
                    provider=_PROVIDER_RIOT_GAME_SERVER,
                    count=params.ping_count,
                    timeout_ms=params.ping_timeout_ms,
                )
            )

        # --- Etapa 4: traceroutes en paralelo ---
        # Heuristic: traceroute a cloudflare (proxy de ruta internacional)
        # y a riot_public[0] (proxy de ruta a Riot). 2 en paralelo = ~7s
        # vs ~14s en serie.
        traceroute_specs: list[tuple[str, str]] = [
            (targets.cloudflare, _PROVIDER_CLOUDFLARE),
        ]
        if targets.riot_public:
            traceroute_specs.append((targets.riot_public[0], _PROVIDER_RIOT_PUBLIC))

        notify(f"Traceroutes en paralelo: {len(traceroute_specs)} rutas")
        traceroutes.extend(
            self._run_traceroutes_in_parallel(
                traceroute_specs,
                params.traceroute_max_hops,
                params.traceroute_timeout_ms,
            )
        )

        # --- Etapa 5: baseline historico por provider ---
        notify("Calculo de baseline historico")
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

        # --- Etapa 6: motor de recomendacion ---
        notify("Motor de recomendacion")
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

        finished_at = now.now()
        run = DiagnosticRun(
            run_id=rid,
            started_at=started_at,
            finished_at=finished_at,
            probes=probes,
            traceroutes=traceroutes,
            active_game_server=active_game_server,
            recommendation=recommendation,
        )

        # --- Etapa 7: persistencia ---
        notify("Persistencia")
        try:
            self._repo.save_run(run)
        except Exception:  # noqa: BLE001
            # EP §7: DB corrupta/inaccesible no pierde la corrida en memoria.
            logger.exception("Fallo persistencia de la corrida %s", rid)

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

    def _run_pings_in_parallel(
        self,
        specs: list[tuple[str, str, str]],
        count: int,
        timeout_ms: int,
    ) -> list[ProbeResult]:
        """Lanza todos los pings en paralelo con ThreadPoolExecutor.

        EP §1.2: un ping individual que falle no aborta los demas. Cada
        `PingRunner.ping()` ya captura excepciones y devuelve un
        `ProbeResult` con outcome TIMEOUT/UNREACHABLE. Adicionalmente,
        envolvemos cada call en try/except para robustez extra: si el
        runner LISKORR fuera buggy, devolvemos un Placeholder TIMEOUT
        sin tirar el pool entero.

        Devuelve los `ProbeResult` en el MISMO orden que `specs` (semaforo
        via indice). Esto permite que la UI los presente por provider en
        orden estable.
        """
        results: list[ProbeResult | None] = [None] * len(specs)

        def _do_one(idx: int, target_ip: str, target_name: str, provider: str) -> None:
            try:
                results[idx] = self._ping.ping(
                    target_ip=target_ip,
                    target_name=target_name,
                    provider=provider,
                    count=count,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001
                # Defense-in-depth: si un runner buggy levanta excepcion,
                # dejamos un Probe TIMEOUT en su lugar. No propagar.
                logger.exception(
                    "PingRunner fallo inesperadamente para %s/%s: %r",
                    provider,
                    target_ip,
                    exc,
                )
                results[idx] = self._placeholder_timeout(
                    target_ip, target_name, provider
                )

        with ThreadPoolExecutor(
            max_workers=_PROBE_WORKERS, thread_name_prefix="gnd-ping"
        ) as pool:
            futures = [
                pool.submit(_do_one, i, ip, name, prov)
                for i, (ip, name, prov) in enumerate(specs)
            ]
            for f in futures:
                f.result()  # propaga excepciones del _do_one (ya try/except)
        # Por patron defense-in-depth, filter-None no debe ser necesario.
        return [r for r in results if r is not None]

    def _run_traceroutes_in_parallel(
        self,
        specs: list[tuple[str, str]],
        max_hops: int,
        timeout_ms: int,
    ) -> list[TracerouteResult]:
        """Lanza traceroutes en paralelo. Mismo patron que pings."""
        results: list[TracerouteResult | None] = [None] * len(specs)

        def _do_one(idx: int, target_ip: str, target_provider: str) -> None:
            try:
                results[idx] = self._tracer.traceroute(
                    target_ip=target_ip,
                    target_provider=target_provider,
                    max_hops=max_hops,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "TracerouteRunner fallo inesperadamente para %s: %r",
                    target_provider,
                    exc,
                )
                results[idx] = TracerouteResult(
                    target_provider=target_provider,
                    hops=[],
                    culprit_hop_index=None,
                )

        with ThreadPoolExecutor(
            max_workers=_TRACEROUTE_WORKERS, thread_name_prefix="gnd-tracer"
        ) as pool:
            futures = [
                pool.submit(_do_one, i, ip, prov) for i, (ip, prov) in enumerate(specs)
            ]
            for f in futures:
                f.result()
        return [r for r in results if r is not None]

    def _placeholder_timeout(
        self, target_ip: str, target_name: str, provider: str
    ) -> ProbeResult:
        """Crea un ProbeResult TIMEOUT placeholder (defense-in-depth)."""
        return ProbeResult(
            target_name=target_name,
            target_ip=target_ip,
            provider=provider,
            outcome=ProbeOutcomeKind.TIMEOUT,
            stats=None,
            timestamp=datetime.now(),
        )
