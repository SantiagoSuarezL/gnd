"""Network Score — ponderado 0-100 segun TECHNICAL_SPEC.md §4.2.

Cada componente se normaliza a 0-100 antes de ponderar.
Las formulas de normalizacion estan documentadas en codigo
(ENGINEERING_PRINCIPLES.md §1.4: todo numero debe ser trazable a una razon).
"""

from __future__ import annotations

from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult

# ── Pesos del score (TECHNICAL_SPEC.md §4.2) ──────────────────────────
# Cada peso representa la proporcion del score final (suman 1.0).
WEIGHT_RIOT_LATENCY: float = 0.35  # Latencia Riot game server vs baseline
WEIGHT_PACKET_LOSS: float = 0.25  # Packet loss (cualquier provider relevante)
WEIGHT_JITTER: float = 0.20  # Jitter (cualquier provider)
WEIGHT_INTERNET_HEALTH: float = 0.15  # Salud Internet general (Google/CF/Quad9)
WEIGHT_LOCAL_STABILITY: float = 0.05  # Estabilidad ruta local (gateway)

# ── Limites de normalizacion ───────────────────────────────────────────
# Cada componente se mapea linealmente de [0, limite] -> [100, 0].
# Mas alla del limite, el score del componente es 0.
#
# Packet loss: 0% = 100, >=5% = 0
PACKET_LOSS_CEILING_PCT: float = 5.0

# Jitter: 0ms = 100, >=50ms = 0
JITTER_CEILING_MS: float = 50.0

# Latencia Riot vs baseline: dentro del threshold = 100, fuera = 0
# (ver normalize_riot_latency para la formula completa)
RIOT_LATENCY_GRACE_FACTOR: float = 1.5  # tolerancia: avg + grace * stddev


def normalize_riot_latency(
    current_ms: float,
    baseline: HistoricalBaseline,
) -> float:
    """Normaliza la latencia Riot vs baseline a 0-100.

    Formula:
        threshold = baseline.avg_ms + RIOT_LATENCY_GRACE_FACTOR * baseline.stddev_ms
        Si current_ms <= baseline.avg_ms -> 100 (perfecto, dentro del promedio)
        Si current_ms >= threshold -> 0 (fuera del rango aceptable)
        Caso contrario -> interpolacion lineal entre 100 y 0

    Razon: no penaliza fluctuaciones normales (dentro de stddev), pero
    penaliza fuertemente desviaciones grandes.
    """
    if baseline.sample_count == 0:
        # Sin baseline: asumir score intermedio (60) para no sesgar.
        return 60.0

    if current_ms <= baseline.avg_ms:
        return 100.0

    threshold = baseline.avg_ms + RIOT_LATENCY_GRACE_FACTOR * baseline.stddev_ms
    if baseline.stddev_ms == 0.0:
        # Sin dispersion: umbral estricto = avg * 1.5
        threshold = baseline.avg_ms * 1.5 if baseline.avg_ms > 0 else 1.0

    if current_ms >= threshold:
        return 0.0

    # Interpolacion lineal: de 100 (en avg) a 0 (en threshold)
    range_span = threshold - baseline.avg_ms
    ratio = (current_ms - baseline.avg_ms) / range_span
    return max(0.0, min(100.0, 100.0 * (1.0 - ratio)))


def normalize_packet_loss(loss_pct: float) -> float:
    """Normaliza packet loss a 0-100.

    0% = 100, >= PACKET_LOSS_CEILING_PCT = 0.
    Interpolacion lineal entre ambos puntos.
    """
    if loss_pct <= 0.0:
        return 100.0
    if loss_pct >= PACKET_LOSS_CEILING_PCT:
        return 0.0
    return 100.0 * (1.0 - loss_pct / PACKET_LOSS_CEILING_PCT)


def normalize_jitter(jitter_ms: float) -> float:
    """Normaliza jitter a 0-100.

    0ms = 100, >= JITTER_CEILING_MS = 0.
    Interpolacion lineal entre ambos puntos.
    """
    if jitter_ms <= 0.0:
        return 100.0
    if jitter_ms >= JITTER_CEILING_MS:
        return 0.0
    return 100.0 * (1.0 - jitter_ms / JITTER_CEILING_MS)


def _score_single_probe(p: ProbeResult) -> float:
    """Score de un solo probe de Internet: latencia vs benchmark.

    Benchmark = 20ms (typical DNS). Formula: 100 * (1 - avg_ms / 60).
    Un probe con avg_ms=0 da 100; avg_ms=60 o mas da 0.
    """
    if p.outcome != ProbeOutcomeKind.SUCCESS or p.stats is None:
        return 0.0
    bench = 20.0
    ratio = p.stats.avg_ms / (bench * 3)
    return max(0.0, min(100.0, 100.0 * (1.0 - ratio)))


