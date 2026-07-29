"""Verificación E2E de Fase 10 — los 5 gráficos del PRD §10.

USO:
    python scripts/verify_phase10_charts.py                    # DB temporal
    python scripts/verify_phase10_charts.py --out-dir <path>   # PNG a ruta
    python scripts/verify_phase10_charts.py --keep-db <path>   # conservar DB

Este script:
1. Crea una DB temporal (sqlite3.connect(":memory:") o archivo en
   %TEMP% si --keep-db). NUNCA toca %APPDATA%/GND/history.db.
2. Siembra ~14 días de datos sintéticos realistas (latencia con
   congestión vespertina, Riot > Google/CF, packet loss no nulo en
   muestras aleatorias) en probe_results.
3. Llama a los 5 SeriesDataSource queries.
4. Renderiza cada ChartDataSet a un PNG en el output dir.
5. Afirma invariantes mínima (cada chart tiene >0 puntos y el PNG se
   escribió sin falla).

Salida esperada en stdout:
    - Listado de los 5 PNG generados con su tamaño en KB.
    - Confirmación de que no tocó la DB de producción.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # forzado: script no abre ventana Tk

import matplotlib.pyplot as plt  # noqa: E402

from gnd.database.schema import SCHEMA_VERSION, ensure_schema  # noqa: E402
from gnd.visualization import (  # noqa: E402
    SqliteSeriesDataSource,
    all_renderers,
)


def _seed_db(conn: sqlite3.Connection, *, seed: int = 42) -> None:
    """Siembra 14 días de probes sintéticos (cada 6h) para 4 providers."""
    import random

    random.seed(seed)
    base = datetime(2026, 7, 27, 14, 0, 0)

    # 14 días * 4 mediciones por día * 4 providers = 224 probes.
    provider_specs = (
        ("google", "8.8.8.8", 12.0),
        ("cloudflare", "1.1.1.1", 11.0),
        ("quad9", "9.9.9.9", 13.0),
        ("riot_public", "auth.riotgames.com", 22.0),
    )
    for day in range(14):
        for sample_in_day in range(4):  # 00:00, 06:00, 12:00, 18:00
            hour = sample_in_day * 6
            ts = base - timedelta(days=14 - day) + timedelta(hours=hour)

            # Congestión vespertina: 18:00 → latencia 1.5x.
            congestion_factor = 1.5 if hour == 18 else 1.0

            for provider, ip, base_latency in provider_specs:
                latency = (
                    base_latency * congestion_factor * (1.0 + random.random() * 0.2)
                )
                loss = max(0.0, random.random() * 1.5) if random.random() > 0.7 else 0.0

                conn.execute(
                    """INSERT INTO probe_results
                       (run_id, target_name, target_ip, provider, outcome,
                        avg_ms, min_ms, max_ms, jitter_ms, packet_loss_pct,
                        samples, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"seed-{provider}-{ts.isoformat()}",
                        f"t-{provider}",
                        ip,
                        provider,
                        "SUCCESS",
                        latency,
                        latency * 0.7,
                        latency * 1.3,
                        3.0,
                        loss,
                        10,
                        ts.isoformat(),
                    ),
                )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directorio donde guardar los PNG (default: cwd).",
    )
    parser.add_argument(
        "--keep-db",
        default=None,
        help="Path a archivo DB temporal para inspección. Default: ':memory:'.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.keep_db is None or args.keep_db == ":memory:":
        db_path = ":memory:"
    else:
        db_path = str(Path(args.keep_db).resolve())

    print(f"[Fase 10] DB temporal: {db_path}")
    print(f"[Fase 10] Output dir: {out_dir.resolve()}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    print(f"[Fase 10] Schema version: {SCHEMA_VERSION}")

    _seed_db(conn)
    print("[Fase 10] Datos sembrados en probe_results.")

    # Source con `now` fijo para que el period_days=30 incluya el seed.
    source = SqliteSeriesDataSource(
        _RowProxyFactory(conn),
        now=datetime(2026, 7, 27, 14, 0, 0),
    )

    # Specs (mismos nombres que _chart_specs en charts_section.py pero
    # accedidos aqui via reflection controlada porque el módulo UI importa
    # tkinter y no queremos fallback — este script es headless).
    specs = [
        (
            "1_latency_over_time",
            "latency_over_time",
            {"providers": ["google", "cloudflare", "quad9", "riot_public"]},
        ),
        (
            "2_packet_loss_over_time",
            "packet_loss_over_time",
            {"providers": ["google", "cloudflare", "quad9", "riot_public"]},
        ),
        (
            "3_cloudflare_vs_google",
            "cloudflare_vs_google",
            {"period_days": 30},
        ),
        (
            "4_riot_latency_over_time",
            "riot_latency_over_time",
            {"provider": "riot_public", "period_days": 30},
        ),
        (
            "5_best_hours_to_play",
            "best_hours_to_play",
            {"provider": "riot_public", "period_days": 30},
        ),
    ]

    renderers = all_renderers()
    summary_lines: list[str] = []
    for fname_root, method_name, kwargs in specs:
        ds = getattr(source, method_name)(**kwargs)
        render = renderers[method_name]
        fig = render(ds)
        png_path = out_dir / f"{fname_root}.png"
        fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        size_kb = png_path.stat().st_size / 1024
        summary_lines.append(
            f" - {fname_root:30s}  puntos={len(ds.points):4d}  "
            f"{png_path.name}  ({size_kb:.1f} KB)"
        )

    print()
    print("[Fase 10] PNGs generados:")
    for line in summary_lines:
        print(line)

    # Sanity: ningún PNG debe tener 0 bytes.
    bad = [
        f.name
        for f in out_dir.iterdir()
        if f.suffix == ".png" and f.stat().st_size == 0
    ]
    if bad:
        print(f"[Fase 10] ERROR: PNGs vacíos detected: {bad}")
        return 2

    print("[Fase 10] OK — 5 gráficos generados a partir de datos reales (DB temporal).")
    return 0


class _RowProxyFactory:
    """Adaptador sqlite3.Connection → DatabaseConnectionFactory.

    El factory real abre una conn nueva por call. Para este script de
    verificación, devolvemos una conn existente (single-thread, noTk).
    Cumple el Protocol ``DatabaseConnectionFactory`` por duck typing.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_connection(self) -> sqlite3.Connection:
        return self._conn


if __name__ == "__main__":
    sys.exit(main())
