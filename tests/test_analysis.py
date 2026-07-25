"""Tests de analysis/baseline.py y analysis/score.py — Fase 4.

Dataset sintetico: 30 dias de latencias normales + anomalia inyectada
dia 31 (IMPLEMENTATION_PLAN.md Fase 4 DoD).

Separacion de providers verificada a nivel de logica de analisis,
no solo de SQL (TECHNICAL_SPEC.md §3).
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from gnd.analysis.baseline import (
    compute_baseline,
    is_anomaly,
)
from gnd.analysis.score import (
    JITTER_CEILING_MS,
    PACKET_LOSS_CEILING_PCT,
    compute_network_score,
    normalize_internet_health,
    normalize_jitter,
    normalize_local_stability,
    normalize_packet_loss,
    normalize_riot_latency,
)
from gnd.database.schema import ensure_schema
from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult

# ── Helpers ────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    return conn


def _insert_probe(
    conn: sqlite3.Connection,
    run_id: str,
    provider: str,
    avg_ms: float,
    *,
    outcome: str = "SUCCESS",
    packet_loss_pct: float = 0.0,
    jitter_ms: float = 2.0,
    timestamp: datetime | None = None,
) -> None:
    ts = (timestamp or datetime.now()).isoformat()
    conn.execute(
        """INSERT INTO probe_results
           (run_id, target_name, target_ip, provider, outcome,
            avg_ms, min_ms, max_ms, jitter_ms, packet_loss_pct,
            samples, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            f"target-{provider}",
            "1.2.3.4",
            provider,
            outcome,
            avg_ms if outcome == "SUCCESS" else None,
            (avg_ms - 5.0) if outcome == "SUCCESS" else None,
            (avg_ms + 5.0) if outcome == "SUCCESS" else None,
            jitter_ms if outcome == "SUCCESS" else None,
            packet_loss_pct if outcome == "SUCCESS" else None,
            10 if outcome == "SUCCESS" else None,
            ts,
        ),
    )


