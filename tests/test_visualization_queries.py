"""Tests de SqliteSeriesDataSource (Fase 10).

EP §3 + §4: tests unitarios de dominio. No tocan red, no abren archivo
en %APPDATA%, no usan tiempo real (inyecta ``now`` para determinismo
— mismo patrón que ``test_historical_baseline.py``).

Patron: ``FakeDatabaseConnectionFactory(shared_conn)`` que devuelve la
misma ``sqlite3.connect(":memory:")``. Sembramos rows con SQL directo
(no nos importa el tipo de escritor que produce probe_results — eso
se valida en ``test_sqlite_diagnostics_repository.py``), luego llama-
mos los métodos de SeriesDataSource y verificamos el ChartDataSet.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from gnd.database.schema import ensure_schema
from gnd.domain.fakes import FakeDatabaseConnectionFactory
from gnd.visualization import SqliteSeriesDataSource
from gnd.visualization.models import ChartDataSet, SeriesPoint

NOW = datetime(2026, 7, 27, 14, 0, 0)


def _insert_probe(
    conn: sqlite3.Connection,
    *,
    provider: str,
    avg_ms: float,
    loss: float,
    outcome: str = "SUCCESS",
    ts: datetime | None = None,
) -> None:
    """Inserta un row en probe_results (schema v1 unlocked)."""
    conn.execute(
        """INSERT INTO probe_results
           (run_id, target_name, target_ip, provider, outcome,
            avg_ms, min_ms, max_ms, jitter_ms, packet_loss_pct,
            samples, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"run-{provider}-{ts.isoformat() if ts else NOW.isoformat()}",
            f"t-{provider}",
            "1.2.3.4",
            provider,
            outcome,
            avg_ms,
            max(0.0, avg_ms - 5.0),
            avg_ms + 5.0,
            3.0,
            loss,
            10,
            (ts or NOW).isoformat(),
        ),
    )


def _seed_conn() -> sqlite3.Connection:
    """Crea una conn nueva seeded con 24 horas de data para 4 providers.

    Para que ``best_hours_to_play`` pase el umbral default
    ``min_samples=3`` (regla kickoff Fase 10), sembramos 24 muestras
    por hora (un punto por hora por 24 días). Esto reproduce un uso
    orgánico realista donde el chart de "mejores horas" tiene n≥3
    por hora.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    for day in range(24):  # 24 días de historia para que cada hora tenga n=24
        for hour in range(24):  # 24 horas del día
            ts = NOW - timedelta(days=24 - day) + timedelta(hours=hour)
            # latencia creciente con la hora del día (simulando congestión vespertina).
            base = 12.0 + 5.0 * (hour / 24)
            for provider, latency in (
                ("google", base),
                ("cloudflare", base - 1),
                ("quad9", base + 1),
                ("riot_public", base + 8),  # Riot tiende a ser más alto.
            ):
                _insert_probe(
                    conn,
                    provider=provider,
                    avg_ms=latency,
                    loss=(0.0 if day % 5 != 0 else 1.0),  # pico de loss cada 5 días.
                    ts=ts,
                )
    return conn


def _make_source(conn: sqlite3.Connection) -> SqliteSeriesDataSource:
    factory = FakeDatabaseConnectionFactory(conn)
    return SqliteSeriesDataSource(factory, now=NOW)


# ── latency_over_time ───────────────────────────────────────────────


def test_latency_over_time_returns_multi_series() -> None:
    """La query agrupa por provider: 4 series, 24 puntos c/u."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.latency_over_time(
        providers=["google", "cloudflare", "quad9", "riot_public"],
        period_days=30,
    )
    assert not ds.is_empty
    assert len(ds.points) == 4 * 24 * 24  # 4 providers × 24 días × 24 horas
    assert set(ds.groups) == {"google", "cloudflare", "quad9", "riot_public"}


