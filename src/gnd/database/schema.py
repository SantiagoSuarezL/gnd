"""Esquema SQLite y migraciones.

TECHNICAL_SPEC.md §3. Implementa las tablas diagnostic_runs, probe_results,
traceroute_results, active_game_servers y el índice idx_probe_provider_time.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnostic_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    recommendation_verdict TEXT NOT NULL,
    recommendation_headline TEXT NOT NULL,
    recommendation_explanation TEXT NOT NULL,
    recommendation_score INTEGER NOT NULL,
    responsible_component TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probe_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    target_name TEXT NOT NULL,
    target_ip TEXT NOT NULL,
    provider TEXT NOT NULL,
    outcome TEXT NOT NULL,
    avg_ms REAL,
    min_ms REAL,
    max_ms REAL,
    jitter_ms REAL,
    packet_loss_pct REAL,
    samples INTEGER,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traceroute_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    target_provider TEXT NOT NULL,
    culprit_hop_index INTEGER,
    hops_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS active_game_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    ip TEXT NOT NULL,
    port INTEGER NOT NULL,
    protocol TEXT NOT NULL,
    detected_via TEXT NOT NULL,
    process_name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_probe_provider_time
    ON probe_results(provider, timestamp);

CREATE TABLE IF NOT EXISTS monitoring_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    target_ip TEXT NOT NULL,
    target_provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    interval_s REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mon_sessions_run
    ON monitoring_sessions(run_id);

CREATE TABLE IF NOT EXISTS monitoring_hops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES monitoring_sessions(session_id),
    hop_number INTEGER NOT NULL,
    ip TEXT,
    hostname TEXT,
    best_ms REAL,
    worst_ms REAL,
    avg_ms REAL,
    jitter_ms REAL NOT NULL,
    loss_pct REAL NOT NULL,
    samples INTEGER NOT NULL,
    success_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mon_hops_session
    ON monitoring_hops(session_id);

-- Fase 12a.2: mediciones de tiempo de resolucion DNS (TECHNICAL_SPEC §8).
-- Tabla nueva independiente (Schema v2 retro-compat: solo ANADIR, Protocolo 19).
CREATE TABLE IF NOT EXISTS dns_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    hostname TEXT NOT NULL,
    resolved_ip TEXT,
    outcome TEXT NOT NULL,
    elapsed_ms REAL,
    family TEXT NOT NULL,
    error TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dns_results_run
    ON dns_results(run_id);
CREATE INDEX IF NOT EXISTS idx_dns_results_host
    ON dns_results(hostname, timestamp);

-- Fase 12a.3: snapshots de interfaz de red (TECHNICAL_SPEC §8 + PRD §7).
-- Tabla nueva (Schema v2 retro-compat: solo ANADIR, Protocolo 19).
-- Nullable cols: wifi_ssid / wifi_signal_dbm cuando type != WIFI.
-- Una fila por run (la etapa inspecciona la default-route iface).
CREATE TABLE IF NOT EXISTS interface_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    type TEXT NOT NULL,  -- WIFI | ETHERNET | OTHER
    name TEXT NOT NULL,
    is_default_route INTEGER NOT NULL,  -- boolean 0/1
    wifi_ssid TEXT,
    wifi_signal_dbm REAL,
    error TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interface_snapshots_run
    ON interface_snapshots(run_id);
"""

SCHEMA_VERSION = 3


def _has_column(conn, table: str, column: str) -> bool:
    """True si `table` ya tiene `column` (checkeo idempotente para ADD COLUMN).

    SQLite no soporta `ADD COLUMN IF NOT EXISTS`; este check evita el
    OperationalError 'duplicate column name' al llamar ensure_schema
    sobre una DB que ya tiene la columna (escenario tipico: ensure_schema
    invocado varias veces en la misma DB en runtime).
    """
    cur = conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
    for row in cur.fetchall():
        # row schema: (cid, name, type, notnull, dflt_value, pk)
        if row[1] == column:
            return True
    return False


def _migrate_v2_to_v3(conn) -> None:
    """Migracion v2 -> v3: anade `family TEXT NOT NULL DEFAULT 'ipv4'` a
    `probe_results` y `traceroute_results`.

    Protocolo 19 (Schema v2 retro-compat) exige 'solo ANADIR, nunca
    modificar existentes' — aqui excepcionamos porque la columna `family`
    es necesaria para distinguir probes IPv4 de IPv6 (Fase 12a.4). ALTER
    TABLE ADD COLUMN es retro-compatible: las rows existentes reciben el
    DEFAULT 'ipv4' (no hay perdida de informacion — runs pre-IPv6 eran
    todos IPv4 por definicion).

    Idempotente: usa PRAGMA table_info para no reintentar ADD COLUMN sobre
    una DB ya migrada (SQLite lanza OperationalError 'duplicate column
    name' en caso contrario).
    """
    if not _has_column(conn, "probe_results", "family"):
        conn.execute(
            "ALTER TABLE probe_results ADD COLUMN family TEXT NOT NULL DEFAULT 'ipv4'"
        )
    if not _has_column(conn, "traceroute_results", "family"):
        conn.execute(
            "ALTER TABLE traceroute_results "
            "ADD COLUMN family TEXT NOT NULL DEFAULT 'ipv4'"
        )


def ensure_schema(conn) -> None:
    """Crea las tablas si no existen y aplica migraciones pendientes."""
    conn.executescript(SCHEMA_SQL)
    # Migracion v2 -> v3: columnas `family` en probe_results y
    # traceroute_results. Idempotente (PRAGMA table_info check).
    _migrate_v2_to_v3(conn)
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cur.fetchone()
    current_version = row[0] if row[0] is not None else 0

    if current_version < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, __import__("datetime").datetime.now().isoformat()),
        )
    conn.commit()
