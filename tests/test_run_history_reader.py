"""Tests del FakeRunHistoryReader y SqliteRunHistoryReader (Fase 12b.3).

FakeRunHistoryReader: cubre filtrado half-open [start, end), orden
ASC por started_at, invariante end >= start, API ``add_run`` incremental.

SqliteRunHistoryReader: cubre roundtrip con ``SqliteDiagnosticsRepository.save_run``
(idempotencia), rango half-open, multi-run multi-provider, secciones
opcionales (DNS, interfaz, game server) reconstruidas completas,
invariante stats=None cuando outcome != SUCCESS, orden ASC por started_at.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from gnd.database import SqliteDiagnosticsRepository, SqliteRunHistoryReader
from gnd.domain.fakes import FakeDatabaseConnectionFactory, FakeRunHistoryReader
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.dns_measurement import DnsOutcome, DnsResolution
from gnd.models.latency_stats import LatencyStats
from gnd.models.network_interface import InterfaceType, NetworkInterfaceSnapshot
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult

# ── Factories ──────────────────────────────────────────────────────────


def _probe(
    *,
    provider: str = "google",
    outcome: ProbeOutcomeKind = ProbeOutcomeKind.SUCCESS,
    family: str = "ipv4",
) -> ProbeResult:
    return ProbeResult(
        target_name=f"target-{provider}",
        target_ip="8.8.8.8",
        provider=provider,
        outcome=outcome,
        stats=(
            LatencyStats(
                avg_ms=20.0,
                min_ms=15.0,
                max_ms=25.0,
                jitter_ms=3.0,
                packet_loss_pct=0.0,
                samples=8,
            )
            if outcome is ProbeOutcomeKind.SUCCESS
            else None
        ),
        timestamp=datetime.now(),
        family=family,
    )


def _traceroute(*, provider: str = "google") -> TracerouteResult:
    return TracerouteResult(
        target_provider=provider,
        hops=[
            TracerouteHop(
                hop_number=1, ip="1.1.1.1", hostname=None, rtt_ms=5.0, responded=True
            ),
            TracerouteHop(
                hop_number=2,
                ip="8.8.8.8",
                hostname="dns.google",
                rtt_ms=15.0,
                responded=True,
            ),
        ],
        culprit_hop_index=None,
    )


def _rec(*, score: int = 90) -> Recommendation:
    return Recommendation(
        verdict="safe_to_play",
        headline="OK",
        explanation=["sin issues"],
        responsible_component="unknown",
        score=score,
    )


def _run(
    *,
    started: datetime,
    run_id: str = "r-x",
    probes: list[ProbeResult] | None = None,
    traceroutes: list[TracerouteResult] | None = None,
    dns: tuple[DnsResolution, ...] = (),
    iface: NetworkInterfaceSnapshot | None = None,
    ags: ActiveGameServerInfo | None = None,
    score: int = 90,
) -> DiagnosticRun:
    return DiagnosticRun(
        run_id=run_id,
        started_at=started,
        finished_at=started + timedelta(seconds=5),
        probes=probes if probes is not None else [_probe()],
        traceroutes=traceroutes if traceroutes is not None else [_traceroute()],
        active_game_server=ags,
        recommendation=_rec(score=score),
        dns_results=dns,
        interface_snapshot=iface,
    )


def _reader_and_repo() -> tuple[SqliteRunHistoryReader, SqliteDiagnosticsRepository]:
    """Crea (reader, writer) sobre la misma DB in-memory compartida."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    factory = FakeDatabaseConnectionFactory(conn)
    # El reader invoca ensure_schema al constructarse (crea las tablas).
    reader = SqliteRunHistoryReader(factory)
    return reader, SqliteDiagnosticsRepository(factory)


# ── FakeRunHistoryReader ──────────────────────────────────────────────


def test_fake_reader_filters_half_open_range() -> None:
    base = datetime(2026, 1, 10)
    run_in = _run(started=base, run_id="in")
    run_out = _run(started=base + timedelta(days=10), run_id="out")
    reader = FakeRunHistoryReader(runs=[run_in, run_out])
    out = reader.get_runs_in_period(
        start=base - timedelta(days=1), end=base + timedelta(days=1)
    )
    assert out == [run_in]