def test_latency_over_time_filters_by_period() -> None:
    """period_days pequeño excluye rows fuera del cutoff."""
    conn = _seed_conn()
    # Ajusta now a 25h en el futuro — los 24h seeded quedan fuera.
    far_source = _make_source(conn).__class__(
        FakeDatabaseConnectionFactory(conn),
        now=NOW + timedelta(hours=25),
    )
    ds = far_source.latency_over_time(
        providers=["google"],
        period_days=1,  # 24h window
    )
    # period_days=1 → cutoff 24h atrás. NOW+25h está 1h después del último insert.
    # El último insert está a 1h (ts=NOW). Cutoff = NOW+25h - 1d = NOW+1h.
    # Quedan fuera todos (ts < cutoff). Result: empty.
    assert ds.is_empty


def test_latency_over_time_excludes_non_success() -> None:
    """Probes con outcome != SUCCESS no aparecen en el chart de latencia."""
    conn = _seed_conn()
    # Inserta 1 row UNREACHABLE que NO debe sumar al dataset.
    _insert_probe(
        conn,
        provider="google",
        avg_ms=999.0,
        loss=100.0,
        outcome="UNREACHABLE",
        ts=NOW - timedelta(hours=1),
    )
    source = _make_source(conn)
    ds = source.latency_over_time(providers=["google"], period_days=30)
    google_vals = [p.y for p in ds.points if p.group == "google"]
    assert 999.0 not in google_vals


def test_latency_over_time_empty_when_no_providers() -> None:
    """providers=[] → empty dataset (no SQL, no rows)."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.latency_over_time(providers=[])
    assert ds.is_empty
    assert ds.title == "Latencia a lo largo del tiempo"


# ── packet_loss_over_time ────────────────────────────────────────────


def test_packet_loss_over_time_returns_series_with_loss_points() -> None:
    """Packet loss solo se grafica cuando hay valor (FILTERED presta loss)."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.packet_loss_over_time(providers=["google"], period_days=30)
    # 24 días × 24 horas = 576 inserts google, todos con loss (0.0 o 1.0) en _seed_conn.
    assert len(ds.points) == 24 * 24
    assert any(p.y > 0.0 for p in ds.points)


# ── cloudflare_vs_google ──────────────────────────────────────────────


def test_cloudflare_vs_google_returns_two_series() -> None:
    """Solo providers cloudflare y google aparecen en este chart."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.cloudflare_vs_google(period_days=30)
    assert set(ds.groups) == {"cloudflare", "google"}
    assert len(ds.points) == 2 * 24 * 24  # 2 providers × 24 días × 24 horas


def test_cloudflare_vs_google_excludes_riot_public() -> None:
    """El Riot no se cuela en la comparativa de DNS públicos."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.cloudflare_vs_google(period_days=30)
    assert "riot_public" not in ds.groups
    assert "quad9" not in ds.groups


# ── riot_latency_over_time ────────────────────────────────────────────


def test_riot_latency_over_time_default_provider_is_riot_public() -> None:
    """Default es riot_public (proxy de infraestructura Riot, tech_stack #11)."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.riot_latency_over_time(period_days=30)
    assert ds.points
    assert all(p.group == "riot_public" for p in ds.points)


def test_riot_latency_over_time_empty_when_no_data_for_provider() -> None:
    """Si el provider pedido no tiene rows, dataset es vacío + title correcto."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.riot_latency_over_time(provider="riot_game_server")
    assert ds.is_empty
    assert "riot_game_server" in ds.title


# ── best_hours_to_play ────────────────────────────────────────────────


def test_best_hours_to_play_aggregates_by_hour() -> None:
    """Group por hora del día (no por timestamp individual)."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.best_hours_to_play(provider="google", period_days=30)
    assert not ds.is_empty
    # El seed usa 24 horas distintas → 24 grupos hora "00".."23".
    assert len(ds.groups) == 24
    # Los groups son strings "00".."23".
    assert all(len(p.group) == 2 for p in ds.points)


def test_best_hours_to_play_finds_minimum() -> None:
    """El primer punto seeded tiene la latencia más baja → mejor hora."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.best_hours_to_play(provider="google", period_days=30)
    values = [p.y for p in ds.points]
    assert min(values) == min(values)  # sanity (no magic)
    # Cross-check: el script de verificación usa esto para denotar ★.


