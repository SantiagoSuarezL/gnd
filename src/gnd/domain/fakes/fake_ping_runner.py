"""Fake in-memory PingRunner para tests sin red real."""

from datetime import datetime

from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult


class FakePingRunner:
    """PingRunner que devuelve resultados pre-configurados.

    Uso típico en tests:
        runner = FakePingRunner()
        runner.set_result("8.8.8.8", ProbeResult(...))
        result = runner.ping("8.8.8.8", "google_dns", "google", 10, 1000)
    """

    def __init__(self) -> None:
        self._results: dict[str, ProbeResult] = {}
        self._default_result: ProbeResult | None = None
        self.calls: list[dict] = []

    def set_result(self, target_ip: str, result: ProbeResult) -> None:
        self._results[target_ip] = result

    def set_default_result(self, result: ProbeResult) -> None:
        self._default_result = result

    def ping(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        timeout_ms: int,
    ) -> ProbeResult:
        self.calls.append(
            {
                "target_ip": target_ip,
                "target_name": target_name,
                "provider": provider,
                "count": count,
                "timeout_ms": timeout_ms,
            }
        )
        if target_ip in self._results:
            return self._results[target_ip]
        if self._default_result is not None:
            base = self._default_result
            return ProbeResult(
                target_name=target_name,
                target_ip=target_ip,
                provider=provider,
                outcome=base.outcome,
                stats=base.stats,
                timestamp=base.timestamp,
            )
        # Fallback: SUCCESS con stats mínimos
        return ProbeResult(
            target_name=target_name,
            target_ip=target_ip,
            provider=provider,
            outcome=ProbeOutcomeKind.SUCCESS,
            stats=LatencyStats(
                avg_ms=10.0,
                min_ms=8.0,
                max_ms=12.0,
                jitter_ms=1.0,
                packet_loss_pct=0.0,
                samples=count,
            ),
            timestamp=datetime.now(),
        )