def test_fake_reader_returns_ordered_by_started_at_asc() -> None:
    base = datetime(2026, 1, 10)
    early = _run(started=base, run_id="early")
    late = _run(started=base + timedelta(hours=2), run_id="late")
    # Pasamos en orden invertido para confirmar que sortea ASC.
    reader = FakeRunHistoryReader(runs=[late, early])
    out = reader.get_runs_in_period(
        start=base - timedelta(days=1), end=base + timedelta(days=1)
    )
    assert out == [early, late]


def test_fake_reader_rejects_end_before_start() -> None:
    now = datetime.now()
    reader = FakeRunHistoryReader()
    with pytest.raises(ValueError, match="end no puede ser anterior a start"):
        reader.get_runs_in_period(start=now, end=now - timedelta(seconds=1))


def test_fake_reader_add_run_incremental() -> None:
    now = datetime.now()
    reader = FakeRunHistoryReader(runs=[])
    assert (
        reader.get_runs_in_period(now - timedelta(days=1), now + timedelta(days=1))
        == []
    )
    reader.add_run(_run(started=now, run_id="r-1"))
    out = reader.get_runs_in_period(now - timedelta(days=1), now + timedelta(days=1))
    assert len(out) == 1
    assert out[0].run_id == "r-1"


def test_fake_reader_compliance_with_protocol() -> None:
    from gnd.domain.ports.run_history_reader import RunHistoryReader

    reader = FakeRunHistoryReader()
    assert isinstance(reader, RunHistoryReader)  # runtime_checkable


# ── SqliteRunHistoryReader ────────────────────────────────────────────


def test_sqlite_reader_empty_db_returns_empty_list() -> None:
    reader, _repo = _reader_and_repo()
    now = datetime.now()
    out = reader.get_runs_in_period(now - timedelta(days=7), now + timedelta(days=1))
    assert out == []


def test_sqlite_reader_roundtrip_single_run() -> None:
    reader, repo = _reader_and_repo()
    started = datetime(2026, 3, 15, 14, 0, 0)
    original = _run(started=started, run_id="r-1")
    repo.save_run(original)

    out = reader.get_runs_in_period(
        started - timedelta(days=1), started + timedelta(days=1)
    )
    assert len(out) == 1
    r = out[0]
    assert r.run_id == "r-1"
    assert r.started_at == started
    assert r.recommendation.verdict == "safe_to_play"
    assert r.recommendation.score == 90
    assert len(r.probes) == 1
    assert r.probes[0].provider == "google"
    assert r.probes[0].outcome is ProbeOutcomeKind.SUCCESS
    assert r.probes[0].stats is not None
    assert r.probes[0].stats.avg_ms == 20.0
    assert len(r.traceroutes) == 1
    assert r.traceroutes[0].target_provider == "google"
    assert len(r.traceroutes[0].hops) == 2


def test_sqlite_reader_half_open_range_excludes_boundary() -> None:
    reader, repo = _reader_and_repo()
    base = datetime(2026, 3, 15, 14, 0, 0)
    run_at_end = _run(started=base, run_id="at-end")
    run_after = _run(started=base + timedelta(hours=1), run_id="after")
    repo.save_run(run_at_end)
    repo.save_run(run_after)

    # End == base (excluido por half-open). After está fuera del rango
    # también (started > end).
    out = reader.get_runs_in_period(start=base - timedelta(days=1), end=base)
    assert out == []
    # Rango ajustado: incluye at-end pero no after.
    out = reader.get_runs_in_period(
        start=base - timedelta(days=1), end=base + timedelta(minutes=1)
    )
    assert len(out) == 1
    assert out[0].run_id == "at-end"


def test_sqlite_reader_preserves_chronological_order() -> None:
    reader, repo = _reader_and_repo()
    base = datetime(2026, 3, 15, 14, 0, 0)
    middle = _run(started=base + timedelta(hours=1), run_id="middle")
    early = _run(started=base, run_id="early")
    late = _run(started=base + timedelta(hours=2), run_id="late")
    # Persistir en orden shuffled.
    repo.save_run(late)
    repo.save_run(early)
    repo.save_run(middle)

    out = reader.get_runs_in_period(
        start=base - timedelta(days=1), end=base + timedelta(days=1)
    )
    assert [r.run_id for r in out] == ["early", "middle", "late"]


