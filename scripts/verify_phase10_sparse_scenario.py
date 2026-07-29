"""Simula el caso real de Fase 10 con DB casi vacía (kickoff 2026-07-27).

Caso: el usuario ejecutó ~10 corridas manuales a horas distintas del
día en las últimas 2 semanas. ¿Qué pasa con el chart de mejores horas?

Resultado esperado: con n<3 por hora, el chart muestra empty state
(Regla 10.4) en lugar de barras engañosas con n=1.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from gnd.database.sqlite_connection_factory import SqliteConnectionFactory  # noqa: E402
from gnd.visualization import (  # noqa: E402
    SqliteSeriesDataSource,
    all_renderers,
)


def _seed_sparse(conn, runs: list[tuple[str, datetime, float]]) -> None:
    for run_id, ts, latency in runs:
        for provider, offset in (
            ("google", 0.0),
            ("cloudflare", -1.0),
            ("quad9", +1.0),
            ("riot_public", +8.0),
        ):
            conn.execute(
                """INSERT INTO probe_results
                   (run_id, target_name, target_ip, provider, outcome,
                    avg_ms, min_ms, max_ms, jitter_ms, packet_loss_pct,
                    samples, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"{run_id}-{provider}",
                    f"t-{provider}",
                    "1.2.3.4",
                    provider,
                    "SUCCESS",
                    latency + offset,
                    (latency + offset) * 0.7,
                    (latency + offset) * 1.3,
                    3.0,
                    0.0,
                    8,
                    ts.isoformat(),
                ),
            )
    conn.commit()


def main(out_dir: str = ".") -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Escenario: 10 corridas manuales del usuario repartidas en horas
    # distintas del día (3 a las 22:00, 2 a las 14:00, 1 a las 02:00,
    # 2 a las 18:00, 2 a las 03:00). Algunas horas tienen n>=3, otras
    # quedan por debajo del umbral.
    base = datetime(2026, 7, 27, 22, 0, 0)
    runs = []
    run_id = 0

    def _add(ts: datetime, latency: float) -> None:
        nonlocal run_id
        runs.append((f"run-{run_id}", ts, latency))
        run_id += 1

    _add(base - timedelta(days=2), 14.0)
    _add(base - timedelta(days=3), 13.5)
    _add(base - timedelta(days=5), 15.0)
    _add(base - timedelta(days=7), 14.2)
    _add(base - timedelta(days=8), 13.8)

    _add(base - timedelta(days=2, hours=8), 16.0)  # 14:00
    _add(base - timedelta(days=4, hours=8), 17.0)  # 14:00

    _add(base - timedelta(days=4, hours=20), 21.0)  # 02:00 (1 sola muestra)

    _add(base - timedelta(days=1, hours=4), 35.0)  # 18:00 (congestión)
    _add(base - timedelta(days=2, hours=4), 38.0)  # 18:00

    _add(base - timedelta(days=6, hours=19), 22.0)  # 03:00 (1 sola)

    db_path = out / "sparse.db"
    factory = SqliteConnectionFactory(str(db_path))
    conn = factory.create_connection()
    _seed_sparse(conn, runs)

    source = SqliteSeriesDataSource(factory, now=base)
    ds = source.best_hours_to_play(provider="riot_public", period_days=30)

    distinct_hours = {r[1].hour for r in runs}
    print(f"Escenario: {len(runs)} corridas en {len(distinct_hours)} horas distintas")
    print(
        f"best_hours_to_play puntos: {len(ds.points)} "
        "(esperado: solo horas con n>=3)"
    )
    print(f"is_empty: {ds.is_empty}")
    if not ds.is_empty:
        print("Horas mostradas (n=count de runs a esa hora):")
        from collections import Counter

        hour_counts = Counter(r[1].hour for r in runs)
        for p in ds.points:
            n_at_hour = hour_counts[int(p.group)]
            print(f"  hora={p.group}  latency_media={p.y:.1f}ms  n={n_at_hour}")

    renderers = all_renderers()
    fig = renderers["best_hours_to_play"](ds)
    png_path = out / "5_best_hours_to_play_SPARSE.png"
    fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"PNG: {png_path} ({png_path.stat().st_size / 1024:.1f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
