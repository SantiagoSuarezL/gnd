"""Puerto RunHistoryReader — lectura de corridas históricas (Fase 12b.3).

ARCHITECTURE.md §2 (Protocol). Implementación real en
``database/sqlite_run_history_reader.py``; fake en
``domain/fakes/fake_run_history_reader.py`` para tests sin disco.

Separado de ``DiagnosticsRepository`` (que solo escribe — ver su
docstring): la lectura de runs completos para composición de reportes
es un contrato distinto y merece su puerto (Interface Segregation).
No forzamos al repositorio de escritura a exponer queries que el
dominio no necesita en el flujo de diagnóstico interactivo.

El reader devuelve una ``list[DiagnosticRun]`` ordenada por
``started_at`` ascendente dentro del rango [start, end) — semántica
half-open consistente con Python ``range()`` y con el modo en que los
períodos se encadenan (end de un período = start del siguiente, sin
doble conteo del run boundary).
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from gnd.models.diagnostic_run import DiagnosticRun

__all__ = ["RunHistoryReader"]


@runtime_checkable
class RunHistoryReader(Protocol):
    """Lee corridas persistidas en un rango de fechas.

    El rango es half-open: [start, end). Un run con ``started_at ==
    end`` queda fuera del rango (pertenece al período siguiente).
    """

    def get_runs_in_period(
        self,
        start: datetime,
        end: datetime,
    ) -> list[DiagnosticRun]: ...
