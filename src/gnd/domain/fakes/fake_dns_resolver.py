"""Fake in-memory DnsResolver para tests sin red (Fase 12a.2)."""

from gnd.models.dns_measurement import DnsOutcome, DnsResolution


class FakeDnsResolver:
    """DnsResolver que devuelve resultados pre-configurados.

    Uso típico en tests:
        resolver = FakeDnsResolver()
        resolver.set_result("8.8.8.8", DnsResolution(...))
        result = resolver.resolve("8.8.8.8")

    Registra las llamadas en `self.calls` para asserts de integración
    sobre orquestadores (RunFullDiagnostics).
    """

    def __init__(self) -> None:
        self._results: dict[str, DnsResolution] = {}
        self._default_result: DnsResolution | None = None
        self.calls: list[dict] = []

    def set_result(self, hostname: str, result: DnsResolution) -> None:
        self._results[hostname] = result

    def set_default_result(self, result: DnsResolution) -> None:
        self._default_result = result

    def resolve(
        self,
        hostname: str,
        *,
        family: str = "ipv4",
        timeout_ms: int = 1000,
    ) -> DnsResolution:
        self.calls.append(
            {"hostname": hostname, "family": family, "timeout_ms": timeout_ms}
        )
        if hostname in self._results:
            return self._results[hostname]
        if self._default_result is not None:
            # Reusar el value del default pero ajustar hostname/family si
            # difieren (para que el fake actúe como plantilla).
            base = self._default_result
            return DnsResolution(
                hostname=hostname,
                resolved_ip=base.resolved_ip,
                outcome=base.outcome,
                elapsed_ms=base.elapsed_ms,
                family=family if base.family == family else base.family,
                error=base.error,
            )
        # Fallback: SUCCESS rápido simulado
        return DnsResolution(
            hostname=hostname,
            resolved_ip="127.0.0.1",
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=1.0,
            family=family,
            error=None,
        )
