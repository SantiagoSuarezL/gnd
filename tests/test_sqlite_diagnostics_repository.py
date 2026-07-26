"""Tests de SqliteDiagnosticsRepository - Fase 3.

Solo prueba save_run() (escritura). Las queries de lectura son
responsabilidad de analysis/ (Fase 4) y se verifican aqui via
SQL directo para no mezclar capas (ENGINEERING_PRINCIPLES.md §1.1).
"""

from datetime import datetime, timedelta

from gnd.database import SqliteDiagnosticsRepository
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult


def _make_probe(
    provider: str,
    target_ip: str = "1.2.3.4",
    avg_ms: float = 20.0,
) -> ProbeResult:
    return ProbeResult(
        target_name=f"target-{provider}",
        target_ip=target_ip,
        provider=provider,
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=avg_ms,
            min_ms=avg_ms - 5.0,
            max_ms=avg_ms + 5.0,
            jitter_ms=3.0,
            packet_loss_pct=0.0,
            samples=10,
        ),
        timestamp=datetime.now(),
    )


def _make_traceroute(provider: str) -> TracerouteResult:
    return TracerouteResult(
        target_provider=provider,
        hops=[
            TracerouteHop(
                hop_number=1,
                ip="1.2.3.4",
                hostname=None,
                rtt_ms=10.0,
                responded=True,
            ),
            TracerouteHop(
                hop_number=2,
                ip="5.6.7.8",
                hostname="example.com",
                rtt_ms=20.0,
                responded=True,
            ),
        ],
        culprit_hop_index=None,
    )


def _make_rec() -> Recommendation:
    return Recommendation(
        verdict="safe_to_play",
        headline="OK",
        explanation=["Todo bien", "Sin problemas detectados"],
        responsible_component="unknown",
        score=90,
    )


def _make_run(
    run_id: str,
    probes: list[ProbeResult],
    ags=None,
) -> DiagnosticRun:
    now = datetime.now()
    return DiagnosticRun(
        run_id=run_id,
        started_at=now,
        finished_at=now + timedelta(seconds=5),
        probes=probes,
        traceroutes=[_make_traceroute(probes[0].provider)],
        active_game_server=ags,
        recommendation=_make_rec(),
    )


def _repo_and_conn() -> tuple[SqliteDiagnosticsRepository, "object"]:
    """Returns (repo, shared_conn) — la conn vive en FakeDatabaseConnectionFactory.

    Tras Fase 9 fix (Regla de Oro 9.1), el repo pide conn por call via
    factory, no la guarda. La verificacion de los tests se hace sobre la
    conn compartida (envuelta en factory, single-thread, check_same_thread
    default True). Ejemplo:

        repo, conn = _repo_and_conn()
        repo.save_run(run)
        row = conn.execute("SELECT ...").fetchone()

    Este es el patron recomendado. El helper legacy ``_repo()`` abajo
    esta para no romper tests que ya usaban ``repo._conn``.
    """
    import sqlite3

    from gnd.domain.fakes import FakeDatabaseConnectionFactory

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    factory = FakeDatabaseConnectionFactory(conn)
    return SqliteDiagnosticsRepository(factory), conn


class _RepoView:
    """Compat legacy: expone ``._conn`` para tests pre-Fase-9.

    Tras el fix threading (Regla de Oro 9.1) el repo ya no guarda `_conn`
    (pide una nueva por call). Para no reescribir todos los asserts de
    los tests existentes, este wrapper sigue exponiendo `_conn` que
    apunta a la conn compartida del factory. Los tests nuevos deben
    preferir ``_repo_and_conn()`` (mas explicito).
    """

    def __init__(self, repo: SqliteDiagnosticsRepository, conn) -> None:
        self._repo = repo
        self._conn = conn

    def save_run(self, run: DiagnosticRun) -> None:
        self._repo.save_run(run)


def _repo() -> "_RepoView":
    repo, conn = _repo_and_conn()
    return _RepoView(repo, conn)


def test_save_run_inserts_diagnostic_run_row() -> None:
    """save_run escribe un row en diagnostic_runs."""
    repo = _repo()
    run = _make_run("run-1", [_make_probe("google", "8.8.8.8")])
    repo.save_run(run)

    row = repo._conn.execute(
        "SELECT * FROM diagnostic_runs WHERE run_id = ?", ("run-1",)
    ).fetchone()
    assert row is not None
    assert row["run_id"] == "run-1"
    assert row["recommendation_verdict"] == "safe_to_play"
    assert row["recommendation_score"] == 90
    assert row["responsible_component"] == "unknown"


