"""Agregacion pura de muestras de monitoreo en estadisticas por hop.

Logica testeable sin red, sin reloj, sin subprocess (EP §4). La extraccion
en modulo separado sigue el patron de `network.real_traceroute_runner.
detect_culprit_hop` (logica pura expuesta para tests directos).

Agregacion por ``hop_number`` (posicion TTL en la ruta), NO por IP:
- En una misma ruta, el hop en la posicion TTL=N puede mostrar IPs
  distintos entre muestras por ECMP / load balancing en routers
  intermedios. La posicion TTL es estable para el mismo target.
- WinMTR usa el mismo criterio (agrupa por hop_number).

Para el campo ``HopStats.ip`` (informacion, no clave de agregacion) se
usa la MODA de los IPs observados para los hops que respondieron. Si
nunca respondio, ``ip=None``. Lo mismo para ``hostname``.

Jitter (nomenclatura del proyecto, alineada con TECHNICAL_SPEC.md §1):
desviacion estandar de los RTTs que respondieron. Si hay una sola
muestra, jitter=0.0 (no hay variabilidad medible). Si hay 0 muestras,
como todo hop_stats tiene al menos 1 muestra total (invariante del
modelo), success_count==0 -> best/worst/avg=None, jitter=0.0.

`format_anomalies_text`: generacion determinista de resumen textual de
anomalias por hop. REGLA FIJA (2026-07-25): cualquier hop con perdida
parcial (respondio + descarto) aparece en el output sin importar `n`.
Ver docstring de la funcion para el porque.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable

from gnd.models.monitoring import HopStats, MonitoringSample


def aggregate_hops(samples: Iterable[MonitoringSample]) -> list[HopStats]:
    """Agrega muestras en estadisticas por hop_number.

    Args:
        samples: iterable de muestras (mismo hop_number == misma posicion
            TTL en la ruta). El iterable puede contener muestras en
            cualquier orden; el resultado se ordena por hop_number.

    Returns:
        Lista de ``HopStats`` ordenada por hop_number ascendente.
        Una entrada por hop_number observado. Si el iterable es vacio,
        devuelve [] (el caller decide si eso es un error o sesion abortada).
    """
    # Agrupar por hop_number. Para cada hop_number, registramos:
    # - las rtts que respondieron (no None)
    # - cuantas muestras totales observamos (denominador del loss_pct)
    # - IPs y hostnames observados (para MODA en HopStats.ip/hostname)
    #   que llegan del caller via otra estructura; este agregador puro
    #   no tiene acceso a IP/hostname (MonitoringSample no los tiene).
    #   Solucion: la estructuracion de HopStats.ip/hostname la arma el
    #   orquestador (RouteMonitor) que tiene los TracerouteHop.models
    #   con IP. Esta funcion `aggregate_hops` se limita a los campos
    #   que si estan en MonitoringSample: hop_number y rtt_ms.
    grouped: dict[int, list[float | None]] = {}
    for s in samples:
        grouped.setdefault(s.hop_number, []).append(s.rtt_ms)

    result: list[HopStats] = []
    for hop_number in sorted(grouped.keys()):
        rtts_with_none = grouped[hop_number]
        samples_total = len(rtts_with_none)
        successes = [r for r in rtts_with_none if r is not None]
        success_count = len(successes)

        if success_count == 0:
            result.append(
                HopStats(
                    hop_number=hop_number,
                    ip=None,  # el orquestador postprocesa para setear la moda
                    hostname=None,
                    best_ms=None,
                    worst_ms=None,
                    avg_ms=None,
                    jitter_ms=0.0,
                    loss_pct=100.0,
                    samples=samples_total,
                    success_count=0,
                )
            )
            continue

        best = min(successes)
        worst = max(successes)
        avg = statistics.fmean(successes)
        # Jitter = desviacion estandar. Con 1 sample no se puede calcular
        # (statistics.stdev() lanza), y por definicion jitter=0 sin
        # variabilidad observable.
        jitter = statistics.stdev(successes) if success_count > 1 else 0.0
        loss_pct = 100.0 * (samples_total - success_count) / samples_total

        result.append(
            HopStats(
                hop_number=hop_number,
                ip=None,
                hostname=None,
                best_ms=best,
                worst_ms=worst,
                avg_ms=avg,
                jitter_ms=jitter,
                loss_pct=loss_pct,
                samples=samples_total,
                success_count=success_count,
            )
        )

    return result


def format_anomalies_text(hop_stats: list[HopStats]) -> str:
    """Genera un resumen textual determinista de anomalias por hop.

    REGLA FIJA (decision 2026-07-25 con Santiago): cualquier hop
    intermedio con ``loss_pct > 0`` Y que respondio al menos una vez
    (``success_count > 0``) aparece EXPLICITAMENTE en el output,
    sin importar ``n``. Nunca omitir perdida real de los resumenes.

    Razon: el LLM que genera los resumenes de chat tiende a omitir
    hops con pocos samples (n=2, n=12) por considerarlo "ruido".
    Eso es una decision de presentacion que debe vivir en codigo
    determinista, no librada al criterio del modelo. Esta funcion
    garantiza que la perdida sea VISIBLE en el textual output que
    luego el LLM (o un humano) consume.

    Adicionalmente reporta:
    - Hops con jitter alto (> jitter_warning_ms, default 20ms) que
      respondieron, sin importar n.
    - Hops con perdida total (loss_pct=100), etiquetados como
      "no respondio" (no son anomalia probada, son ausencia de dato).

    Args:
        hop_stats: lista de HopStats de una MonitoringSession.

    Returns:
        Texto multi-linea. Si no hay anomalias, devuelve una linea
        indicando "sin anomalias observadas". Nunca devuelve cadena
        vacia (caller puede imprimir directo).
    """
    lines: list[str] = []

    # Anomalias confirmadas: hop respondio pero perdio paquetes.
    # Esta categoria es la que NUNCA se omite (regla fija).
    partial_loss = [
        hs for hs in hop_stats if hs.loss_pct > 0.0 and hs.success_count > 0
    ]
    if partial_loss:
        lines.append(" hops con perdida parcial (respondio + descarto):")
        for hs in partial_loss:
            ip = hs.ip or "?"
            lines.append(
                f"   hop {hs.hop_number:2d} ip={ip:15s} "
                f"loss={hs.loss_pct:5.1f}% (samples={hs.samples} "
                f"success={hs.success_count})"
            )

    # Hops que nunca respondieron (loss 100): reportar como ausencia
    # de dato, no como fallo confirmado (puede ser ICMP deprioritized).
    no_response = [
        hs for hs in hop_stats if hs.loss_pct >= 100.0 and hs.success_count == 0
    ]
    if no_response:
        lines.append(" hops sin respuesta (no aporta dato de latencia):")
        for hs in no_response:
            lines.append(f"   hop {hs.hop_number:2d} (samples={hs.samples})")

    # Jitter alto en hops que respondieron (samples >= 2 para que
    # jitter sea distinto de 0). Umbral default 20ms (TECHNICAL_SPEC §5).
    jitter_warning_ms = 20.0
    high_jitter = [
        hs
        for hs in hop_stats
        if hs.success_count > 1 and hs.jitter_ms > jitter_warning_ms
    ]
    if high_jitter:
        lines.append(f" hops con jitter alto (>{jitter_warning_ms:.0f}ms):")
        for hs in high_jitter:
            ip = hs.ip or "?"
            lines.append(
                f"   hop {hs.hop_number:2d} ip={ip:15s} "
                f"jitter={hs.jitter_ms:6.2f}ms"
            )

    if not lines:
        return " sin anomalias observadas en hops intermedios."
    return "\n".join(lines)


def fill_ip_hostname_mode(
    stats: list[HopStats],
    per_hop_observations: dict[int, list[tuple[str | None, str | None]]],
) -> list[HopStats]:
    """Rellena ``HopStats.ip``/``hostname`` con la MODA de observaciones.

    El ``RouteMonitor`` orquestador tiene, por cada hop_number, una lista
    de (ip, hostname) observados a lo largo de las muestras (uno por
    muestra donde ese hop respondio). Esta funcion selecciona la
    (ip, hostname) mas frecuente y reconstruye cada ``HopStats``.

    Mantiene la inmutabilidad: como ``HopStats`` es frozen=True, no
    mutamos in place. Creamos copias con dataclasses.replace.

    Args:
        stats: lista de HopStats con ip=None, hostname=None (lo que
            devuelve `aggregate_hops`).
        per_hop_observations: dict hop_number -> lista de (ip, hostname)
            observados cuando respondio. Los (None, None) se ignoran
            (no se observo IP en esa muestra).

    Returns:
        Nueva lista de HopStats con ip/hostname seteados cuando hubo
        observaciones (no None). Si para un hop_number no hay
        observaciones (todas las muestras fueron timeout), ip=None y
        hostname=None se mantienen.
    """
    # Import local para evitar dependency cycle en tests que solo testean
    # aggregate_hops.
    from dataclasses import replace

    result: list[HopStats] = []
    for hs in stats:
        obs = per_hop_observations.get(hs.hop_number, [])
        # Filtrar observaciones con ip None (timeout en ese sample).
        valid = [(ip, hn) for ip, hn in obs if ip is not None]
        if valid:
            # Moda: par (ip, hostname) mas frecuente. Counter sobre tuple
            # hace exactamente esto.
            ip_mode, hostname_mode = Counter(valid).most_common(1)[0][0]
        else:
            ip_mode, hostname_mode = None, None
        result.append(replace(hs, ip=ip_mode, hostname=hostname_mode))
    return result