def _insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    probes: list[tuple[str, float]],
    *,
    timestamp: datetime | None = None,
) -> None:
    ts = timestamp or datetime.now()
    now = ts.isoformat()
    conn.execute(
        """INSERT INTO diagnostic_runs
           (run_id, started_at, finished_at,
            recommendation_verdict, recommendation_headline,
            recommendation_explanation, recommendation_score,
            responsible_component)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            now,
            (ts + timedelta(seconds=5)).isoformat(),
            "safe_to_play",
            "OK",
            '["test"]',
            90,
            "unknown",
        ),
    )
    for provider, avg_ms in probes:
        _insert_probe(conn, f"{run_id}-{provider}", provider, avg_ms, timestamp=ts)


def _populate_30day_dataset(conn: sqlite3.Connection) -> None:
    """Poblacion de 30 dias de latencias normales + anomalia dia 31.

    Providers: riot_public (20ms estable), riot_game_server (25ms estable),
    google (10ms), cloudflare (12ms), quad9 (11ms), local (5ms).
    Dia 31: riot_game_server salta a 120ms (anomalia detectable).
    """
    now = datetime.now()
    base = now - timedelta(days=30)

    for day in range(30):
        ts = base + timedelta(days=day, hours=12)
        _insert_run(
            conn,
            f"day-{day:02d}",
            [
                ("riot_public", 20.0),
                ("riot_game_server", 25.0),
                ("google", 10.0),
                ("cloudflare", 12.0),
                ("quad9", 11.0),
                ("local", 5.0),
            ],
            timestamp=ts,
        )

    # Dia 31: anomalia en riot_game_server
    ts_anomaly = base + timedelta(days=30, hours=12)
    _insert_run(
        conn,
        "day-31-anomaly",
        [
            ("riot_public", 20.0),
            ("riot_game_server", 120.0),  # anomalia
            ("google", 10.0),
            ("cloudflare", 12.0),
            ("quad9", 11.0),
            ("local", 5.0),
        ],
        timestamp=ts_anomaly,
    )


# ── Tests: compute_baseline ───────────────────────────────────────────


def test_baseline_basic_calculation() -> None:
    """Baseline calcula media y stddev correctamente."""
    conn = _conn()
    for i in range(10):
        _insert_probe(
            conn,
            f"run-{i}",
            "google",
            10.0 + float(i),
            timestamp=datetime.now() - timedelta(days=10 - i),
        )

    baseline = compute_baseline(conn, "google", 30, now=datetime.now())
    assert baseline.provider == "google"
    assert baseline.sample_count == 10
    assert baseline.avg_ms == pytest.approx(14.5, abs=0.1)
    assert baseline.stddev_ms > 0.0


def test_baseline_single_sample_stddev_zero() -> None:
    """Un solo sample -> stddev = 0."""
    conn = _conn()
    _insert_probe(conn, "run-1", "cloudflare", 15.0)

    baseline = compute_baseline(conn, "cloudflare", 30, now=datetime.now())
    assert baseline.sample_count == 1
    assert baseline.avg_ms == 15.0
    assert baseline.stddev_ms == 0.0


def test_baseline_empty_provider() -> None:
    """Provider sin datos -> zeros."""
    conn = _conn()
    baseline = compute_baseline(conn, "inexistente", 30, now=datetime.now())
    assert baseline.sample_count == 0
    assert baseline.avg_ms == 0.0
    assert baseline.stddev_ms == 0.0


def test_baseline_excludes_failed_probes() -> None:
    """Solo probes SUCCESS entran al baseline."""
    conn = _conn()
    _insert_probe(conn, "run-ok", "google", 10.0, outcome="SUCCESS")
    _insert_probe(conn, "run-filtered", "google", 10.0, outcome="FILTERED")
    _insert_probe(conn, "run-timeout", "google", 10.0, outcome="TIMEOUT")

    baseline = compute_baseline(conn, "google", 30, now=datetime.now())
    assert baseline.sample_count == 1


def test_baseline_respects_period_days() -> None:
    """Solo samples dentro del periodo se incluyen."""
    conn = _conn()
    now = datetime.now()

    # Sample viejo (60 dias atras)
    _insert_probe(conn, "old", "google", 200.0, timestamp=now - timedelta(days=60))
    # Sample reciente
    _insert_probe(conn, "new", "google", 10.0, timestamp=now - timedelta(days=1))

    baseline_short = compute_baseline(conn, "google", 30, now=now)
    assert baseline_short.sample_count == 1
    assert baseline_short.avg_ms == 10.0

    baseline_long = compute_baseline(conn, "google", 90, now=now)
    assert baseline_long.sample_count == 2


def test_baseline_never_mixes_providers() -> None:
    """TECHNICAL_SPEC.md §3: riot_public y riot_game_server NUNCA se mezclan.

    Mismo patron de rigor que Fase 3, ahora a nivel de logica de analisis.
    """
    conn = _conn()
    now = datetime.now()

    # 10 samples de riot_public a 20ms
    for i in range(10):
        _insert_probe(
            conn,
            f"pub-{i}",
            "riot_public",
            20.0,
            timestamp=now - timedelta(days=10 - i),
        )

    # 10 samples de riot_game_server a 100ms (muy distinto)
    for i in range(10):
        _insert_probe(
            conn,
            f"game-{i}",
            "riot_game_server",
            100.0,
            timestamp=now - timedelta(days=10 - i),
        )

    baseline_public = compute_baseline(conn, "riot_public", 30, now=now)
    baseline_game = compute_baseline(conn, "riot_game_server", 30, now=now)

    # Verificar que los promedios son distintos (no mezclados)
    assert baseline_public.avg_ms == pytest.approx(20.0, abs=0.1)
    assert baseline_game.avg_ms == pytest.approx(100.0, abs=0.1)
    assert baseline_public.sample_count == 10
    assert baseline_game.sample_count == 10

    # Si se hubieran mezclado, ambos tendrian avg=60 y sample_count=20
    assert baseline_public.avg_ms != baseline_game.avg_ms


def test_baseline_30day_dataset_anomaly_detection() -> None:
    """DoD Fase 4: dataset 30d con anomalia dia 31 debe detectarse."""
    conn = _conn()
    _populate_30day_dataset(conn)
    now = datetime.now()

    # Baseline de los 30 dias normales (excluyendo dia 31)
    baseline = compute_baseline(
        conn, "riot_game_server", 30, now=now - timedelta(days=1)
    )

    # El dataset tiene 31 entradas; la anomalia del dia 30 (120ms)
    # esta dentro de la ventana. Verificamos que la deteccion funciona.
    assert baseline.sample_count >= 30
    assert baseline.stddev_ms > 5.0  # la anomalia aumenta la dispersion

    # La anomalia del dia 31 (120ms) debe ser detectada
    assert is_anomaly(120.0, baseline) is True

    # Un valor normal (25ms) no debe ser anomalo
    assert is_anomaly(25.0, baseline) is False


# ── Tests: is_anomaly ─────────────────────────────────────────────────


def test_is_anomaly_within_threshold() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=20.0, stddev_ms=5.0, sample_count=30)
    assert is_anomaly(25.0, b) is False  # 20 + 2*5 = 30


def test_is_anomaly_above_threshold() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=20.0, stddev_ms=5.0, sample_count=30)
    assert is_anomaly(35.0, b) is True  # 35 > 30


def test_is_anomaly_no_data() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=0.0, stddev_ms=0.0, sample_count=0)
    assert is_anomaly(100.0, b) is False  # sin datos = sin juicio


def test_is_anomaly_zero_stddev() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=20.0, stddev_ms=0.0, sample_count=1)
    assert is_anomaly(20.0, b) is False
    assert is_anomaly(21.0, b) is True  # cualquier desviacion con stddev=0


# ── Tests: normalization functions ─────────────────────────────────────


def test_normalize_packet_loss_zero() -> None:
    assert normalize_packet_loss(0.0) == 100.0


def test_normalize_packet_loss_ceiling() -> None:
    assert normalize_packet_loss(PACKET_LOSS_CEILING_PCT) == 0.0


def test_normalize_packet_loss_midpoint() -> None:
    mid = normalize_packet_loss(PACKET_LOSS_CEILING_PCT / 2)
    assert mid == pytest.approx(50.0, abs=0.1)


def test_normalize_jitter_zero() -> None:
    assert normalize_jitter(0.0) == 100.0


def test_normalize_jitter_ceiling() -> None:
    assert normalize_jitter(JITTER_CEILING_MS) == 0.0


def test_normalize_riot_latency_within_avg() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=20.0, stddev_ms=5.0, sample_count=30)
    assert normalize_riot_latency(20.0, b) == 100.0


def test_normalize_riot_latency_above_threshold() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=20.0, stddev_ms=5.0, sample_count=30)
    # threshold = 20 + 1.5*5 = 27.5
    assert normalize_riot_latency(30.0, b) == 0.0


def test_normalize_riot_latency_no_baseline() -> None:
    b = HistoricalBaseline("test", 30, avg_ms=0.0, stddev_ms=0.0, sample_count=0)
    assert normalize_riot_latency(50.0, b) == 60.0  # neutral


def test_normalize_internet_health_all_success() -> None:
    def _probe(avg_ms: float) -> ProbeResult:
        return ProbeResult(
            target_name="t",
            target_ip="1.1.1.1",
            provider="test",
            outcome=ProbeOutcomeKind.SUCCESS,
            stats=LatencyStats(
                avg_ms=avg_ms,
                min_ms=avg_ms - 2,
                max_ms=avg_ms + 2,
                jitter_ms=1.0,
                packet_loss_pct=0.0,
                samples=10,
            ),
            timestamp=datetime.now(),
        )

    score = normalize_internet_health(_probe(10.0), _probe(12.0), _probe(11.0))
    assert score > 80.0  # latencias bajas = score alto


def test_normalize_internet_health_all_filtered() -> None:
    def _filtered() -> ProbeResult:
        return ProbeResult(
            target_name="t",
            target_ip="1.1.1.1",
            provider="test",
            outcome=ProbeOutcomeKind.FILTERED,
            stats=None,
            timestamp=datetime.now(),
        )

    score = normalize_internet_health(_filtered(), _filtered(), _filtered())
    assert score == 0.0


def test_normalize_internet_health_none_available() -> None:
    score = normalize_internet_health(None, None, None)
    assert score is None  # sin datos = None (redistribuir peso, no penalizar)


def test_normalize_local_stability_good() -> None:
    p = ProbeResult(
        target_name="gw",
        target_ip="192.168.1.1",
        provider="local",
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=5.0,
            min_ms=3.0,
            max_ms=7.0,
            jitter_ms=1.0,
            packet_loss_pct=0.0,
            samples=10,
        ),
        timestamp=datetime.now(),
    )
    score = normalize_local_stability(p)
    assert score > 90.0


def test_normalize_local_stability_high_loss() -> None:
    p = ProbeResult(
        target_name="gw",
        target_ip="192.168.1.1",
        provider="local",
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=5.0,
            min_ms=3.0,
            max_ms=7.0,
            jitter_ms=1.0,
            packet_loss_pct=4.5,
            samples=10,
        ),
        timestamp=datetime.now(),
    )
    score = normalize_local_stability(p)
    assert score < 50.0


def test_normalize_local_stability_no_data() -> None:
    assert normalize_local_stability(None) == 0.0  # sin datos = penaliza


# ── Tests: compute_network_score ───────────────────────────────────────


def _make_probe(
    provider: str,
    avg_ms: float,
    packet_loss: float = 0.0,
    jitter: float = 2.0,
) -> ProbeResult:
    return ProbeResult(
        target_name=f"t-{provider}",
        target_ip="1.2.3.4",
        provider=provider,
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=avg_ms,
            min_ms=avg_ms - 3,
            max_ms=avg_ms + 3,
            jitter_ms=jitter,
            packet_loss_pct=packet_loss,
            samples=10,
        ),
        timestamp=datetime.now(),
    )


def test_score_all_good() -> None:
    """Todos los providers sanos -> score alto."""
    probes = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 25.0, 2.0, 30),
    }
    score = compute_network_score(probes, baselines)
    assert score >= 80


def test_score_high_packet_loss() -> None:
    """Packet loss alto -> score baja significativamente (25% del total)."""
    probes = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
        _make_probe("google_lossy", 10.0, packet_loss=4.0),
    ]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 25.0, 2.0, 30),
    }
    score_lossy = compute_network_score(probes, baselines)

    probes_clean = [p for p in probes if p.provider != "google_lossy"]
    score_clean = compute_network_score(probes_clean, baselines)

    assert score_lossy < score_clean


def test_score_riot_latency_degraded() -> None:
    """Riot game server con latencia degradada vs baseline -> score baja (35%)."""
    probes_good = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 25.0, 2.0, 30),
    }
    score_good = compute_network_score(probes_good, baselines)

    probes_bad = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 80.0),  # degradado
    ]
    score_bad = compute_network_score(probes_bad, baselines)

    assert score_bad < score_good
    assert score_bad < 70  # penalizacion significativa por riot degradado


def test_score_range_0_100() -> None:
    """Score siempre esta en [0, 100]."""
    # Peor caso: todo degradado
    probes_worst = [
        ProbeResult(
            target_name="t",
            target_ip="1.1.1.1",
            provider="test",
            outcome=ProbeOutcomeKind.TIMEOUT,
            stats=None,
            timestamp=datetime.now(),
        ),
    ]
    score = compute_network_score(probes_worst, {})
    assert 0 <= score <= 100


def test_score_missing_probes_redistributes() -> None:
    """Probes faltantes redistribuyen peso, no penalizan.

    Regla: un componente sin datos se excluye y su peso se reparte
    entre los que sí tienen datos (TECHNICAL_SPEC §7 + §4.2).
    """
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 25.0, 2.0, 30),
    }

    # Sin probes: score = 0
    score_empty = compute_network_score([], {})
    assert score_empty == 0

    # Con probes completos: score alto
    probes_full = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    score_full = compute_network_score(probes_full, baselines)

    # Con solo 1 probe (google): solo loss/jitter tienen datos, el resto
    # se excluye. El peso se redistribuye entre loss (25%) y jitter (20%).
    probes_one = [_make_probe("google", 10.0)]
    score_one = compute_network_score(probes_one, baselines)

    assert score_empty < score_one < score_full


def test_score_quad9_missing_vs_present() -> None:
    """Test clave: mismo score si Quad9 responde perfecto vs si no responde.

    Escenario: Google=10ms, Cloudflare=12ms, Riot=25ms (baseline 25ms),
    local=5ms. Quad9 en (a) responde 11ms, en (b) no existe (None).

    Resultado esperado: scores muy similares (< 5 puntos de diferencia).
    Un probe DNS que no responde no debe hundir el 15% del score.
    """
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 25.0, 2.0, 30),
    }

    # (a) Quad9 presente con latencia normal
    probes_with_quad9 = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    score_with = compute_network_score(probes_with_quad9, baselines)

    # (b) Quad9 ausente (no responde en absoluto)
    probes_without_quad9 = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        # quad9 None -> se excluye, peso redistribuido
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    score_without = compute_network_score(probes_without_quad9, baselines)

    # Ambos scores deben ser altos (>80) y cercanos entre si
    assert score_with >= 80
    assert score_without >= 80
    diff = abs(score_with - score_without)
    assert diff <= 5, (
        f"Score con Quad9 ({score_with}) vs sin Quad9 ({score_without}) "
        f"diferencia demasiado grande: {diff} puntos"
    )


def test_score_all_internet_probes_missing_redistributes() -> None:
    """Si TODOS los DNS faltan, el peso de internet_health (15%) se
    redistribuye entre los demas componentes que sí tienen datos.
    """
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 25.0, 2.0, 30),
    }

    # Solo riot + local: sin internet_health
    probes_no_internet = [
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    score_no_internet = compute_network_score(probes_no_internet, baselines)

    # Completo: riot + local + internet
    probes_full = [
        _make_probe("google", 10.0),
        _make_probe("cloudflare", 12.0),
        _make_probe("quad9", 11.0),
        _make_probe("local", 5.0),
        _make_probe("riot_game_server", 25.0),
    ]
    score_full = compute_network_score(probes_full, baselines)

    # Ambos deben ser altos: internet healthy no deberia cambiar mucho
    assert score_no_internet >= 75
    assert score_full >= 80
    diff = abs(score_full - score_no_internet)
    assert diff <= 5, (
        f"Score completo ({score_full}) vs sin internet ({score_no_internet}) "
        f"diferencia: {diff}"
    )
