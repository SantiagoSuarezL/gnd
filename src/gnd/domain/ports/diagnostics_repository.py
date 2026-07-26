"""Puerto DiagnosticsRepository — persistencia de corridas de diagnóstico.

ARCHITECTURE.md §2 (Protocol DiagnosticsRepository). Implementación real
en database/ (SQLite, TECHNICAL_SPEC.md §3). Implementación fake en
domain/fakes/ para tests sin disco.

El puerto de lectura (baseline histórico) se separa en métodos discretos
para respetar Interface Segregation y no forzar al repositorio a exponer
queries genéricas que el dominio no necesita.
"""

from typing import Protocol, runtime_checkable

from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.historical_baseline import HistoricalBaseline


@runtime_checkable
class DiagnosticsRepository(Protocol):
    """Persiste un DiagnosticRun completo (con probes y traceroutes anidados).

    La conexion SQLite la gestiona la implementacion (SqliteDiagnosticsRepository
    pide una conn nueva por save_run via ``DatabaseConnectionFactory`` — Regla
    de Oro 9.1). El caller NO pasa la conn por call.
    """

    def save_run(self, run: DiagnosticRun) -> None: ...

    """Computa el baseline histórico de latencia por provider.

    TECHNICAL_SPEC.md §4.1: usa solo muestras SUCCESS del provider dado en
    los últimos `period_days`. Nunca mezcla providers (§3: riot_public !=
    riot_game_server).
    """

    def get_latency_baseline(
        self,
        provider: str,
        period_days: int,
    ) -> HistoricalBaseline: ...
