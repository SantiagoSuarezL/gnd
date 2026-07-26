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
"""

SCHEMA_VERSION = 2


def ensure_schema(conn) -> None:
    """Crea las tablas si no existen y aplica migraciones pendientes."""
    conn.executescript(SCHEMA_SQL)
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cur.fetchone()
    current_version = row[0] if row[0] is not None else 0

    if current_version < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, __import__("datetime").datetime.now().isoformat()),
        )
    conn.commit()
