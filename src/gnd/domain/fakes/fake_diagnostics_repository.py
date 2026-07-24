"""Fake in-memory DiagnosticsRepository para tests sin SQLite real."""

from gnd.models.diagnostic_run import DiagnosticRun


class FakeDiagnosticsRepository:
    """DiagnosticsRepository que guarda en memoria (lista)."""

    def __init__(self) -> None:
        self._runs: list[DiagnosticRun] = []
        self.calls: list[dict] = []

    def save(self, run: DiagnosticRun) -> None:
        self.calls.append({"run_id": run.run_id, "action": "save"})
        self._runs.append(run)

    def get_all(self) -> list[DiagnosticRun]:
        self.calls.append({"action": "get_all"})
        return list(self._runs)

    def get_by_provider(
        self, provider: str, limit: int | None = None
    ) -> list[DiagnosticRun]:
        self.calls.append(
            {"action": "get_by_provider", "provider": provider, "limit": limit}
        )
        # Filter runs that have at least one probe for this provider
        filtered = [
            run for run in self._runs if any(p.provider == provider for p in run.probes)
        ]
        if limit is not None:
            return filtered[-limit:]
        return filtered

    def clear(self) -> None:
        self._runs.clear()
        self.calls.append({"action": "clear"})
