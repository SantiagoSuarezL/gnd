"""Fake in-memory RouteMonitor + MonitoringRepository para tests.

EP §4 (testing sin red, sin disco, sin reloj real). Ambos fakes son
intercambiables con las clases reales por Liskov (Protocolos
`runtime_checkable`).

- ``FakeRouteMonitor`` graba las llamadas y devuelve una sesion armada
  manualmente (o la default que produce estadisticas vacias: hop 1 solo
  timeout). Permite tests con `samples` y `hop_stats` especificos sin
  tocar red.
- ``FakeMonitoringRepository`` guarda sesiones en memoria (lista) y
  responde a `get_sessions_by_run()`. No toca disk.
"""

from __future__ import annotations

from gnd.models.monitoring import MonitoringSession


class FakeRouteMonitor:
    """RouteMonitor que devuelve sesiones pre-configuradas.

    Uso tipico en tests:
        monitor = FakeRouteMonitor()
        monitor.set_session(my_session)
        result = monitor.monitor(...)
        assert result is my_session
        assert len(monitor.calls) == 1
    """

    def __init__(self) -> None:
        self._session_for_run_id: dict[str, MonitoringSession] = {}
        self._default_session: MonitoringSession | None = None
        self.calls: list[dict] = []

    def set_session_for_run_id(
        self,
        run_id: str,
        session: MonitoringSession,
    ) -> None:
        self._session_for_run_id[run_id] = session

    def set_default_session(self, session: MonitoringSession) -> None:
        self._default_session = session

    def monitor(
        self,
        *,
        target_ip: str,
        target_provider: str,
        run_id: str,
        interval_s: float,
        duration_s: float,
        max_hops: int,
        timeout_ms: int,
    ) -> MonitoringSession:
        self.calls.append(
            {
                "target_ip": target_ip,
                "target_provider": target_provider,
                "run_id": run_id,
                "interval_s": interval_s,
                "duration_s": duration_s,
                "max_hops": max_hops,
                "timeout_ms": timeout_ms,
            }
        )
        if run_id in self._session_for_run_id:
            return self._session_for_run_id[run_id]
        if self._default_session is not None:
            return self._default_session
        # Fallback: sesion vacia minimal (0 muestras, 0 stats).
        # El modelo exige samples y hop_stats ambos vacios o ambos no
        # vacios; este es el caso vacio (sesion abortada antes de sample 0).
        return _empty_session(
            run_id=run_id,
            target_ip=target_ip,
            target_provider=target_provider,
        )


class FakeMonitoringRepository:
    """MonitoringRepository en memoria. Guarda y devuelve por run_id."""

    def __init__(self) -> None:
        self._sessions: list[MonitoringSession] = []
        self.calls: list[dict] = []

    def save_session(self, session: MonitoringSession) -> None:
        self.calls.append({"action": "save_session", "run_id": session.run_id})
        self._sessions.append(session)

    def get_sessions_by_run(self, run_id: str) -> list[MonitoringSession]:
        self.calls.append(
            {"action": "get_sessions_by_run", "run_id": run_id},
        )
        return [s for s in self._sessions if s.run_id == run_id]


def _empty_session(
    *,
    run_id: str,
    target_ip: str,
    target_provider: str,
) -> MonitoringSession:
    """Devuelve una MonitoringSession con 0 muestras y 0 stats.

    Helper para que FakeRouteMonitor.monitor() nunca crashee sin
    set_default_session. La sesion esta vacia pero tiene timestamps
    coherentes (started_at == finished_at == datetime(2000,1,1)).
    """
    from datetime import datetime

    t = datetime(2000, 1, 1)
    return MonitoringSession(
        run_id=run_id,
        target_ip=target_ip,
        target_provider=target_provider,
        started_at=t,
        finished_at=t,
        interval_s=1.0,
        samples=[],
        hop_stats=[],
    )
