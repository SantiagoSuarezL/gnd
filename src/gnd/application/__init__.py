"""Casos de uso (Application layer) — orquestación de los Protocol del dominio.

ARCHITECTURE.md §2: Application layer consume los Protocol del dominio
inyectados por constructor (EP §3 DI). El wiring de qué implementacion
concreta usar (real vs fake) vive en `composition_root` — ni este caso
de uso ni la UI deciden.

Fase 12b.4: WarpComparisonUseCase orquesta dos corridas (WARP on + WARP
off) y devuelve un WarpComparisonResult con deltas por provider.
"""

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.application.warp_comparison import (
    WarpComparisonParams,
    WarpComparisonUseCase,
)

__all__ = [
    "DiagnosticParams",
    "DiagnosticTargets",
    "RunFullDiagnostics",
    "WarpComparisonParams",
    "WarpComparisonUseCase",
]