def test_sqlite_reader_reconstructs_optional_game_server_dns_interface() -> None:
    reader, repo = _reader_and_repo()
    started = datetime(2026, 3, 15, 14, 0, 0)
    run = _run(
        started=started,
        run_id="r-full",
        ags=ActiveGameServerInfo(
            ip="10.20.30.40",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="League of Legends.exe",
        ),
        dns=(
            DnsResolution(
                hostname="auth.riotgames.com",
                resolved_ip="1.2.3.4",
                outcome=DnsOutcome.SUCCESS,
                elapsed_ms=42.0,
                family="ipv4",
                error=None,
            ),
        ),
        iface=NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="HomeNet",
            wifi_signal_dbm=-57.0,
            error=None,
        ),
    )
    repo.save_run(run)

    out = reader.get_runs_in_period(
        started - timedelta(days=1), started + timedelta(days=1)
    )
    assert len(out) == 1
    r = out[0]
    assert r.active_game_server is not None
    assert r.active_game_server.ip == "10.20.30.40"
    assert r.active_game_server.port == 5000
    assert r.active_game_server.process_name == "League of Legends.exe"
    assert len(r.dns_results) == 1
    assert r.dns_results[0].hostname == "auth.riotgames.com"
    assert r.dns_results[0].resolved_ip == "1.2.3.4"
    assert r.dns_results[0].elapsed_ms == 42.0
    assert r.interface_snapshot is not None
    assert r.interface_snapshot.type is InterfaceType.WIFI
    assert r.interface_snapshot.name == "Wi-Fi"
    assert r.interface_snapshot.wifi_ssid == "HomeNet"
    assert r.interface_snapshot.wifi_signal_dbm == -57.0


def test_sqlite_reader_reconstructs_filtered_outcome_with_stats_none() -> None:
    """Invariante: stats=None cuando outcome != SUCCESS."""
    reader, repo = _reader_and_repo()
    started = datetime(2026, 3, 15, 14, 0, 0)
    run = _run(
        started=started,
        run_id="r-filtered",
        probes=[_probe(outcome=ProbeOutcomeKind.FILTERED)],
    )
    repo.save_run(run)

    out = reader.get_runs_in_period(
        started - timedelta(days=1), started + timedelta(days=1)
    )
    assert len(out) == 1
    p = out[0].probes[0]
    assert p.outcome is ProbeOutcomeKind.FILTERED
    assert p.stats is None


def test_sqlite_reader_rejects_end_before_start() -> None:
    reader, _repo = _reader_and_repo()
    now = datetime.now()
    with pytest.raises(ValueError, match="end no puede ser anterior a start"):
        reader.get_runs_in_period(start=now, end=now - timedelta(seconds=1))


def test_sqlite_reader_compliance_with_protocol() -> None:
    from gnd.domain.ports.run_history_reader import RunHistoryReader

    reader, _repo = _reader_and_repo()
    assert isinstance(reader, RunHistoryReader)  # runtime_checkable


def test_sqlite_reader_reconstructs_ipv6_family_field() -> None:
    """Fase 12a.4: la columna `family` se persiste y se reconstruye."""
    reader, repo = _reader_and_repo()
    started = datetime(2026, 3, 15, 14, 0, 0)
    run = _run(
        started=started,
        run_id="r-v6",
        probes=[_probe(family="ipv6")],
        traceroutes=[
            TracerouteResult(
                target_provider="google",
                hops=[
                    TracerouteHop(
                        hop_number=1,
                        ip=None,
                        hostname=None,
                        rtt_ms=None,
                        responded=False,
                    )
                ],
                culprit_hop_index=None,
                family="ipv6",
            )
        ],
    )
    repo.save_run(run)

    out = reader.get_runs_in_period(
        started - timedelta(days=1), started + timedelta(days=1)
    )
    assert len(out) == 1
    assert out[0].probes[0].family == "ipv6"
    assert out[0].traceroutes[0].family == "ipv6"
