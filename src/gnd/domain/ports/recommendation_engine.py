"""Puerto RecommendationEngine — motor de recomendacion del dominio.

ARCHITECTURE.md §2. El motor recibe datos ya procesados (probes, baselines,
thresholds) y devuelve un Recommendation con veredicto + explicacion.

ENGINEERING_PRINCIPLES.md §2.D: el caso de uso (RunFullDiagnostics) depende
de este Protocol, nunca de la implementacion concreta en recommendations/.
"""

from typing import Protocol, runtime_checkable

from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.probe_result import ProbeResult
from gnd.models.recommendation import Recommendation


@runtime_checkable
class RecommendationEngine(Protocol):
    """Genera un Recommendation a partir de probes, baselines y thresholds.

    Cada implementacion debe ser intercambiable (Liskov, EP §2.L).
    La implementacion por defecto (recommendations/engine.py) usa 7 reglas
    ordenadas por prioridad segun TECHNICAL_SPEC.md §5.
    """

    def evaluate(
        self,
        probes: list[ProbeResult],
        *,
        baselines: dict[str, HistoricalBaseline],
        packet_loss_warning_pct: float,
        packet_loss_critical_pct: float,
        jitter_warning_ms: float,
        jitter_critical_ms: float,
    ) -> Recommendation: ...