def test_save_run_inserts_probe_results() -> None:
    """save_run escribe probes en probe_results con provider correcto."""
    repo = _repo()
    run = _make_run("run-probes", [_make_probe("cloudflare", "1.1.1.1")])
    repo.save_run(run)

    rows = repo._conn.execute(
        "SELECT * FROM probe_results WHERE run_id = ?", ("run-probes",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["provider"] == "cloudflare"
    assert rows[0]["target_ip"] == "1.1.1.1"
    assert rows[0]["outcome"] == "SUCCESS"
    assert rows[0]["avg_ms"] == 20.0
    assert rows[0]["packet_loss_pct"] == 0.0


def test_save_run_inserts_traceroute_results() -> None:
    """save_run serializa hops como JSON en traceroute_results."""
    repo = _repo()
    run = _make_run("run-tr", [_make_probe("google", "8.8.8.8")])
    repo.save_run(run)

    row = repo._conn.execute(
        "SELECT * FROM traceroute_results WHERE run_id = ?", ("run-tr",)
    ).fetchone()
    assert row is not None
    assert row["target_provider"] == "google"
    import json

    hops = json.loads(row["hops_json"])
    assert len(hops) == 2
    assert hops[0]["ip"] == "1.2.3.4"
    assert hops[1]["hostname"] == "example.com"


def test_save_run_inserts_active_game_server() -> None:
    """save_run escribe active_game_servers cuando esta presente."""
    from gnd.models.active_game_server import ActiveGameServerInfo

    repo = _repo()
    ags = ActiveGameServerInfo(
        ip="185.40.64.1",
        port=50000,
        protocol="udp",
        detected_via="process_connection_scan",
        process_name="League of Legends.exe",
    )
    run = _make_run(
        "run-ags",
        [_make_probe("riot_game_server", "185.40.64.1")],
        ags=ags,
    )
    repo.save_run(run)

    row = repo._conn.execute(
        "SELECT * FROM active_game_servers WHERE run_id = ?", ("run-ags",)
    ).fetchone()
    assert row is not None
    assert row["ip"] == "185.40.64.1"
    assert row["port"] == 50000
    assert row["protocol"] == "udp"
    assert row["detected_via"] == "process_connection_scan"


def test_save_run_no_ags_when_none() -> None:
    """Cuando active_game_server es None, no se inserta en active_game_servers."""
    repo = _repo()
    run = _make_run("run-no-ags", [_make_probe("google")])
    repo.save_run(run)

    row = repo._conn.execute(
        "SELECT COUNT(*) AS cnt FROM active_game_servers WHERE run_id = ?",
        ("run-no-ags",),
    ).fetchone()
    assert row["cnt"] == 0


def test_schema_version_table_exists() -> None:
    """schema_version existe para migraciones (TECHNICAL_SPEC.md §3)."""
    repo = _repo()
    row = repo._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    assert row is not None


def test_index_idx_probe_provider_time_exists() -> None:
    """Indice idx_probe_provider_time creado (TECHNICAL_SPEC.md §3)."""
    repo = _repo()
    row = repo._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='idx_probe_provider_time'"
    ).fetchone()
    assert row is not None


def test_multiple_save_are_idempotent() -> None:
    """INSERT OR REPLACE permite guardar el mismo run_id dos veces sin error."""
    repo = _repo()
    run = _make_run("idempotent", [_make_probe("quad9", "9.9.9.9")])
    repo.save_run(run)
    repo.save_run(run)  # segunda vez no debe fallar

    rows = repo._conn.execute(
        "SELECT COUNT(*) AS cnt FROM diagnostic_runs WHERE run_id = ?",
        ("idempotent",),
    ).fetchone()
    assert rows["cnt"] == 1


def test_separation_riot_public_vs_riot_game_server_via_sql() -> None:
    """TECHNICAL_SPEC.md §3: riot_public y riot_game_server como providers
    DISTINTOS en probe_results.

    Verificado via SQL directo (no a traves del repositorio, que no
    expone metodos de lectura — ENGINEERING_PRINCIPLES.md §1.1).
    """
    repo = _repo()

    run_public = _make_run(
        "run-public",
        [_make_probe("riot_public", "104.16.119.50", avg_ms=20.0)],
    )
    run_game = _make_run(
        "run-game",
        [_make_probe("riot_game_server", "185.40.64.1", avg_ms=100.0)],
    )

    repo.save_run(run_public)
    repo.save_run(run_game)

    # Query directa: riot_public SOLO contiene el run-public
    public_rows = repo._conn.execute(
        "SELECT run_id, provider, avg_ms FROM probe_results WHERE provider = 'riot_public'"
    ).fetchall()
    assert len(public_rows) == 1
    assert public_rows[0]["run_id"] == "run-public"
    assert public_rows[0]["avg_ms"] == 20.0

    # Query directa: riot_game_server SOLO contiene el run-game
    game_rows = repo._conn.execute(
        "SELECT run_id, provider, avg_ms FROM probe_results WHERE provider = 'riot_game_server'"
    ).fetchall()
    assert len(game_rows) == 1
    assert game_rows[0]["run_id"] == "run-game"
    assert game_rows[0]["avg_ms"] == 100.0

    # Verificar explicitamente que NO se mezclaron
    all_providers = [
        r["provider"]
        for r in repo._conn.execute(
            "SELECT DISTINCT provider FROM probe_results"
        ).fetchall()
    ]
    assert "riot_public" in all_providers
    assert "riot_game_server" in all_providers
    assert len(all_providers) == 2  # solo estos dos, no mezclados con google


def test_save_run_with_filtered_outcome_stores_null_stats() -> None:
    """Cuando outcome != SUCCESS, avg_ms/min/max/jitter/packet_loss/samples son NULL."""
    repo = _repo()

    filtered_probe = ProbeResult(
        target_name="target-filtered",
        target_ip="1.1.1.1",
        provider="cloudflare",
        outcome=ProbeOutcomeKind.FILTERED,
        stats=None,
        timestamp=datetime.now(),
    )
    run = _make_run("run-filtered", [filtered_probe])
    repo.save_run(run)

    row = repo._conn.execute(
        "SELECT * FROM probe_results WHERE run_id = ?", ("run-filtered",)
    ).fetchone()
    assert row["outcome"] == "FILTERED"
    assert row["avg_ms"] is None
    assert row["min_ms"] is None
    assert row["jitter_ms"] is None
    assert row["packet_loss_pct"] is None
    assert row["samples"] is None


def test_complete_run_persists_all_tables() -> None:
    """Un DiagnosticRun con probes + traceroutes + AGS ocupa las 4 tablas."""
    from gnd.models.active_game_server import ActiveGameServerInfo

    repo = _repo()
    ags = ActiveGameServerInfo(
        ip="185.40.64.1",
        port=50000,
        protocol="udp",
        detected_via="process_connection_scan",
        process_name="League of Legends.exe",
    )
    probes = [
        _make_probe("google", "8.8.8.8"),
        _make_probe("cloudflare", "1.1.1.1", avg_ms=12.0),
        _make_probe("riot_public", "104.16.119.50", avg_ms=35.0),
        _make_probe("riot_game_server", "185.40.64.1", avg_ms=55.0),
    ]
    run = _make_run("complete-run", probes, ags=ags)
    repo.save_run(run)

    # 4 tablas con datos
    assert (
        repo._conn.execute(
            "SELECT COUNT(*) AS cnt FROM diagnostic_runs WHERE run_id = 'complete-run'"
        ).fetchone()["cnt"]
        == 1
    )

    probe_count = repo._conn.execute(
        "SELECT COUNT(*) AS cnt FROM probe_results WHERE run_id = 'complete-run'"
    ).fetchone()["cnt"]
    assert probe_count == 4

    assert (
        repo._conn.execute(
            "SELECT COUNT(*) AS cnt FROM traceroute_results WHERE run_id = 'complete-run'"
        ).fetchone()["cnt"]
        == 1
    )

    assert (
        repo._conn.execute(
            "SELECT COUNT(*) AS cnt FROM active_game_servers WHERE run_id = 'complete-run'"
        ).fetchone()["cnt"]
        == 1
    )

    # Verificar separacion providers via SQL directo
    providers = [
        r["provider"]
        for r in repo._conn.execute(
            "SELECT DISTINCT provider FROM probe_results WHERE run_id = 'complete-run'"
        ).fetchall()
    ]
    assert set(providers) == {"google", "cloudflare", "riot_public", "riot_game_server"}
