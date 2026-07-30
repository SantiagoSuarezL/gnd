"""Modelo de resultado de comparación WARP (Fase 12b.4).

Compara dos corridas: una con WARP habilitado y otra con WARP deshabilitado.
Calcula deltas por provider y métricas agregadas para presentar en UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WarpComparisonDelta:
    """Delta de una métrica entre WARP on vs off.

    Valores positivos = peor con WARP (ej. latencia más alta, loss más alto).
    Valores negativos = mejor con WARP.
    """

    metric_name: str
    """Nombre de la métrica: 'avg_latency_ms', 'jitter_ms',
    'packet_loss_pct', 'score'."""

    warp_off_value: float
    """Valor con WARP deshabilitado (baseline)."""

    warp_on_value: float
    """Valor con WARP habilitado."""

    delta: float
    """warp_on - warp_off (positivo = peor con WARP)."""

    delta_pct: float | None = None
    """Cambio porcentual relativo a baseline (None si baseline es 0)."""


@dataclass(frozen=True)
class WarpComparisonResult:
    """Resultado completo de la comparación WARP on/off.

    Generado por `WarpComparisonUseCase.execute()`. Contiene:
    - Las dos corridas completas (warp_off_run, warp_on_run)
    - Deltas por provider (latencia, jitter, loss, score)
    - Veredicto agregado: WARP mejora / empeora / neutro
    - Explicación en lenguaje natural para UI.
    """

    warp_off_run_id: str
    """run_id de la corrida con WARP deshabilitado."""

    warp_on_run_id: str
    """run_id de la corrida con WARP habilitado."""

    warp_off_score: float
    """Network Score con WARP off."""

    warp_on_score: float
    """Network Score con WARP on."""

    score_delta: float
    """warp_on_score - warp_off_score (positivo = peor con WARP)."""

    provider_deltas: dict[str, list[WarpComparisonDelta]] = field(default_factory=dict)
    """Deltas por provider: {provider: [WarpComparisonDelta, ...]}.

    Incluye: 'local', 'google', 'cloudflare', 'quad9', 'riot_public',
    'riot_game_server'.
    Solo providers presentes en AMBAS corridas.
    """

    overall_verdict: str = "neutral"
    """'improved' | 'degraded' | 'neutral' — basado en score_delta y thresholds."""

    verdict_explanation: list[str] = field(default_factory=list)
    """Explicación legible para UI (1-3 líneas)."""

    # Metadata para logging/debug
    warp_off_duration_ms: float | None = None
    warp_on_duration_ms: float | None = None
    warp_controller_available: bool = True
    """False si RealWarpController no estaba disponible (warp-cli no en PATH)."""

    @property
    def score_change_pct(self) -> float | None:
        """Cambio porcentual del score (None si warp_off_score == 0)."""
        if self.warp_off_score == 0:
            return None
        return round((self.score_delta / self.warp_off_score) * 100, 1)

    def get_provider_delta(
        self, provider: str, metric: str
    ) -> WarpComparisonDelta | None:
        """Busca un delta específico por provider y métrica."""
        for d in self.provider_deltas.get(provider, []):
            if d.metric_name == metric:
                return d
        return None
