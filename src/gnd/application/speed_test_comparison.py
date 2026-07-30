"""Caso de uso SpeedTestComparison — ejecuta speed test y lo compara
con el último diagnóstico (Fase 12b.5).

Application layer de ARCHITECTURE.md §2. Consume Protocol del dominio
inyectados por constructor (EP §3 DI). Wiring en composition_root.

Diseño (Regla de Oro 12b.4.1 aplicada a speed test):
- SpeedTestComparisonUseCase COMPONE RunFullDiagnostics + SpeedTestController.
- Flujo: 1) Ejecuta diagnóstico completo (RunFullDiagnostics.execute),
  2) Ejecuta speed test (SpeedTestController.run), 3) Computa deltas entre
  las métricas de red del diagnóstico y el speed test, 4) Genera veredicto.
- El speed test se ejecuta DESPUÉS del diagnóstico para no interferir con
  los probes (un speed test consume ancho de banda, afectando ping/latency).
- El caso de uso es dueño del lifecycle: run diagnostic -> run speed test ->
  compute deltas -> return result.

EP §1.2: cualquier fallo en subprocess de speedtest o diagnóstico individual
se captura y se refleja en el resultado (no crashea la UI).
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
from gnd.domain.ports.speed_test_controller import SpeedTestController, SpeedTestError
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.speed_test import (
    SpeedTestComparisonResult,
    SpeedTestDelta,
    SpeedTestResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeedTestComparisonParams:
    """Parámetros de ejecución del speed test comparison.

    Extiende DiagnosticParams con flags específicos de speed test.
    """

    diagnostic_params: DiagnosticParams
    """Parámetros base del diagnóstico (count, timeouts, thresholds, etc.)."""

    skip_if_speedtest_unavailable: bool = True
    """Si True y SpeedTestController no está disponible, devuelve resultado
    con speed_test_controller_available=False en vez de lanzar excepción."""


class SpeedTestComparisonUseCase:
    """Orquesta diagnóstico + speed test y computa deltas.

    DI completa: recibe RunFullDiagnostics + SpeedTestController. El caller
    (composition_root) decide implementaciones reales vs fakes.

    EP §1.2: cualquier fallo en subprocess de speedtest o diagnóstico
    individual se captura y se refleja en el resultado (no crashea la UI).
    """

    def __init__(
        self,
        *,
        diagnostics_use_case: RunFullDiagnostics,
        speed_test_controller: SpeedTestController,
    ) -> None:
        self._diagnostics = diagnostics_use_case
        self._speed_test = speed_test_controller

    def execute(
        self,
        targets: DiagnosticTargets,
        params: SpeedTestComparisonParams,
        *,
        clock=None,
    ) -> SpeedTestComparisonResult:
        """Ejecuta diagnóstico + speed test y computa deltas.

        Args:
            targets: Targets de diagnóstico (IPs, hostnames, game process names).
            params: Parámetros de la comparación (incluye diagnostic_params).
            clock: Callable () -> datetime para tests deterministas.

        Returns:
            SpeedTestComparisonResult con el diagnóstico, el speed test,
            deltas y veredicto.

        EP §1.2: nunca lanza excepción a la UI. Errores de speedtest o
        diagnóstico se loguean y se reflejan en el resultado.
        """
        from datetime import datetime

        now = clock or datetime
        started_at = now.now()

        # 1. Verificar disponibilidad del speed test controller
        if not self._is_speedtest_available():
            if params.skip_if_speedtest_unavailable:
                logger.warning(
                    "SpeedTest controller no disponible — comparación saltada",
                    extra={
                        "event": "speed_test_comparison.skip",
                        "reason": "controller_unavailable",
                    },
                )
                return self._build_unavailable_result(started_at, now.now())
            raise SpeedTestError(
                "SpeedTest controller no disponible (speedtest no en PATH)"
            )

        # 2. Ejecutar diagnóstico completo
        logger.info(
            "Iniciando diagnóstico para speed test comparison",
            extra={"event": "speed_test_comparison.diag_start"},
        )
        diag_start = time.perf_counter()
        try:
            run = self._diagnostics.execute(
                targets, params.diagnostic_params, clock=clock
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Diagnóstico falló durante speed test comparison")
            raise SpeedTestError(
                f"Diagnóstico falló: {exc}", original_error=exc
            ) from exc
        diag_duration_ms = (time.perf_counter() - diag_start) * 1000

        logger.info(
            "Diagnóstico completado",
            extra={
                "event": "speed_test_comparison.diag_finish",
                "run_id": run.run_id,
                "duration_ms": round(diag_duration_ms, 2),
                "score": run.recommendation.score,
                "verdict": run.recommendation.verdict,
            },
        )

        # 3. Ejecutar speed test (después del diagnóstico para no interferir)
        logger.info(
            "Iniciando speed test",
            extra={"event": "speed_test_comparison.speedtest_start"},
        )
        speedtest_start = time.perf_counter()
        try:
            speed_test_result = self._speed_test.run()
        except SpeedTestError:
            logger.exception("Speed test falló")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Speed test falló (error inesperado)")
            raise SpeedTestError(
                f"Speed test falló: {exc}", original_error=exc
            ) from exc
        speedtest_duration_ms = (time.perf_counter() - speedtest_start) * 1000

        logger.info(
            "Speed test completado",
            extra={
                "event": "speed_test_comparison.speedtest_finish",
                "latency_ms": speed_test_result.latency_ms,
                "download_mbps": speed_test_result.download_mbps,
                "upload_mbps": speed_test_result.upload_mbps,
                "duration_ms": round(speedtest_duration_ms, 2),
            },
        )

        # 4. Computar deltas entre diagnóstico y speed test
        result = self._compute_comparison(
            run=run,
            speed_test_result=speed_test_result,
            diag_duration_ms=diag_duration_ms,
            speedtest_duration_ms=speedtest_duration_ms,
        )

        logger.info(
            "Speed test comparison completada",
            extra={
                "event": "speed_test_comparison.finish",
                "verdict": result.overall_verdict,
                "score": run.recommendation.score,
            },
        )
        return result

    def _is_speedtest_available(self) -> bool:
        """Verifica si speedtest está disponible (sin lanzar)."""
        return getattr(self._speed_test, "available", True)

    def _compute_comparison(
        self,
        *,
        run: DiagnosticRun,
        speed_test_result: SpeedTestResult,
        diag_duration_ms: float,
        speedtest_duration_ms: float,
    ) -> SpeedTestComparisonResult:
        """Computa deltas entre el diagnóstico y el speed test.

        Los deltas comparan:
        - Latencia del gateway (del diagnóstico) vs latencia del speed test
        - Jitter del gateway vs jitter del speed test
        - Packet loss del gateway vs packet loss del speed test
        - Download/upload del speed test (no hay equivalente en diagnóstico,
          se reporta como información)
        """
        # Extraer métricas del diagnóstico (gateway probe)
        gateway_probe = None
        for probe in run.probes:
            if probe.provider == "local":
                gateway_probe = probe
                break

        deltas: list[SpeedTestDelta] = []

        if gateway_probe is not None and gateway_probe.stats is not None:
            # Latencia: speed test vs gateway
            lat_delta = self._make_delta(
                "latency_ms",
                gateway_probe.stats.avg_ms,
                speed_test_result.latency_ms,
            )
            deltas.append(lat_delta)

            # Jitter
            jitter_delta = self._make_delta(
                "jitter_ms",
                gateway_probe.stats.jitter_ms,
                speed_test_result.jitter_ms,
            )
            deltas.append(jitter_delta)

            # Packet loss
            loss_delta = self._make_delta(
                "packet_loss_pct",
                gateway_probe.stats.packet_loss_pct,
                speed_test_result.packet_loss_pct,
            )
            deltas.append(loss_delta)

        # Download/upload (solo speed test, no equivalente en diagnóstico)
        download_delta = SpeedTestDelta(
            metric_name="download_mbps",
            baseline_value=0.0,
            comparison_value=speed_test_result.download_mbps,
            delta=speed_test_result.download_mbps,
            delta_pct=None,
        )
        deltas.append(download_delta)

        upload_delta = SpeedTestDelta(
            metric_name="upload_mbps",
            baseline_value=0.0,
            comparison_value=speed_test_result.upload_mbps,
            delta=speed_test_result.upload_mbps,
            delta_pct=None,
        )
        deltas.append(upload_delta)

        # Veredicto
        verdict, explanation = self._determine_verdict(
            run=run, speed_test_result=speed_test_result, deltas=deltas
        )

        return SpeedTestComparisonResult(
            baseline=speed_test_result,
            comparison=speed_test_result,
            deltas=deltas,
            overall_verdict=verdict,
            verdict_explanation=explanation,
            baseline_duration_ms=diag_duration_ms,
            comparison_duration_ms=speedtest_duration_ms,
            speed_test_controller_available=True,
        )

    def _make_delta(
        self, metric_name: str, baseline_value: float, comparison_value: float
    ) -> SpeedTestDelta:
        """Crea un SpeedTestDelta con cálculo de porcentaje."""
        delta = comparison_value - baseline_value
        delta_pct = None
        if baseline_value != 0:
            delta_pct = round((delta / baseline_value) * 100, 1)
        return SpeedTestDelta(
            metric_name=metric_name,
            baseline_value=baseline_value,
            comparison_value=comparison_value,
            delta=delta,
            delta_pct=delta_pct,
        )

    def _determine_verdict(
        self,
        *,
        run: DiagnosticRun,
        speed_test_result: SpeedTestResult,
        deltas: list[SpeedTestDelta],
    ) -> tuple[str, list[str]]:
        """Determina veredicto y explicación basado en score del diagnóstico
        y métricas del speed test.

        El veredicto principal viene del diagnóstico (safe_to_play, etc.).
        El speed test aporta contexto de ancho de banda.
        """
        score = run.recommendation.score
        verdict = run.recommendation.verdict

        parts: list[str] = []

        # Contexto del diagnóstico
        parts.append(f"Diagnóstico: score={score}/100, verdict={verdict}")

        # Contexto del speed test
        parts.append(
            f"Speed test: {speed_test_result.download_mbps:.1f}↓ "
            f"{speed_test_result.upload_mbps:.1f}↑ "
            f"latencia={speed_test_result.latency_ms:.1f}ms"
        )

        # Análisis de deltas
        lat_delta = next((d for d in deltas if d.metric_name == "latency_ms"), None)
        if lat_delta and abs(lat_delta.delta) > 5:
            if lat_delta.delta > 0:
                parts.append(
                    f"Speed test muestra latencia +{lat_delta.delta:.1f}ms "
                    "vs gateway (posible congestión)"
                )
            else:
                parts.append(
                    f"Speed test muestra latencia {abs(lat_delta.delta):.1f}ms "
                    "menor vs gateway (ruta optimizada)"
                )

        # Veredicto agregado
        if score >= 80:
            overall = "improved"
        elif score >= 60:
            overall = "neutral"
        else:
            overall = "degraded"

        return overall, parts

    def _build_unavailable_result(
        self, started_at, finished_at
    ) -> SpeedTestComparisonResult:
        """Resultado cuando speedtest no está disponible."""
        from gnd.models.speed_test import SpeedTestResult

        unavailable_result = SpeedTestResult(
            latency_ms=0.0,
            jitter_ms=0.0,
            download_mbps=0.0,
            upload_mbps=0.0,
            packet_loss_pct=0.0,
            server_name="Unavailable",
            server_country="Unknown",
            isp="Unknown",
        )
        return SpeedTestComparisonResult(
            baseline=unavailable_result,
            comparison=unavailable_result,
            deltas=[],
            overall_verdict="unavailable",
            verdict_explanation=[
                (
                    "speedtest (ookla-speedtest) no encontrado en PATH. "
                    "Instala Ookla Speedtest CLI para usar esta feature."
                )
            ],
            baseline_duration_ms=0.0,
            comparison_duration_ms=0.0,
            speed_test_controller_available=False,
        )
