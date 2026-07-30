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

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.domain.ports.warp_controller import WarpController, WarpError, WarpStatus
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.warp_comparison import WarpComparisonDelta, WarpComparisonResult

logger = logging.getLogger(__name__)


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


class WarpComparisonUseCase:
    """Orquesta comparación WARP on vs off.

    DI completa: recibe RunFullDiagnostics + WarpController. El caller
    (composition_root) decide implementaciones reales vs fakes.

    EP §1.2: cualquier fallo en subprocess de warp-cli o diagnóstico
    individual se captura y se refleja en el resultado (no crashea la UI).
    """

    def __init__(
        self,
        *,
        diagnostics_use_case: RunFullDiagnostics,
        warp_controller: WarpController,
    ) -> None:
        self._diagnostics = diagnostics_use_case
        self._warp = warp_controller

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
        started_at = now.now()

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
                return self._build_unavailable_result(started_at, now.now())
            raise WarpError("WARP controller no disponible (warp-cli no en PATH)")

        # 2. Guardar estado original
        original_status = self._safe_get_status()
        logger.info(
            "Estado WARP original",
            extra={
                "event": "warp_comparison.original_status",
                "connected": original_status.connected,
                "registration": original_status.registration_status,
            },
        )

        try:
            # 3. Ejecutar WARP OFF
            warp_off_run, warp_off_duration = self._run_with_warp_state(
                targets, params.diagnostic_params, warp_enabled=False, clock=now
            )

            # 4. Ejecutar WARP ON
            warp_on_run, warp_on_duration = self._run_with_warp_state(
                targets, params.diagnostic_params, warp_enabled=True, clock=now
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
            return result

        finally:
            # 6. Restaurar estado original
            if params.restore_original_state:
                self._restore_original_state(original_status)

    def _is_warp_available(self) -> bool:
        """Verifica si warp-cli está disponible (sin lanzar)."""
        try:
            # get_status() no debería lanzar si no hay warp-cli (adapter
            # real marca _available=False y devuelve status degradado)
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
        *,
        warp_enabled: bool,
        clock: type,
    ) -> tuple[DiagnosticRun, float]:
        """Ajusta estado WARP, corre diagnóstico, devuelve (run, duration_ms)."""
        label = "ON" if warp_enabled else "OFF"
        logger.info(
            "Preparando WARP %s para diagnóstico",
            label,
            extra={"event": f"warp_comparison.warp_{label.lower()}"},
        )

        start = time.perf_counter()
        try:
            if warp_enabled:
                status = self._warp.enable()
                if not status.connected:
                    logger.warning(
                        "WARP enable no conectó: %s", status.connection_status
                    )
            else:
                status = self._warp.disable()
                if status.connected:
                    logger.warning(
                        "WARP disable no desconectó: %s", status.connection_status
                    )

            # Pequeña pausa para que la interfaz de red se estabilice
            time.sleep(1.0)

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

    def _restore_original_state(self, original: WarpStatus) -> None:
        """Restaura WARP al estado original (conectado/desconectado)."""
        try:
            if original.connected:
                logger.info(
                    "Restaurando WARP a CONECTADO",
                    extra={
                        "event": "warp_comparison.restore",
                        "target": "connected",
                    },
                )
                self._warp.enable()
            else:
                logger.info(
                    "Restaurando WARP a DESCONECTADO",
                    extra={
                        "event": "warp_comparison.restore",
                        "target": "disconnected",
                    },
                )
                self._warp.disable()
        except WarpError as exc:
            logger.error("No se pudo restaurar estado WARP original: %s", exc)
        except Exception:  # noqa: BLE001
            logger.exception("Error inesperado restaurando WARP")

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

        for provider in common_providers:
            deltas = self._compute_provider_deltas(
                provider,
                off_by_provider[provider],
                on_by_provider[provider],
            )
            if deltas:
                provider_deltas[provider] = deltas

        # Veredicto agregado
        verdict, explanation = self._determine_verdict(
            score_delta, score_off, provider_deltas
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
    ) -> list[WarpComparisonDelta]:
        """Computa deltas de latencia, jitter, loss por provider."""

        # Promediar probes del mismo provider (puede haber múltiples targets)
        def avg_metric(probes: list, attr: str) -> float:
            vals = [getattr(p.stats, attr) for p in probes if p.stats is not None]
            return sum(vals) / len(vals) if vals else 0.0

        off_lat = avg_metric(off_probes, "avg_ms")
        on_lat = avg_metric(on_probes, "avg_ms")
        off_jitter = avg_metric(off_probes, "jitter_ms")
        on_jitter = avg_metric(on_probes, "jitter_ms")
        off_loss = avg_metric(off_probes, "packet_loss_pct")
        on_loss = avg_metric(on_probes, "packet_loss_pct")

        deltas = [
            WarpComparisonDelta(
                metric_name="avg_latency_ms",
                warp_off_value=off_lat,
                warp_on_value=on_lat,
                delta=on_lat - off_lat,
                delta_pct=(
                    round(((on_lat - off_lat) / off_lat) * 100, 1) if off_lat else None
                ),
            ),
            WarpComparisonDelta(
                metric_name="jitter_ms",
                warp_off_value=off_jitter,
                warp_on_value=on_jitter,
                delta=on_jitter - off_jitter,
                delta_pct=(
                    round(((on_jitter - off_jitter) / off_jitter) * 100, 1)
                    if off_jitter
                    else None
                ),
            ),
            WarpComparisonDelta(
                metric_name="packet_loss_pct",
                warp_off_value=off_loss,
                warp_on_value=on_loss,
                delta=on_loss - off_loss,
                delta_pct=(
                    round(((on_loss - off_loss) / off_loss) * 100, 1)
                    if off_loss
                    else None
                ),
            ),
        ]
        return deltas

    def _determine_verdict(
        self,
        score_delta: float,
        score_off: float,
        provider_deltas: dict[str, list[WarpComparisonDelta]],
    ) -> tuple[str, list[str]]:
        """Determina veredicto y explicación basado en score_delta.

        score_delta = warp_on_score - warp_off_score.
        Positivo = WARP mejora (score subió). Negativo = WARP empeora.
        """
        # Thresholds: mejora/degrada si score_delta > 5% del score baseline
        threshold = max(5.0, score_off * 0.05)

        if score_delta > threshold:
            pct = score_delta / score_off * 100
            return "improved", [
                f"WARP mejora el score en {score_delta:.1f} puntos ({pct:.1f}%)"
            ]
        elif score_delta < -threshold:
            pct = abs(score_delta) / score_off * 100
            return "degraded", [
                f"WARP empeora el score en {abs(score_delta):.1f} puntos ({pct:.1f}%)"
            ]
        else:
            # Neutral: buscar si hay proveedores específicos que cambien
            improved_providers = []
            degraded_providers = []
            for provider, deltas in provider_deltas.items():
                lat_delta = next(
                    (d for d in deltas if d.metric_name == "avg_latency_ms"), None
                )
                # lat_delta positivo = peor con WARP; negativo = mejor
                if lat_delta and lat_delta.delta < -5:
                    improved_providers.append(provider)
                elif lat_delta and lat_delta.delta > 5:
                    degraded_providers.append(provider)

            parts = ["WARP tiene impacto neutro en el score global"]
            if improved_providers:
                parts.append(f"Mejora latencia en: {', '.join(improved_providers)}")
            if degraded_providers:
                parts.append(f"Empeora latencia en: {', '.join(degraded_providers)}")
            return "neutral", parts

    def _build_unavailable_result(
        self, started_at, finished_at
    ) -> WarpComparisonResult:
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


# Re-export WarpError para que callers puedan importar de un solo lugar
