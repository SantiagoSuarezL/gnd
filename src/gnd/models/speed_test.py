"""Modelo de resultado de speed test (Fase 12b.5).

Captura las métricas de ancho de banda obtenidas de `ookla-speedtest`
(latencia, jitter, descarga, upload, packet loss) para comparar con/sin
WARP o para usar como contexto en el motor de recomendación.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpeedTestResult:
    """Resultado de un speed test individual.

    Generado por ``SpeedTestController.run()``. Contiene:
    - Latencia (ping) al servidor de speed test
    - Jitter
    - Ancho de banda de descarga (Mbps)
    - Ancho de banda de upload (Mbps)
    - Packet loss (%)
    - Nombre del servidor y proveedor
    """

    latency_ms: float
    """Latencia promedio al servidor de speed test (ms)."""

    jitter_ms: float
    """Jitter (ms)."""

    download_mbps: float
    """Ancho de banda de descarga (Mbps)."""

    upload_mbps: float
    """Ancho de banda de upload (Mbps)."""

    packet_loss_pct: float
    """Packet loss (%) reportado por el speed test."""

    server_name: str
    """Nombre del servidor de speed test usado."""

    server_country: str
    """País del servidor de speed test."""

    isp: str
    """ISP detectado por el speed test."""

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms debe ser >= 0, fue {self.latency_ms}")
        if self.jitter_ms < 0:
            raise ValueError(f"jitter_ms debe ser >= 0, fue {self.jitter_ms}")
        if self.download_mbps < 0:
            raise ValueError(f"download_mbps debe ser >= 0, fue {self.download_mbps}")
        if self.upload_mbps < 0:
            raise ValueError(f"upload_mbps debe ser >= 0, fue {self.upload_mbps}")
        if not (0.0 <= self.packet_loss_pct <= 100.0):
            raise ValueError(
                f"packet_loss_pct debe estar en [0, 100], fue {self.packet_loss_pct}"
            )
        if not self.server_name:
            raise ValueError("server_name no puede ser vacío")


@dataclass(frozen=True)
class SpeedTestDelta:
    """Delta de una métrica entre speed test baseline vs comparación.

    Valores positivos = empeora con el segundo test.
    Valores negativos = mejora.
    """

    metric_name: str
    """Nombre de la métrica: 'latency_ms', 'jitter_ms',
    'download_mbps', 'upload_mbps', 'packet_loss_pct'."""

    baseline_value: float
    """Valor del speed test baseline (primer test)."""

    comparison_value: float
    """Valor del speed test de comparación (segundo test)."""

    delta: float
    """comparison_value - baseline_value."""

    delta_pct: float | None = None
    """Cambio porcentual relativo a baseline (None si baseline es 0)."""


@dataclass(frozen=True)
class SpeedTestComparisonResult:
    """Resultado de una comparación de speed test (baseline vs comparación).

    Generado por ``SpeedTestComparisonUseCase.execute()``. Contiene:
    - El speed test baseline (antes)
    - El speed test de comparación (después)
    - Deltas por métrica
    - Veredicto agregado
    - Explicación en lenguaje natural
    """

    baseline: SpeedTestResult
    """Speed test realizado antes de la comparación."""

    comparison: SpeedTestResult
    """Speed test realizado después de la comparación."""

    deltas: list[SpeedTestDelta] = field(default_factory=list)
    """Deltas por métrica (latency, jitter, download, upload, packet_loss)."""

    overall_verdict: str = "neutral"
    """'improved' | 'degraded' | 'neutral' — basado en deltas agregados."""

    verdict_explanation: list[str] = field(default_factory=list)
    """Explicación legible para UI (1-3 líneas)."""

    baseline_duration_ms: float | None = None
    """Duración del speed test baseline en ms."""

    comparison_duration_ms: float | None = None
    """Duración del speed test de comparación en ms."""

    speed_test_controller_available: bool = True
    """False si RealSpeedTestController no estaba disponible."""

    diagnostic_score: int | None = None
    """Score 0-100 del diagnóstico de red corrido antes del speed test.
    None si el resultado vino del path unavailable (no se corrió diagnóstico).
    """

    diagnostic_verdict: str | None = None
    """Veredicto textual del diagnóstico de red (ej. 'safe_to_play', 'playable').
    None si el resultado vino del path unavailable.
    """

    def get_delta(self, metric: str) -> SpeedTestDelta | None:
        """Busca un delta específico por nombre de métrica."""
        for d in self.deltas:
            if d.metric_name == metric:
                return d
        return None
