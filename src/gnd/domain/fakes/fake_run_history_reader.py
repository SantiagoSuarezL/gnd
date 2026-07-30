"""Fake in-memory RunHistoryReader para tests sin disco (Fase 12b.3).

Mismo patrón que los demás fakes (FakeDesktopNotifier, FakePingRunner, ...):
- No toca SQLite, no arranca factory.
- Recibe una lista de ``DiagnosticRun`` sembrada en el constructor
  (o agregable en runtime via ``add_run`` para tests incrementales).
- Implementa el Protocol ``RunHistoryReader`` implícitamente (duck
  typing — tener ``get_runs_in_period`` basta).

Filtrado por rango: replica la semántica half-open [start, end) que
realiza el reader SQLite, para que los tests ejerciten el mismo
contrato. Orden ascendente por ``started_at``.
"""

from datetime import datetime

from gnd.models.diagnostic_run import DiagnosticRun

__all__ = ["FakeRunHistoryReader"]


class FakeRunHistoryReader:
    """RunHistoryReader sobre una lista in-memory configurable.

    Uso típico en tests:
        reader = FakeRunHistoryReader(runs=[run_a, run_b])
        out = reader.get_runs_in_period(start, end)
        assert out == [run_a]
    """

    def __init__(self, *, runs: list[DiagnosticRun] | None = None) -> None:
        self._runs: list[DiagnosticRun] = list(runs) if runs else []

    def add_run(self, run: DiagnosticRun) -> None:
        """Siembra un run más en el Fake (para tests incrementales)."""
        self._runs.append(run)

    @property
    def runs(self) -> list[DiagnosticRun]:
        """Snapshot ordenado por started_at (no mutar el interno)."""
        return sorted(self._runs, key=lambda r: r.started_at)

    def get_runs_in_period(self, start: datetime, end: datetime) -> list[DiagnosticRun]:
        if end < start:
            raise ValueError(
                f"end no puede ser anterior a start (start={start} end={end})"
            )
        selected = [r for r in self._runs if start <= r.started_at < end]
        return sorted(selected, key=lambda r: r.started_at)
