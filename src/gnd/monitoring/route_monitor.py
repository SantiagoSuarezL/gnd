"""Implementacion real de `Protocol RouteMonitor` (ARCHITECTURE.md §2).

Ejecuta N traceroutes contra el MISMO target a intervalos regulares y
agrega estadisticas por hop. Tres dependencias inyectables para tests:

1. ``TracerouteRunner`` — el adapter de traceroute real (RealTracerouteRunner)
   o un fake. Inyectado por constructor (EP §3 DI).
2. ``Sleeper`` — callable que espera N segundos. Inyectable para tests
   sin reloj real (Regla de Oro 2.1 ampliada: cualquier I/O de SO,
   incluido sleep, se inyecta). Default: ``time.sleep``.
3. ``clock`` — callable que devuelve el timestamp actual. Inyectable
   para tests deterministas (EP §4: tests sin reloj real). Default:
   ``datetime.now``.

Decision Fase 8: ``interval_s`` es el intervalo NOMINAL entre muestras.
El traceroute en si toma tiempo variable (instante de fin - inicio de
cada toma). El comportamiento del monitor es:

    tomar muestra 0  -> sleep(interval_s) -> tomar muestra 1 -> ...

Esto hace que el periodo total sea aprox ``duration_s`` o, equivalentemente,
``samples_count = max(1, int(duration_s / interval_s))``. Si ``duration_s``
no es multiplo exacto de ``interval_s``, se toman tantas muestras como
cpan en ``duration_s`` garantizando al menos 1 muestra. Si una toma
individual de traceroute lleva mas que ``interval_s``, el monitor no se
espera extra: la proxima toma arranca inmediatamente despues.

Implementacion defensiva (EP §1.2 — nunca crashear):
- Si una toma individual de TracerouteRunner devuelve TracerouteResult
  vacio (hops=[placeholder responded=False]), el monitor registra esa
  toma como: hop 1 con rtt_ms=None (cuenta como loss). La sesion sigue.
- Si todas las tomas devuelven vacio, hop_stats tendra un solo HopStats
  con loss_pct=100 para hop 1 (consistente con que no se observo ruta).

Volcado del hop_number como clave de agregacion:
- En cada toma i, para cada hop en ``result.hops`` se emite un
  ``MonitoringSample(sample_index=i, hop_number=hop.hop_number,
  rtt_ms=hop.rtt_ms)``.
- Si hop_number cambia entre tomas (caso raro: traceroute encontro ruta
  mas corta), la agregacion simplemente agrega por todos los hop_number
  vistos (cada uno tendra menos samples_total); el hop_stats resultante
  sigue siendo valido para su propio rango de samples.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Protocol

from gnd.domain.ports.traceroute_runner import TracerouteRunner
from gnd.models.monitoring import (
    MonitoringSample,
    MonitoringSession,
)
from gnd.models.traceroute import TracerouteHop, TracerouteResult
from gnd.monitoring.aggregator import aggregate_hops, fill_ip_hostname_mode

logger = logging.getLogger(__name__)


# --- DI helpers: Sleeper y clock extraccion de I/O del OS ---


class Sleeper(Protocol):
    """Callable que duerme ``seconds`` segundos. Inyectable en tests."""

    def __call__(self, seconds: float) -> None: ...


class _DefaultSleeper:
    """Implementacion por defecto: time.sleep."""

    def __call__(self, seconds: float) -> None:
        if seconds > 0.0:
            time.sleep(seconds)


_default_sleeper: Sleeper = _DefaultSleeper()  # type: ignore[assignment]


class Clock(Protocol):
    """Callable que devuelve el timestamp actual. Inyectable en tests."""

    def __call__(self) -> datetime: ...


class _DefaultClock:
    def __call__(self) -> datetime:
        return datetime.now()


_default_clock: Clock = _DefaultClock()  # type: ignore[assignment]


# --- RouteMonitor ---


class RouteMonitor:
    """Implementacion real de ``Protocol RouteMonitor`` (ARCHITECTURE.md §2).

    Orquesta ``TracerouteRunner`` (DI) N veces contra el mismo target,
    agrega estadisticas por hop y devuelve una ``MonitoringSession``.

    Args de construccion (DI):
        traceroute_runner: adapter que ejecuta un traceroute individual.
        sleeper: callable que duerme N segundos (default time.sleep).
        clock: callable que devuelve ``datetime`` (default datetime.now).

    Args de ejecucion (``monitor()``), ver ``Protocol RouteMonitor``.
    """

    def __init__(
        self,
        *,
        traceroute_runner: TracerouteRunner,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._tracer = traceroute_runner
        self._sleeper: Sleeper = sleeper or _default_sleeper
        self._clock: Clock = clock or _default_clock

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
        started_at = self._clock()
        monotonic_start = time.monotonic()

        all_samples: list[MonitoringSample] = []
        per_hop_obs: dict[int, list[tuple[str | None, str | None]]] = defaultdict(list)

        if duration_s <= 0.0:
            duration_s = 0.0
        if interval_s <= 0.0:
            interval_s = 1.0

        i = 0
        take_finished_at = monotonic_start
        while True:
            if i > 0:
                # Next take scheduled at fixed interval from start,
                # but not before previous take finished.
                next_take_at = max(
                    monotonic_start + i * interval_s,
                    take_finished_at,
                )
                if next_take_at >= monotonic_start + duration_s:
                    break
                # Wait until it's time for this take.
                now = time.monotonic()
                if now < next_take_at:
                    self._sleeper(next_take_at - now)

            result = self._tracer.traceroute(
                target_ip=target_ip,
                target_provider=target_provider,
                max_hops=max_hops,
                timeout_ms=timeout_ms,
            )
            _record_take(
                take_index=i,
                result=result,
                all_samples=all_samples,
                per_hop_obs=per_hop_obs,
            )

            take_finished_at = time.monotonic()
            i += 1

        finished_at = self._clock()

        hop_stats_partial = aggregate_hops(all_samples)
        hop_stats = fill_ip_hostname_mode(hop_stats_partial, per_hop_obs)

        logger.info(
            "monitoring session done target=%s run_id=%s samples_taken=%d "
            "hops_observed=%d wall_clock=%.1fs",
            target_ip,
            run_id,
            len(all_samples),
            len(hop_stats),
            (finished_at - started_at).total_seconds(),
        )

        return MonitoringSession(
            run_id=run_id,
            target_ip=target_ip,
            target_provider=target_provider,
            started_at=started_at,
            finished_at=finished_at,
            interval_s=interval_s,
            samples=all_samples,
            hop_stats=hop_stats,
        )


def _record_take(
    take_index: int,
    result: TracerouteResult,
    all_samples: list[MonitoringSample],
    per_hop_obs: dict[int, list[tuple[str | None, str | None]]],
) -> None:
    """Registra los hops de una toma individual en las estructuras de agregacion.

    Para cada hop en ``result.hops``:
    - Agrega un MonitoringSample con rtt_ms=hop.rtt_ms (None=timeout).
    - Si el hop respondio, registra (ip, hostname) en per_hop_obs para la
      moda posterior.

    TracerouteResult vacio (placeholder hop 1 responded=False) produce
    exactamente un sample con hop_number=1, rtt_ms=None. Esto cuenta como
    una muestra observada y loss_pct=100 para hop 1.
    """
    for hop in result.hops:
        _record_single_hop(
            take_index=take_index,
            hop=hop,
            all_samples=all_samples,
            per_hop_obs=per_hop_obs,
        )


def _record_single_hop(
    take_index: int,
    hop: TracerouteHop,
    all_samples: list[MonitoringSample],
    per_hop_obs: dict[int, list[tuple[str | None, str | None]]],
) -> None:
    """Agrega una muestra individual para un hop. Implicitamente pura."""
    all_samples.append(
        MonitoringSample(
            sample_index=take_index,
            hop_number=hop.hop_number,
            rtt_ms=hop.rtt_ms,
        )
    )
    if hop.responded:
        per_hop_obs[hop.hop_number].append((hop.ip, hop.hostname))
