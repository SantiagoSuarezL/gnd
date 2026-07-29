"""Fake in-memory TracerouteRunner para tests sin red real."""

from gnd.models.traceroute import TracerouteHop, TracerouteResult


class FakeTracerouteRunner:
    """TracerouteRunner que devuelve resultados pre-configurados."""

    def __init__(self) -> None:
        self._results: dict[str, TracerouteResult] = {}
        self._default_result: TracerouteResult | None = None
        self.calls: list[dict] = []

    def set_result(self, target_ip: str, result: TracerouteResult) -> None:
        self._results[target_ip] = result

    def set_default_result(self, result: TracerouteResult) -> None:
        self._default_result = result

    def traceroute(
        self,
        target_ip: str,
        target_provider: str,
        max_hops: int,
        timeout_ms: int,
        *,
        family: str = "ipv4",
    ) -> TracerouteResult:
        self.calls.append(
            {
                "target_ip": target_ip,
                "target_provider": target_provider,
                "max_hops": max_hops,
                "timeout_ms": timeout_ms,
                "family": family,
            }
        )
        if target_ip in self._results:
            return self._results[target_ip]
        if self._default_result is not None:
            return self._default_result
        # Fallback: un solo hop (el destino) con respuesta
        return TracerouteResult(
            target_provider=target_provider,
            hops=[
                TracerouteHop(
                    hop_number=1,
                    ip=target_ip,
                    hostname=None,
                    rtt_ms=10.0,
                    responded=True,
                )
            ],
            culprit_hop_index=None,
            family=family,
        )
