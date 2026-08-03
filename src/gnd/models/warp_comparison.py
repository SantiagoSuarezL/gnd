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

    Regla 12b.4.5 (bug 2 fix): si un provider falla en una o ambas
    corridas (probes non-SUCCESS), los valores afectados se setean en
    None (NO 0.0) y `status` indica en qué lado falló. La UI muestra
    "-" en deltas/valores y una nota "FAILED" en la celda status.
    Provider con fallo total en alguna corrida NO contribuye al
    veredicto agregado (Regla 4.1 estricta: excluye, no cuenta como 0).
    """

    metric_name: str
    """Nombre de la métrica: 'avg_latency_ms', 'jitter_ms',
    'packet_loss_pct', 'score'."""

    warp_off_value: float | None
    """Valor con WARP deshabilitado (baseline). None si el provider falló
    en esta corrida (todos los probes non-SUCCESS)."""

    warp_on_value: float | None
    """Valor con WARP habilitado. None si el provider falló en esta corrida."""

    delta: float | None
    """warp_on - warp_off (positivo = peor con WARP). None si alguno de los
    dos valores es None (no se puede computar delta sin ambos puntos)."""

    delta_pct: float | None = None
    """Cambio porcentual relativo a baseline (None si baseline es 0 o no
    medido)."""

    status: str = "ok"
    """``"ok"`` (ambas mediciones presentes) | ``"failed_off"`` (WARP off
    falló) | ``"failed_on"`` (WARP on falló) | ``"failed_both"`` (ambas
    fallaron). Regla 12b.4.5: distingue fallo total de mejora real."""


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

    restore_warning: str | None = None
    """Si el restore no pudo replicar el modo/protocolo original del usuario
    (Regla 12b.4.2: el adapter no detectó mode/protocol via `settings list`),
    contiene un mensaje legible para que el usuario sepa que WARP quedó
    apagado y debe prenderlo a mano en su modo preferido. None = restore OK
    o no aplicó."""

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