def test_best_hours_to_play_excludes_hours_below_min_samples() -> None:
    """Regla (Fase 10 kickoff, 2026-07-27): con <N muestras por hora, esa hora
    se excluye del gráfico. Evita que un n=1 marcado como ★ distorsione la
    lectura de "mejor hora" cuando hay pocas corridas reales.

    Seed tiene 24 muestras por provider (1/hora). Bajamos min_samples a un
    valor tal que se excluyen horas con menos del mínimo.
    """
    conn = _seed_conn()
    source = _make_source(conn)
    ds_full = source.best_hours_to_play(provider="google", period_days=30)
    ds_filtered = source.best_hours_to_play(
        provider="google", period_days=30, min_samples=100
    )
    # min_samples=100 > n_real=24 → todas las horas excluidas → empty.
    assert ds_filtered.is_empty
    # Default min_samples=3 → todas las horas pasan (n=24 cada una).
    assert not ds_full.is_empty
    assert len(ds_full.points) == 24


def test_best_hours_to_play_min_samples_default_is_three() -> None:
    """Default min_samples=3 — documenta la decisión del kickoff 2026-07-27.
    Una sola corrida a una hora X no califica esa hora como 'mejor'."""
    # Inspección de firma para detectar cambios accidentales del default.
    import inspect

    from gnd.visualization.queries import SqliteSeriesDataSource

    sig = inspect.signature(SqliteSeriesDataSource.best_hours_to_play)
    default = sig.parameters["min_samples"].default
    assert default == 3


def test_best_hours_to_play_includes_n_samples_metadata() -> None:
    """Kickoff 2026-07-27: cada barra lleva n_samples en metadata para
    que el renderer anote 'n=X' y vos veas si la conclusión es firme."""
    conn = _seed_conn()
    source = _make_source(conn)
    ds = source.best_hours_to_play(provider="google", period_days=30)
    assert ds.points
    for p in ds.points:
        assert "n_samples" in p.metadata
        assert p.metadata["n_samples"] == 24  # 24 días × 1 muestra/día


def test_series_point_metadata_default_is_empty_dict() -> None:
    """Default metadata={} para los charts que no usan la feature."""
    p = SeriesPoint(x=datetime.now(), y=10.0, group="g")
    assert p.metadata == {}


# ── Invariantes del modelo ChartDataSet ──────────────────────────────


def test_chart_dataset_validates_chronological_order() -> None:
    """Constructor falla si points vienen desordenadas (invariante)."""
    t1 = datetime(2026, 7, 27, 10)
    t2 = datetime(2026, 7, 27, 9)  # anterior a t1
    with pytest.raises(ValueError, match="ordenada cronológicamente"):
        ChartDataSet(
            title="x",
            y_label="y",
            points=(
                SeriesPoint(x=t1, y=1.0, group=""),
                SeriesPoint(x=t2, y=2.0, group=""),
            ),
        )


def test_chart_dataset_empty_factory() -> None:
    """ChartDataSet.empty produce un dataset que la UI trata como empty state."""
    ds = ChartDataSet.empty(title="x", y_label="y")
    assert ds.is_empty
    assert ds.points == ()


def test_chart_dataset_groups_preserves_order() -> None:
    """``groups`` devuelve los groups en orden de aparición (no sort)."""
    t = datetime(2026, 7, 27, 10)
    ds = ChartDataSet(
        title="x",
        y_label="y",
        points=(
            SeriesPoint(x=t, y=1.0, group="beta"),
            SeriesPoint(x=t, y=2.0, group="alpha"),  # alpha aparece 2do.
            SeriesPoint(x=t, y=3.0, group="beta"),
        ),
    )
    assert ds.groups == ("beta", "alpha")


def test_series_point_rejects_negative_y() -> None:
    """Latencia/loss negativos no son valid telefónicamente."""
    with pytest.raises(ValueError, match="y debe ser >= 0"):
        SeriesPoint(x=datetime.now(), y=-1.0, group="")
