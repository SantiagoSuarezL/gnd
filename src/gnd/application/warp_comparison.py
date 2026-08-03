"""Caso de uso WarpComparison — orquesta comparación WARP on vs off (Fase 12b.4).

Application layer de ARCHITECTURE.md §2. Consume Protocol del dominio
inyectados por constructor (EP §3 DI). Wiring en composition_root.

Flujo:
1. Verifica disponibilidad de WarpController
2. Guarda estado original de WARP
3. Si WARP estaba on -> deshabilita, corre diagnóstico (warp_off_run)
4. Habilita WARP, corre diagnóstico (warp_on_run)
5. Restaura estado original
6. Computa deltas y genera WarpComparisonResult
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.domain.ports.warp_controller import WarpController, WarpError, WarpStatus
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.warp_comparison import WarpComparisonDelta, WarpComparisonResult

logger = logging.getLogger(__name__)


def _append_failed_note(parts: list[str], failed_providers: list[str] | None) -> None:
    """Anexa nota de providers con medición fallida al explanation.

    Regla 12b.4.5 (bug 2 fix): providers con probes non-SUCCESS en al menos
    una corrida se listan al final del explanation para que el usuario vea
    qué medición no se computó (vs la trampa vieja de mostrarlas como 0.0
    y -100% "mejora perfecta").
    """
    if not failed_providers:
        return
    parts.append(f"Medición fallida (excluida): {', '.join(failed_providers)}")


class Sleeper(Protocol):
    """Callable que duerme ``seconds`` segundos. Inyectable en tests.

    Mismo patrón que RouteMonitor (Regla 8.3) y ReportsScheduler: DI
    permite tests deterministas sin time.sleep real. Default en producción
    usa ``time.sleep``.
    """

    def __call__(self, seconds: float) -> None: ...


class _DefaultSleeper:
    def __call__(self, seconds: float) -> None:
        if seconds > 0.0:
            time.sleep(seconds)


class PerfClock(Protocol):
    """Callable que devuelve elapsed time en segundos (float). Inyectable.

    Mismo patrón que ``Sleeper``: en producción usa ``time.perf_counter``,
    en tests se puede inyectar un clock fake que avanza simuladamente para
    tests deterministas del poll de status (sin time.sleep real).
    """

    def __call__(self) -> float: ...


class _DefaultPerfClock:
    def __call__(self) -> float:
        return time.perf_counter()


@dataclass(frozen=True)
class WarpComparisonParams:
    """Parámetros de ejecución de la comparación WARP.

    Extiende DiagnosticParams con flags específicos de WARP.
    """

    diagnostic_params: DiagnosticParams
    """Parámetros base del diagnóstico (count, timeouts, thresholds, etc.)."""

    restore_original_state: bool = True
    """Si True, restaura el estado WARP original al terminar (on/off)."""

    skip_if_warp_unavailable: bool = True
    """Si True y WarpController no está disponible, devuelve resultado
    con warp_controller_available=False en vez de lanzar excepción."""

    enable_timeout_s: float = 15.0
    """Timeout total para esperar que WARP transicione a 'connected' tras
    ``warp-cli connect``. ``warp-cli connect`` no bloquea hasta conectar —
    el daemon transiciona async a 'connecting' y luego a 'connected' (1-3s
    típicamente, puede tardar más en redes lentas). El use case hace
    poll de status cada ``poll_interval_s`` hasta alcanzar el estado
    objetivo o agotar este timeout (Regla 12b.4.4: race fix)."""

    disable_timeout_s: float = 10.0
    """Timeout para esperar 'disconnected' tras ``warp-cli disconnect``."""

    poll_interval_s: float = 0.5
    """Intervalo entre polls de ``warp-cli status`` al esperar transición."""


class WarpComparisonUseCase:
    """Orquesta comparación WARP on vs off.

    DI completa: recibe RunFullDiagnostics + WarpController + Sleeper. El
    caller (composition_root) decide implementaciones reales vs fakes.

    EP §1.2: cualquier fallo en subprocess de warp-cli o diagnóstico
    individual se captura y se refleja en el resultado (no crashea la UI).
    """

    def __init__(
        self,
        *,
        diagnostics_use_case: RunFullDiagnostics,
        warp_controller: WarpController,
        sleeper: Sleeper | None = None,
        perf_clock: PerfClock | None = None,
    ) -> None:
        self._diagnostics = diagnostics_use_case
        self._warp = warp_controller
        self._sleeper: Sleeper = sleeper or _DefaultSleeper()
        self._perf_clock: PerfClock = perf_clock or _DefaultPerfClock()

    def execute(
        self,
        targets: DiagnosticTargets,
        params: WarpComparisonParams,
        *,
        clock: type = None,
    ) -> WarpComparisonResult:
        """Ejecuta la comparación completa WARP on vs off.

        Args:
            targets: Targets de diagnóstico (IPs, hostnames, game process names).
            params: Parámetros de la comparación (incluye diagnostic_params).
            clock: Callable () -> datetime para tests deterministas.

        Returns:
            WarpComparisonResult con ambas corridas, deltas y veredicto.

        EP §1.2: nunca lanza excepción a la UI. Errores de warp-cli o
        diagnóstico se loguean y se reflejan en el resultado.
        """
        from datetime import datetime

        now = clock or datetime

        # 1. Verificar disponibilidad del controller
        if not self._is_warp_available():
            if params.skip_if_warp_unavailable:
                logger.warning(
                    "WARP controller no disponible — comparación saltada",
                    extra={
                        "event": "warp_comparison.skip",
                        "reason": "controller_unavailable",
                    },
                )
                return self._build_unavailable_result()
            raise WarpError("WARP controller no disponible (warp-cli no en PATH)")

        # 2. Guardar estado original
        original_status = self._safe_get_status()
        logger.info(
            "Estado WARP original",
            extra={
                "event": "warp_comparison.original_status",
                "warp_connected": original_status.connected,
                "registration": original_status.registration_status,
            },
        )

        result: WarpComparisonResult | None = None
        try:
            # 3. Ejecutar WARP OFF (espera 'disconnected' antes de medir)
            warp_off_run, warp_off_duration = self._run_with_warp_state(
                targets, params.diagnostic_params, params, warp_enabled=False, clock=now
            )

            # 4. Ejecutar WARP ON (espera 'connected' antes de medir)
            warp_on_run, warp_on_duration = self._run_with_warp_state(
                targets, params.diagnostic_params, params, warp_enabled=True, clock=now
            )

            # 5. Calcular deltas y veredicto
            result = self._compute_comparison(
                warp_off_run=warp_off_run,
                warp_on_run=warp_on_run,
                warp_off_duration_ms=warp_off_duration,
                warp_on_duration_ms=warp_on_duration,
            )

            logger.info(
                "Comparación WARP completada",
                extra={
                    "event": "warp_comparison.finish",
                    "verdict": result.overall_verdict,
                    "score_delta": result.score_delta,
                    "warp_off_score": result.warp_off_score,
                    "warp_on_score": result.warp_on_score,
                },
            )
        except WarpError as exc:
            # Regla 12b.4.4: si el poll de status agota timeout (o falla
            # enable/disable) → abortar con resultado claro, no propagar
            # excepción a la UI (EP §1.2). La fase que falló indica cuál
            # medición no se hizo.
            logger.error(
                "Comparación WARP abortada por fallo de estado WARP: %s",
                exc,
                extra={
                    "event": "warp_comparison.abort_state_timeout",
                    "reason": "state_timeout",
                    "error_message": str(exc),
                },
            )
            result = self._build_state_timeout_result(exc)
        finally:
            # 6. Restaurar estado original — Regla 12b.4.2: replica modo +
            # protocolo, o fail-safe si no se detectaron. Devuelve warning
            # si el restore no pudo ser fiel (caller lo adjunta al result).
            if params.restore_original_state:
                restore_warning = self._restore_original_state(original_status)
                if result is not None and restore_warning is not None:
                    from dataclasses import replace

                    result = replace(result, restore_warning=restore_warning)

        # Post-try/except: resultivamente seteado (sea comparación exitosa
        # o abort por state timeout). EP §1.2: nunca devolvemos None.
        assert result is not None  # noqa: S101 - invariant post-try
        return result

    def _is_warp_available(self) -> bool:
        """Verifica si warp-cli está disponible (sin lanzar)."""
        # Preferir la property `available` si el controller la expone
        # (RealWarpController: False si warp-cli no en PATH; Fake: True).
        # Esto evita consumir una llamada de get_status solo para el check,
        # preservando la secuencia de status para los polls reales.
        available = getattr(self._warp, "available", None)
        if available is not None:
            return bool(available)
        try:
            self._warp.get_status()
            return True
        except WarpError:
            return False
        except Exception:  # noqa: BLE001 - defense in depth
            logger.exception("Error inesperado verificando disponibilidad WARP")
            return False

    def _safe_get_status(self) -> WarpStatus:
        """Obtiene estado WARP capturando cualquier excepción."""
        try:
            return self._warp.get_status()
        except WarpError as exc:
            logger.warning("Error obteniendo estado WARP: %s", exc)
            # Devolver status "desconocido" pero no lanzar
            return WarpStatus(
                connected=False,
                registration_status="error",
                connection_status="error",
                warp_plus=False,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error inesperado en get_status")
            return WarpStatus(
                connected=False,
                registration_status="error",
                connection_status="error",
                warp_plus=False,
            )

    def _run_with_warp_state(
        self,
        targets: DiagnosticTargets,
        diag_params: DiagnosticParams,
        params: WarpComparisonParams,
        *,
        warp_enabled: bool,
        clock: type,
    ) -> tuple[DiagnosticRun, float]:
        """Ajusta estado WARP, espera transición completa, corre diagnóstico.

        Regla 12b.4.4 (race fix): ``warp-cli connect`` NO bloquea hasta
        conectar — el daemon transiciona async a 'connecting' y luego a
        'connected'. El diagnóstico arrancado antes del 'connected' pilla
        la interfaz de red en estado intermedio y reporta timeouts/DNS
        failed erróneamente. Este método hace poll de ``get_status()`` con
        backoff hasta alcanzar el estado objetivo o agotar el timeout. Si
        timeout → raises WarpError con mensaje claro, aborta la comparación.
        """
        label = "ON" if warp_enabled else "OFF"
        target_state = "connected" if warp_enabled else "disconnected"
        logger.info(
            "Preparando WARP %s para diagnóstico",
            label,
            extra={"event": f"warp_comparison.warp_{label.lower()}"},
        )

        start = time.perf_counter()
        try:
            if warp_enabled:
                self._warp.enable()
            else:
                self._warp.disable()

            # Esperar transición completa (no sleep ciego fijo).
            timeout = (
                params.enable_timeout_s if warp_enabled else params.disable_timeout_s
            )
            self._wait_for_warp_state(target_state, timeout, params.poll_interval_s)

            run = self._diagnostics.execute(targets, diag_params, clock=clock)
            duration_ms = (time.perf_counter() - start) * 1000

            logger.info(
                "Diagnóstico WARP %s completado",
                label,
                extra={
                    "event": f"warp_comparison.diag_{label.lower()}_finish",
                    "run_id": run.run_id,
                    "duration_ms": round(duration_ms, 2),
                    "score": run.recommendation.score,
                    "verdict": run.recommendation.verdict,
                },
            )
            return run, duration_ms

        except WarpError as exc:
            logger.exception("Error WARP %s: %s", label, exc)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error diagnóstico WARP %s", label)
            raise WarpError(
                f"Diagnóstico WARP {label} falló: {exc}",
                original_error=exc,
            ) from exc

    def _wait_for_warp_state(
        self, target_state: str, timeout_s: float, poll_interval_s: float
    ) -> None:
        """Poll ``warp-cli status`` hasta alcanzar ``target_state`` o timeout.

        Args:
            target_state: "connected" | "disconnected".
            timeout_s: tiempo máximo total a esperar.
            poll_interval_s: sleep entre polls.

        Raises:
            WarpError: si timeout agotado sin alcanzar ``target_state``.

        Regla 12b.4.4: no asumir ``warp-cli connect`` es sync; el daemon
        transiciona async. Poll activo + timeout = único mecanismo confiable.
        """
        elapsed = self._perf_clock()
        deadline = elapsed + timeout_s
        attempts = 0
        last_status = ""
        start_wait = elapsed
        while elapsed < deadline:
            attempts += 1
            status = self._safe_get_status()
            last_status = status.connection_status
            if status.connection_status == target_state:
                logger.info(
                    "WARP transicionó a %s tras %d polls (%.2fs)",
                    target_state,
                    attempts,
                    self._perf_clock() - start_wait,
                    extra={
                        "event": "warp_comparison.state_reached",
                        "warp_target_state": target_state,
                        "attempts": attempts,
                    },
                )
                return
            self._sleeper(poll_interval_s)
            elapsed = self._perf_clock()

        logger.error(
            "WARP no transicionó a %s tras %.1fs (último status=%s, %d polls)",
            target_state,
            timeout_s,
            last_status,
            attempts,
            extra={
                "event": "warp_comparison.state_timeout",
                "warp_target_state": target_state,
                "last_status": last_status,
                "attempts": attempts,
                "timeout_s": timeout_s,
            },
        )
        raise WarpError(
            f"WARP no alcanzó estado '{target_state}' en {timeout_s:.1f}s "
            f"(último status: {last_status}). Abortando comparación para no "
            f"medir contra una interfaz de red en estado intermedio. "
            f"Verificá que warp-cli y el daemon estén sanos."
        )

    def _restore_original_state(self, original: WarpStatus) -> str | None:
        """Restaura WARP al estado original (conectado/desconectado).

        Regla 12b.4.2: si WARP estaba conectado en un modo/protocolo
        específico (ej. "UDP" = WireGuard), el restore replica ese modo
        vía `set_mode()` + `set_tunnel_protocol()` ANTES de `enable()`.
        Si el adapter NO detectó el modo/protocolo original (None), NO
        restaura a ciego (dejaría WARP en MASQUE default, perdiendo el
        modo elegido por el usuario) — aplica fail-safe: deja WARP
        apagado (disable), loguea `restore_skip_mode_unknown` y devuelve
        un warning legible que el caller (use case) adjunta al
        WarpComparisonResult para que la UI lo muestre.

        Returns:
            str | None: mensaje de warning si el restore fue fall-safe
            (no pudo replicar modo/protocolo), None si el restore fue
            fiel o si original.connected era False (restore trivial).
        """
        try:
            if not original.connected:
                logger.info(
                    "Restaurando WARP a DESCONECTADO",
                    extra={
                        "event": "warp_comparison.restore",
                        "target": "disconnected",
                    },
                )
                self._warp.disable()
                return None

            # original.connected == True: replica modo/protocolo o fail-safe.
            mode = original.mode
            protocol = original.tunnel_protocol
            if mode is None or protocol is None:
                logger.warning(
                    "No se detectó el modo/protocolo WARP original "
                    "(mode=%s, protocol=%s) — no se restaura a ciego para no "
                    "perder el modo elegido por el usuario. WARP queda "
                    "desconectado; el usuario lo prende a mano en su modo "
                    "preferido.",
                    mode,
                    protocol,
                    extra={
                        "event": "warp_comparison.restore_skip_mode_unknown",
                        "reason": "mode_unknown",
                        "mode": mode,
                        "tunnel_protocol": protocol,
                    },
                )
                self._warp.disable()
                return (
                    "No se pudo detectar el modo/protocolo original de WARP. "
                    "Se dejó WARP desconectado para no sobreescribir tu "
                    "configuración. Prendelo a mano en el modo que uses "
                    "(ej. UDP=WireGuard)."
                )

            # Restore fiel: setea modo + protocolo, luego connect.
            logger.info(
                "Restaurando WARP a CONECTADO (mode=%s, protocol=%s)",
                mode,
                protocol,
                extra={
                    "event": "warp_comparison.restore",
                    "target": "connected",
                    "mode": mode,
                    "tunnel_protocol": protocol,
                },
            )
            self._warp.set_mode(mode)
            self._warp.set_tunnel_protocol(protocol)
            self._warp.enable()
            return None
        except WarpError as exc:
            logger.error("No se pudo restaurar estado WARP original: %s", exc)
            return f"Error restaurando WARP: {exc.message}"
        except Exception:  # noqa: BLE001
            logger.exception("Error inesperado restaurando WARP")
            return "Error inesperado restaurando WARP (ver logs)"

    def _compute_comparison(
        self,
        *,
        warp_off_run: DiagnosticRun,
        warp_on_run: DiagnosticRun,
        warp_off_duration_ms: float,
        warp_on_duration_ms: float,
    ) -> WarpComparisonResult:
        """Computa deltas y veredicto a partir de las dos corridas."""
        score_off = warp_off_run.recommendation.score
        score_on = warp_on_run.recommendation.score
        score_delta = score_on - score_off  # positivo = peor con WARP

        # Deltas por provider
        provider_deltas: dict[str, list[WarpComparisonDelta]] = {}

        # Agrupar probes por provider en ambas corridas
        off_by_provider = self._group_probes_by_provider(warp_off_run.probes)
        on_by_provider = self._group_probes_by_provider(warp_on_run.probes)

        common_providers = set(off_by_provider.keys()) & set(on_by_provider.keys())

        # Providers que fallaron en al menos una corrida (Regla 12b.4.5).
        failed_providers: list[str] = []

        for provider in common_providers:
            status, deltas = self._compute_provider_deltas(
                provider,
                off_by_provider[provider],
                on_by_provider[provider],
            )
            provider_deltas[provider] = deltas
            if status != "ok":
                failed_providers.append(provider)

        # Veredicto agregado (pasa failed_providers para nota en explanation)
        verdict, explanation = self._determine_verdict(
            score_delta, score_off, provider_deltas, failed_providers
        )

        return WarpComparisonResult(
            warp_off_run_id=warp_off_run.run_id,
            warp_on_run_id=warp_on_run.run_id,
            warp_off_score=score_off,
            warp_on_score=score_on,
            score_delta=score_delta,
            provider_deltas=provider_deltas,
            overall_verdict=verdict,
            verdict_explanation=explanation,
            warp_off_duration_ms=warp_off_duration_ms,
            warp_on_duration_ms=warp_on_duration_ms,
            warp_controller_available=True,
        )

    def _group_probes_by_provider(self, probes: list) -> dict[str, list]:
        """Agrupa probes por provider."""
        from collections import defaultdict

        grouped: dict[str, list] = defaultdict(list)
        for p in probes:
            grouped[p.provider].append(p)
        return dict(grouped)

    def _compute_provider_deltas(
        self,
        provider: str,
        off_probes: list,
        on_probes: list,
    ) -> tuple[str, list[WarpComparisonDelta]]:
        """Computa deltas de latencia, jitter, loss por provider.

        Regla 4.1 + 12b.4.5 (bug 2 fix): se excluyen probes non-SUCCESS
        del aggregate (NO se cuentan como 0.0). Si una corrida no tiene
        ningun probe SUCCESS para este provider, el lado (off/on) se marca
        como None y el ``status`` de cada delta indica el fallo. La UI
        muestra "-" en los valores/deltas y "FAILED" en la celda status.

        Returns:
            (status, deltas): status es "ok" | "failed_off" | "failed_on"
            | "failed_both". deltas son los WarpComparisonDelta de lat/jitter
            /loss (3 siempre, aunque los valores sean None).
        """
        from gnd.models.probe_result import ProbeOutcomeKind

        def filter_success(probes: list) -> list:
            """Solo probes SUCCESS (Regla 4.1: excluye non-SUCCESS, no 0.0)."""
            return [
                p
                for p in probes
                if p.outcome == ProbeOutcomeKind.SUCCESS and p.stats is not None
            ]

        off_ok = filter_success(off_probes)
        on_ok = filter_success(on_probes)

        # Status del provider: cual lado fallo (0 probes SUCCESS en ese lado).
        off_failed = len(off_ok) == 0
        on_failed = len(on_ok) == 0
        if off_failed and on_failed:
            status = "failed_both"
        elif off_failed:
            status = "failed_off"
        elif on_failed:
            status = "failed_on"
        else:
            status = "ok"

        def avg(probes: list, attr: str) -> float | None:
            """Avg de un atributo. None si no hay probes SUCCESS."""
            if not probes:
                return None
            vals = [getattr(p.stats, attr) for p in probes]
            return sum(vals) / len(vals)

        off_lat = avg(off_ok, "avg_ms")
        on_lat = avg(on_ok, "avg_ms")
        off_jitter = avg(off_ok, "jitter_ms")
        on_jitter = avg(on_ok, "jitter_ms")
        off_loss = avg(off_ok, "packet_loss_pct")
        on_loss = avg(on_ok, "packet_loss_pct")

        def compute_delta(off_v, on_v) -> tuple[float | None, float | None]:
            """Delta + delta_pct: None si alguno de los valores es None."""
            if off_v is None or on_v is None:
                return None, None
            delta = on_v - off_v
            delta_pct = round((delta / off_v) * 100, 1) if off_v else None
            return delta, delta_pct

        lat_delta, lat_pct = compute_delta(off_lat, on_lat)
        jitter_delta, jitter_pct = compute_delta(off_jitter, on_jitter)
        loss_delta, loss_pct = compute_delta(off_loss, on_loss)

        return status, [
            WarpComparisonDelta(
                metric_name="avg_latency_ms",
                warp_off_value=off_lat,
                warp_on_value=on_lat,
                delta=lat_delta,
                delta_pct=lat_pct,
                status=status,
            ),
            WarpComparisonDelta(
                metric_name="jitter_ms",
                warp_off_value=off_jitter,
                warp_on_value=on_jitter,
                delta=jitter_delta,
                delta_pct=jitter_pct,
                status=status,
            ),
            WarpComparisonDelta(
                metric_name="packet_loss_pct",
                warp_off_value=off_loss,
                warp_on_value=on_loss,
                delta=loss_delta,
                delta_pct=loss_pct,
                status=status,
            ),
        ]

    def _determine_verdict(
        self,
        score_delta: float,
        score_off: float,
        provider_deltas: dict[str, list[WarpComparisonDelta]],
        failed_providers: list[str] | None = None,
    ) -> tuple[str, list[str]]:
        """Determina veredicto y explicación basado en score_delta.

         score_delta = warp_on_score - warp_off_score.
         Positivo = WARP mejora (score subió). Negativo = WARP empeora.

         Regla 12b.4.5 (bug 2 fix): providers con medición fallida en al
        guna corrida NO contribuyen al análisis neutral (su delta es None,
         no cuenta como mejora/degrada). Se listan al final de la
         explicación como "medición fallida" para que el usuario sepa.
        """
        # Thresholds: mejora/degrada si score_delta > 5% del score baseline
        threshold = max(5.0, score_off * 0.05)

        if score_delta > threshold:
            pct = score_delta / score_off * 100
            parts = [f"WARP mejora el score en {score_delta:.1f} puntos ({pct:.1f}%)"]
            _append_failed_note(parts, failed_providers)
            return "improved", parts
        elif score_delta < -threshold:
            pct = abs(score_delta) / score_off * 100
            parts = [
                f"WARP empeora el score en "
                f"{abs(score_delta):.1f} puntos ({pct:.1f}%)"
            ]
            _append_failed_note(parts, failed_providers)
            return "degraded", parts
        else:
            # Neutral: buscar si hay proveedores específicos que cambien
            improved_providers = []
            degraded_providers = []
            for provider, deltas in provider_deltas.items():
                lat_delta = next(
                    (d for d in deltas if d.metric_name == "avg_latency_ms"), None
                )
                # Skip providers con delta None (medición fallida en algún lado).
                if lat_delta is None or lat_delta.delta is None:
                    continue
                # lat_delta positivo = peor con WARP; negativo = mejor
                if lat_delta.delta < -5:
                    improved_providers.append(provider)
                elif lat_delta.delta > 5:
                    degraded_providers.append(provider)

            parts = ["WARP tiene impacto neutro en el score global"]
            if improved_providers:
                parts.append(f"Mejora latencia en: {', '.join(improved_providers)}")
            if degraded_providers:
                parts.append(f"Empeora latencia en: {', '.join(degraded_providers)}")
            _append_failed_note(parts, failed_providers)
            return "neutral", parts

    def _build_unavailable_result(self) -> WarpComparisonResult:
        """Resultado cuando warp-cli no está disponible."""
        return WarpComparisonResult(
            warp_off_run_id="",
            warp_on_run_id="",
            warp_off_score=0.0,
            warp_on_score=0.0,
            score_delta=0.0,
            overall_verdict="unavailable",
            verdict_explanation=[
                (
                    "warp-cli no encontrado en PATH. "
                    "Instala Cloudflare WARP para usar esta feature."
                )
            ],
            warp_off_duration_ms=0.0,
            warp_on_duration_ms=0.0,
            warp_controller_available=False,
        )

    def _build_state_timeout_result(self, exc: WarpError) -> WarpComparisonResult:
        """Resultado cuando WARP no transiciona al estado objetivo a tiempo.

        Regla 12b.4.4 (race fix): ``warp-cli connect`` no es sync — si el
        daemon no alcanza 'connected' en ``enable_timeout_s`` (o
        'disconnected' en ``disable_timeout_s``), abortar la comparación
        con un verdict 'state_timeout' para NO medir contra una interfaz de
        red en transición (que reportaría timeouts/DNS failed erróneos).
        """
        return WarpComparisonResult(
            warp_off_run_id="",
            warp_on_run_id="",
            warp_off_score=0.0,
            warp_on_score=0.0,
            score_delta=0.0,
            overall_verdict="state_timeout",
            verdict_explanation=[
                (
                    f"Comparación abortada: WARP no transicionó al estado "
                    f"objetivo a tiempo. {exc.message} "
                    f"Reintentá en unos segundos; si persiste, verificá "
                    f"el daemon de Cloudflare WARP (`warp-cli status`)."
                )
            ],
            warp_off_duration_ms=0.0,
            warp_on_duration_ms=0.0,
            warp_controller_available=True,
        )


# Re-export WarpError para que callers puedan importar de un solo lugar
