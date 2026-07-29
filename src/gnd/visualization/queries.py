"""Implementación SQLite de ``SeriesDataSource`` (Fase 10).

EP §3 (DI total): recibe ``DatabaseConnectionFactory`` para pedir una
``sqlite3.Connection`` nueva por call (Regla de Oro 9.1: nunca compartir
conn entre hilos). Cada método abre una conn, corre la query, cierra.

ARQUITECTURA §3 para ``visualization/``: "Generación de gráficos a partir
de datos ya calculados. No calcula ni interpreta datos."
Las queries aquí son lecturas agregadas puras — no interpretan anomalías
ni computan baselines (eso ya está en ``analysis/``). Solo arman series
de puntos con timestamp y valor.

Tabla con todos los datos de latencia: ``probe_results`` (schema v1:
target_name, target_ip, provider, outcome, avg_ms, packet_loss_pct,
samples, timestamp). Schema v2 (Fase 8) añadió ``monitoring_*`` pero los
5 gráficos del PRD §10 operan sobre series históricas por **provider**,
no por hop — los probe_results son el grano correcto.

Ventana temporal: ``period_days`` (default 30, igual que ``compute_baseline``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from gnd.domain.ports.database import DatabaseConnectionFactory
from gnd.visualization.models import ChartDataSet, SeriesPoint


def _parse_ts(s: str) -> datetime:
    """Parsea ISO-format timestamp. Probe results guardan ``isoformat()``."""
    return datetime.fromisoformat(s)


def _cutoff(period_days: int, *, now: datetime | None) -> str:
    """Computa el cutoff ISO string `period_days` atrás desde `now`."""
    ref = now or datetime.now()
    return (ref - timedelta(days=period_days)).isoformat()


class SqliteSeriesDataSource:
    """Implementación de ``SeriesDataSource`` contra la SQLite real.

    El caller (normalmente el ChartsSection en el main thread) pide una
    ``create_connection()`` de la factory, ejecuta la query, y cierra.
    Nunca comparte conn entre hilos (Regla de Oro 9.1).

    Si el período o los providers devuelven 0 rows, el método devuelve
    ``ChartDataSet.empty(...)`` — la decisión de cómo mostrarlo es de la UI.
    """

    def __init__(
        self,
        db_factory: DatabaseConnectionFactory,
        *,
        now: datetime | None = None,
    ) -> None:
        """
        Args:
            db_factory: provee ``sqlite3.Connection`` por call.
            now: inyectable para tests deterministas (EP §4). En prod None
                → usa ``datetime.now()``. Como los probe_results se guardan
                con ``datetime.now().isoformat()``, el cutoff calculado con
                ``now`` inyectado debe usar la misma zona horaria (UTC offset
                None = naive local time, igual que isoformat() del save_run).
        """
        self._factory = db_factory
        self._now = now

    # ── Query helpers ──────────────────────────────────────────────

    def _fetch(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> list[sqlite3.Row]:
        """Pide una conn, corre la query y devuelve rows.

        NO cierra la conn — la factory real (SqliteConnectionFactory) crea
        una conn nueva por call y el GC la libera; cerrar acá rompería
        factories in-memory (tests, este script de verificación) que
        comparten una sola conn. La factory real marca check_same_thread
        default True, así que no hay riesgo de reusar conn entre hilos.
        """
        conn = self._factory.create_connection()
        cur = conn.execute(sql, params)
        return list(cur.fetchall())

    # ── SeriesDataSource Protocol ──────────────────────────────────

    def latency_over_time(
        self,
        *,
        providers: list[str],
        period_days: int = 30,
    ) -> ChartDataSet:
        """Serie de latencia avg_ms en el tiempo, agrupada por provider.

        Solo probes con outcome='SUCCESS' (Regla 2: FILTERED no aporta
        latencia, no se grafica). Un punto por probe (no por run) — si el
        run tuvo 10 samples contra google, eso es 1 row en probe_results
        con avg_ms=media de esos 10.
        """
        if not providers:
            return ChartDataSet.empty(
                title="Latencia a lo largo del tiempo",
                y_label="Latencia avg (ms)",
            )

        placeholders = ",".join("?" * len(providers))
        cutoff = _cutoff(period_days, now=self._now)
        sql = f"""
            SELECT provider, avg_ms, timestamp
            FROM probe_results
            WHERE outcome = 'SUCCESS'
              AND avg_ms IS NOT NULL
              AND provider IN ({placeholders})
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """
        rows = self._fetch(sql, (*providers, cutoff))

        points = tuple(
            SeriesPoint(
                x=_parse_ts(r["timestamp"]),
                y=float(r["avg_ms"]),
                group=str(r["provider"]),
            )
            for r in rows
        )
        return ChartDataSet(
            title="Latencia a lo largo del tiempo",
            y_label="Latencia avg (ms)",
            points=points,
        )

    def packet_loss_over_time(
        self,
        *,
        providers: list[str],
        period_days: int = 30,
    ) -> ChartDataSet:
        """Serie de packet_loss_pct en el tiempo, agrupada por provider.

        Incluye SUCCESS y FILTERED (un provider que pierde paquetes es
        signal útil). Excluye UNREACHABLE/TIMEOUT (no hay valor de loss).
        """
        if not providers:
            return ChartDataSet.empty(
                title="Pérdida de paquetes histórica",
                y_label="Packet loss (%)",
            )

        placeholders = ",".join("?" * len(providers))
        cutoff = _cutoff(period_days, now=self._now)
        sql = f"""
            SELECT provider, packet_loss_pct, timestamp
            FROM probe_results
            WHERE packet_loss_pct IS NOT NULL
              AND provider IN ({placeholders})
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """
        rows = self._fetch(sql, (*providers, cutoff))

        points = tuple(
            SeriesPoint(
                x=_parse_ts(r["timestamp"]),
                y=float(r["packet_loss_pct"]),
                group=str(r["provider"]),
            )
            for r in rows
        )
        return ChartDataSet(
            title="Pérdida de paquetes histórica",
            y_label="Packet loss (%)",
            points=points,
        )

    def cloudflare_vs_google(
        self,
        *,
        period_days: int = 30,
    ) -> ChartDataSet:
        """Comparativa Cloudflare vs Google: latencia avg_ms en el tiempo.

        DNs públicos representativos de la "salud Internet general"
        (TECHNICAL_SPEC.md §4.2 componente 4). Solo SUCCESS.
        """
        cutoff = _cutoff(period_days, now=self._now)
        sql = """
            SELECT provider, avg_ms, timestamp
            FROM probe_results
            WHERE outcome = 'SUCCESS'
              AND avg_ms IS NOT NULL
              AND provider IN ('cloudflare', 'google')
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """
        rows = self._fetch(sql, (cutoff,))

        points = tuple(
            SeriesPoint(
                x=_parse_ts(r["timestamp"]),
                y=float(r["avg_ms"]),
                group=str(r["provider"]),
            )
            for r in rows
        )
        return ChartDataSet(
            title="Cloudflare vs Google — Latencia",
            y_label="Latencia avg (ms)",
            points=points,
        )

    def riot_latency_over_time(
        self,
        *,
        provider: str = "riot_public",
        period_days: int = 30,
    ) -> ChartDataSet:
        """Serie histórica de latencia Riot (default: riot_public).

        PRD §3 Riot 3-capas: ``riot_public`` (proxy de infraestructura
        Riot) o ``riot_game_server`` (IP real del server activo) — el
        caller elige. Default ``riot_public`` porque ``riot_game_server``
        está sujeto a partidas activas y suele tener samples escasos
        (instrinsic limitation v1, ver tech_stack.md #11).
        """
        if not provider:
            return ChartDataSet.empty(
                title="Latencia Riot histórica",
                y_label="Latencia avg (ms)",
            )

        cutoff = _cutoff(period_days, now=self._now)
        sql = """
            SELECT avg_ms, timestamp
            FROM probe_results
            WHERE outcome = 'SUCCESS'
              AND avg_ms IS NOT NULL
              AND provider = ?
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """
        rows = self._fetch(sql, (provider, cutoff))

        points = tuple(
            SeriesPoint(
                x=_parse_ts(r["timestamp"]),
                y=float(r["avg_ms"]),
                group=provider,
            )
            for r in rows
        )
        return ChartDataSet(
            title=f"Latencia Riot histórica ({provider})",
            y_label="Latencia avg (ms)",
            points=points,
        )

    def best_hours_to_play(
        self,
        *,
        provider: str = "riot_public",
        period_days: int = 30,
        min_samples: int = 3,
    ) -> ChartDataSet:
        """Mejores horas para jugar: latencia media agregada por hora.

        Agrupa por ``strftime('%H', timestamp)`` (hora 00-23) y promedia
        avg_ms. El gráfico resultante es un bar chart por hora; el menor
        = mejor hora. PRD user story #4: "ver mi historial de latencia
        por hora/día".

        Args:
            min_samples: umbral de muestras por hora (default 3). Horas con
                menos muestras se excluyen porque la "mejor hora" con n=1
                no es representativa — una sola medición anómala (microondas
                prendido, hora pico temporal) se confunde con "señal".
                Default 3 asume ~30 días de uso con 1 corrida diaria → 3-5
                muestras por hora, suficiente para comparar.

        El ``group`` de cada point es la hora (string "00" a "23") para
        que el renderer lo use como etiqueta de eje X, no como serie.
        """
        if not provider:
            return ChartDataSet.empty(
                title="Mejores horas para jugar",
                y_label="Latencia media (ms)",
                x_label="Hora del día",
            )

        cutoff = _cutoff(period_days, now=self._now)
        sql = """
            SELECT strftime('%H', timestamp) AS hour,
                   AVG(avg_ms) AS avg_latency,
                   COUNT(*) AS n_samples
            FROM probe_results
            WHERE outcome = 'SUCCESS'
              AND avg_ms IS NOT NULL
              AND provider = ?
              AND timestamp >= ?
            GROUP BY strftime('%H', timestamp)
            HAVING COUNT(*) >= ?
            ORDER BY hour ASC
        """
        rows = self._fetch(sql, (provider, cutoff, min_samples))

        points = tuple(
            SeriesPoint(
                # Usamos datetime artificial (epoch) para que el tipo sea
                # consistente con los demás ChartDataSet; el group lleva
                # la hora como string para el eje X.
                x=datetime.fromisoformat(f"2000-01-01T{r['hour']}:00:00"),
                y=float(r["avg_latency"]),
                group=str(r["hour"]),
                metadata={"n_samples": int(r["n_samples"])},
            )
            for r in rows
        )
        return ChartDataSet(
            title=f"Mejores horas para jugar ({provider})",
            y_label="Latencia media (ms)",
            points=points,
            x_label="Hora del día",
        )