def normalize_internet_health(
    google: ProbeResult | None,
    cloudflare: ProbeResult | None,
    quad9: ProbeResult | None,
) -> float | None:
    """Salud de Internet general: promedio de los DNS publicos disponibles.

    Regla (TECHNICAL_SPEC.md §7 + §4.2): un host que no responde no es
    automaticamente "malo". Probes faltantes (None) o FILTERED se excluyen
    del promedio — no penalizan, simplemente no aportan dato.

    Retorna:
        float 0-100 si al menos 1 probe respondio (promedio de los disponibles).
        None si NINGUN probe respondio (senial para redistribuir peso).
    """
    probes = [google, cloudflare, quad9]
    available = [p for p in probes if p is not None]

    if not available:
        return None

    scores = [_score_single_probe(p) for p in available]
    return sum(scores) / len(scores)


def normalize_local_stability(
    gateway: ProbeResult | None,
) -> float:
    """Estabilidad de ruta local (gateway): combina loss y jitter.

    60% weight en packet_loss, 40% en jitter.
    Si el gateway no esta disponible, retorna 0 (penalizacion)
    en vez de neutral, para que la ausencia de dato reduzca el score.
    """
    if gateway is None or gateway.outcome != ProbeOutcomeKind.SUCCESS:
        return 0.0

    stats = gateway.stats
    if stats is None:
        return 0.0

    loss_score = normalize_packet_loss(stats.packet_loss_pct)
    jitter_score = normalize_jitter(stats.jitter_ms)
    return 0.6 * loss_score + 0.4 * jitter_score


def compute_network_score(
    probes: list[ProbeResult],
    baselines: dict[str, HistoricalBaseline],
) -> int:
    """Computa el Network Score 0-100 (TECHNICAL_SPEC.md §4.2).

    Pesos base:
        Riot latency vs baseline: 35%
        Packet loss: 25%
        Jitter: 20%
        Internet health (Google/CF/Quad9): 15%
        Local stability (gateway): 5%

    Redistribucion de pesos: si un componente no tiene datos disponibles
    (None o sin probes), su peso se redistribuye proporcionalmente entre
    los componentes que sí tienen datos. Razon (TECHNICAL_SPEC.md §7):
    un probe que no responde no es automaticamente "malo"; la ausencia
    de dato no debe hundir el score.

    Args:
        probes: lista de ProbeResult de la corrida actual.
        baselines: dict{provider: HistoricalBaseline} pre-computados.

    Returns:
        int 0-100 (redondeo del score float).
    """
    # Indexar probes por provider
    by_provider: dict[str, ProbeResult] = {}
    for p in probes:
        by_provider[p.provider] = p

    # ── Componente 1: Latencia Riot game server (35%) ──
    riot_server = by_provider.get("riot_game_server")
    riot_baseline = baselines.get(
        "riot_game_server", HistoricalBaseline("riot_game_server", 30, 0, 0, 0)
    )
    riot_score: float | None = None
    if riot_server and riot_server.stats:
        riot_score = normalize_riot_latency(riot_server.stats.avg_ms, riot_baseline)

    # ── Componente 2: Packet loss — el PEOR de todos los providers (25%) ──
    probed = [p for p in probes if p.stats is not None]
    loss_score: float | None = None
    if probed:
        max_loss = max(p.stats.packet_loss_pct for p in probed)
        loss_score = normalize_packet_loss(max_loss)

    # ── Componente 3: Jitter — el PEOR de todos los providers (20%) ──
    jitter_score: float | None = None
    if probed:
        max_jitter = max(p.stats.jitter_ms for p in probed)
        jitter_score = normalize_jitter(max_jitter)

    # ── Componente 4: Internet health — Google/Cloudflare/Quad9 (15%) ──
    internet_score = normalize_internet_health(
        by_provider.get("google"),
        by_provider.get("cloudflare"),
        by_provider.get("quad9"),
    )

    # ── Componente 5: Local stability — gateway (5%) ──
    local_score: float | None = None
    gateway = by_provider.get("local")
    if gateway is not None:
        local_score = normalize_local_stability(gateway)

    # ── Redistribucion de pesos ──
    # Componentes con datos: (peso_base, score). Si score es None, se excluye.
    components: list[tuple[float, float]] = [
        (WEIGHT_RIOT_LATENCY, riot_score),
        (WEIGHT_PACKET_LOSS, loss_score),
        (WEIGHT_JITTER, jitter_score),
        (WEIGHT_INTERNET_HEALTH, internet_score),
        (WEIGHT_LOCAL_STABILITY, local_score),
    ]

    active = [(w, s) for w, s in components if s is not None]
    if not active:
        return 0

    total_weight = sum(w for w, _ in active)
    weighted = sum(w * s for w, s in active) / total_weight

    return max(0, min(100, round(weighted)))
