"""Tests de la feature Fase 12a.2 — DNS timing.

Estructura:
1. Modelos (`DnsResolution` invariantes).
2. Fake (`FakeDnsResolver` contract).
3. Adaptador real (`RealDnsResolver` contra socket real — coverage
   del happy path con `localhost`, que esta garantido en cualquier OS).
4. Orquestador (`RunFullDiagnostics` etapa DNS serial + persistencia
   en `dns_results` tabla).
5. Composición (wiring del composition_root incluye el resolver).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
    _looks_like_ip_literal,
)
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import (
    SqliteDiagnosticsRepository,
)
from gnd.domain.fakes import (
    FakeDiagnosticsRepository,
    FakeDnsResolver,
    FakePingRunner,
    FakeTracerouteRunner,
)
from gnd.models.dns_measurement import DnsOutcome, DnsResolution

# ---------------------------------------------------------------------------
# 1. DnsResolution invariantes
# ---------------------------------------------------------------------------


class TestDnsResolutionInvariants:
    def test_success_requires_resolved_ip_and_elapsed(self):
        with pytest.raises(ValueError, match="resolved_ip no puede ser None"):
            DnsResolution(
                hostname="auth.riotgames.com",
                resolved_ip=None,
                outcome=DnsOutcome.SUCCESS,
                elapsed_ms=15.0,
                family="ipv4",
                error=None,
            )

    def test_success_requires_elapsed_ms(self):
        with pytest.raises(ValueError, match="elapsed_ms no puede ser None"):
            DnsResolution(
                hostname="auth.riotgames.com",
                resolved_ip="1.2.3.4",
                outcome=DnsOutcome.SUCCESS,
                elapsed_ms=None,
                family="ipv4",
                error=None,
            )

    def test_non_success_requires_error(self):
        with pytest.raises(ValueError, match="error no puede ser None"):
            DnsResolution(
                hostname="auth.riotgames.com",
                resolved_ip=None,
                outcome=DnsOutcome.TIMEOUT,
                elapsed_ms=1000.0,
                family="ipv4",
                error=None,
            )

    def test_invalid_family_rejected(self):
        with pytest.raises(ValueError, match="family debe ser"):
            DnsResolution(
                hostname="auth.riotgames.com",
                resolved_ip=None,
                outcome=DnsOutcome.ERROR,
                elapsed_ms=None,
                family="ipv9",
                error="boom",
            )

    def test_empty_hostname_rejected(self):
        with pytest.raises(ValueError, match="hostname no puede ser vacío"):
            DnsResolution(
                hostname="",
                resolved_ip=None,
                outcome=DnsOutcome.ERROR,
                elapsed_ms=None,
                family="ipv4",
                error="no host",
            )

    def test_frozen_dataclass_is_immutable(self):
        from dataclasses import FrozenInstanceError

        d = DnsResolution(
            hostname="h",
            resolved_ip="1.1.1.1",
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=10.0,
            family="ipv4",
            error=None,
        )
        with pytest.raises(FrozenInstanceError):
            d.hostname = "otro"  # type: ignore[misc]

    def test_valid_success_instance_constructs(self):
        d = DnsResolution(
            hostname="auth.riotgames.com",
            resolved_ip="23.45.67.89",
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=42.5,
            family="ipv4",
            error=None,
        )
        assert d.hostname == "auth.riotgames.com"
        assert d.resolved_ip == "23.45.67.89"
        assert d.outcome is DnsOutcome.SUCCESS


# ---------------------------------------------------------------------------
# 2. FakeDnsResolver
# ---------------------------------------------------------------------------


class TestFakeDnsResolver:
    def test_default_returns_synthetic_success(self):
        r = FakeDnsResolver()
        result = r.resolve("auth.riotgames.com")
        assert result.outcome is DnsOutcome.SUCCESS
        assert result.resolved_ip == "127.0.0.1"
        assert result.elapsed_ms == 1.0
        assert result.error is None
        assert len(r.calls) == 1
        assert r.calls[0]["hostname"] == "auth.riotgames.com"

    def test_set_result_overrides_for_specific_host(self):
        r = FakeDnsResolver()
        slow = DnsResolution(
            hostname="auth.riotgames.com",
            resolved_ip="1.2.3.4",
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=500.0,
            family="ipv4",
            error=None,
        )
        r.set_result("auth.riotgames.com", slow)
        result = r.resolve("auth.riotgames.com")
        assert result.elapsed_ms == 500.0
        assert result.resolved_ip == "1.2.3.4"

    def test_timeout_outcome_preserved(self):
        r = FakeDnsResolver()
        r.set_default_result(
            DnsResolution(
                hostname="x",
                resolved_ip=None,
                outcome=DnsOutcome.TIMEOUT,
                elapsed_ms=1000.0,
                family="ipv4",
                error="timeout 1000ms",
            )
        )
        result = r.resolve("auth.riotgames.com")
        assert result.outcome is DnsOutcome.TIMEOUT
        assert result.resolved_ip is None
        assert "timeout" in (result.error or "")


# ---------------------------------------------------------------------------
# 3. RealDnsResolver against socket real
# ---------------------------------------------------------------------------


class TestRealDnsResolver:
    def test_resolve_localhost_returns_success(self):
        # localhost should exist on any dev OS / runner de CI. Usa el
        # hostname literal "localhost" que resuelve a 127.0.0.1.
        from gnd.network.real_dns_resolver import RealDnsResolver

        r = RealDnsResolver()
        result = r.resolve("localhost", family="ipv4", timeout_ms=2000)
        # Algunos OS (Windows lean) podrian no resolver localhost en DNS normal
        # (usa /etc/hosts), pero getaddrinfo SI lo toca y resuelve a 127.0.0.1.
        assert result.outcome is DnsOutcome.SUCCESS
        assert result.resolved_ip is not None
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0.0
        assert result.error is None

    def test_resolve_invalid_host_returns_error_or_timeout(self):
        # Un host sinteticamente falso genera gaierror -> ERROR (no propagar).
        from gnd.network.real_dns_resolver import RealDnsResolver

        r = RealDnsResolver()
        result = r.resolve("nx.invalid.somefake", timeout_ms=300)
        # Algunos DNS publicos *resuelven* dominios inexistentes a paginas
        # de captive portal (DNS hijacking), pero prefixes invalidos
        # generalmente fallan. Aceptamos ERROR o TIMEOUT pero nunca excepción.
        assert result.outcome in (DnsOutcome.ERROR, DnsOutcome.TIMEOUT)
        assert result.error is not None

    def test_resolve_with_zero_timeout_might_timeout(self):
        # timeout=0 podria disparar timeout inmediato o success instant
        # si el OS cacheo el host. Acepta ambos. Lo importante: nunca lanza.
        from gnd.network.real_dns_resolver import RealDnsResolver

        r = RealDnsResolver()
        result = r.resolve("localhost", family="ipv4", timeout_ms=1)
        # Puede ser SUCCESS o TIMEOUT dependiendo del scheduler del OS.
        # Invariant: no exception raised, estructura valid.
        assert result.outcome in (DnsOutcome.SUCCESS, DnsOutcome.TIMEOUT)
        assert result.hostname == "localhost"


# ---------------------------------------------------------------------------
# 4. Orquestador: etapa DNS serial en RunFullDiagnostics.execute()
# ---------------------------------------------------------------------------


def _targets_with_riot_public():
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names={"League of Legends.exe"},
    )


def _params_with_dns_enabled(hosts=None, include_ipv6=False, timeout=1000):
    return DiagnosticParams(
        ping_count=2,
        ping_timeout_ms=200,
        traceroute_max_hops=5,
        traceroute_timeout_ms=200,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
        dns_enabled=True,
        dns_hosts=tuple(hosts) if hosts else (),
        dns_timeout_ms=timeout,
        dns_include_ipv6=include_ipv6,
    )


def _build_use_case(dns_resolver, repo=None, db_factory=None):
    inspector = _NoopInspector()
    return RunFullDiagnostics(
        ping_runner=FakePingRunner(),
        traceroute_runner=FakeTracerouteRunner(),
        connection_inspector=inspector,
        repository=repo or FakeDiagnosticsRepository(),
        db_factory=db_factory,
        dns_resolver=dns_resolver,
    )


class _NoopInspector:
    def __init__(self):
        self.calls: list[set[str]] = []

    def detect_active_game_server(self, names):
        self.calls.append(names)
        return None


class TestRunFullDiagnosticsDnsStage:
    def test_dns_disabled_skips_stage(self):
        # dns_enabled=False -> no hay etapa, dns_results vacio.
        resolver = FakeDnsResolver()
        uc = _build_use_case(resolver)
        params = _params_with_dns_enabled()
        params = DiagnosticParams(
            ping_count=2,
            ping_timeout_ms=200,
            traceroute_max_hops=5,
            traceroute_timeout_ms=200,
            baseline_period_days=30,
            packet_loss_warning_pct=1.0,
            packet_loss_critical_pct=3.0,
            jitter_warning_ms=20.0,
            jitter_critical_ms=40.0,
            dns_enabled=False,
            dns_hosts=(),
            dns_timeout_ms=1000,
            dns_include_ipv6=False,
        )
        run = uc.execute(_targets_with_riot_public(), params)
        assert run.dns_results == ()
        assert len(resolver.calls) == 0

    def test_dns_enabled_resolves_each_host(self):
        resolver = FakeDnsResolver()
        uc = _build_use_case(resolver)
        run = uc.execute(
            _targets_with_riot_public(),
            _params_with_dns_enabled(hosts=["auth.riotgames.com"]),
        )
        assert len(run.dns_results) == 1
        assert run.dns_results[0].hostname == "auth.riotgames.com"
        assert run.dns_results[0].outcome is DnsOutcome.SUCCESS
        assert len(resolver.calls) == 1

    def test_dns_default_hosts_use_riot_public_when_empty(self):
        # dns_hosts=() -> el use case cae a targets.riot_public.
        resolver = FakeDnsResolver()
        uc = _build_use_case(resolver)
        run = uc.execute(
            _targets_with_riot_public(),
            _params_with_dns_enabled(),
        )
        assert len(run.dns_results) == 1
        assert run.dns_results[0].hostname == "auth.riotgames.com"

    def test_dns_filters_ip_literals_from_hosts(self):
        # Una IP literal en el config no tiene sentido para DNS; se filtra.
        resolver = FakeDnsResolver()
        uc = _build_use_case(resolver)
        run = uc.execute(
            _targets_with_riot_public(),
            _params_with_dns_enabled(
                hosts=["8.8.8.8", "1.1.1.1", "auth.riotgames.com"]
            ),
        )
        # Solo el hostname se resuelve; las 2 IPs se filtran.
        assert len(run.dns_results) == 1
        assert run.dns_results[0].hostname == "auth.riotgames.com"
        assert len(resolver.calls) == 1

    def test_dns_ipv6_invoked_when_include_ipv6(self):
        resolver = FakeDnsResolver()
        uc = _build_use_case(resolver)
        run = uc.execute(
            _targets_with_riot_public(),
            _params_with_dns_enabled(hosts=["h"], include_ipv6=True),
        )
        # 2 calls: 1 ipv4 + 1 ipv6
        assert len(resolver.calls) == 2
        families = [c["family"] for c in resolver.calls]
        assert families == ["ipv4", "ipv6"]
        assert len(run.dns_results) == 2

    def test_dns_timeout_propagates_to_dns_resolution(self):
        # Resolver que devuelve timeout no aborta la corrida.
        resolver = FakeDnsResolver()
        resolver.set_default_result(
            DnsResolution(
                hostname="x",
                resolved_ip=None,
                outcome=DnsOutcome.TIMEOUT,
                elapsed_ms=1000.0,
                family="ipv4",
                error="timeout 1000ms",
            )
        )
        uc = _build_use_case(resolver)
        run = uc.execute(
            _targets_with_riot_public(),
            _params_with_dns_enabled(hosts=["slowhost.test"]),
        )
        assert len(run.dns_results) == 1
        assert run.dns_results[0].outcome is DnsOutcome.TIMEOUT
        # La corrida finaliza (no aborta).
        assert run.run_id

    def test_dns_buggy_resolver_does_not_abort_run(self):
        # Resolver que lanza excepcion es atrapado por belt-and-suspenders.
        class BadResolver:
            def resolve(self, hostname, *, family="ipv4", timeout_ms=1000):
                raise RuntimeError("oops")

        uc = _build_use_case(BadResolver())
        run = uc.execute(
            _targets_with_riot_public(),
            _params_with_dns_enabled(hosts=["x"]),
        )
        assert len(run.dns_results) == 1
        assert run.dns_results[0].outcome is DnsOutcome.ERROR
        assert "oops" in (run.dns_results[0].error or "")


# ---------------------------------------------------------------------------
# 5. Persistencia dns_results en SQLite (Schema v2 / tabla nueva)
# ---------------------------------------------------------------------------


class TestDnsResultsPersistence:
    def test_save_run_persists_dns_results_atomically(self, tmp_path: Path):
        from gnd.models.diagnostic_run import DiagnosticRun
        from gnd.models.latency_stats import LatencyStats
        from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
        from gnd.models.recommendation import Recommendation

        db_path = tmp_path / "history.db"
        factory = SqliteConnectionFactory(str(db_path))
        repo = SqliteDiagnosticsRepository(factory)

        stats = LatencyStats(
            avg_ms=10.0,
            min_ms=8.0,
            max_ms=12.0,
            jitter_ms=1.0,
            packet_loss_pct=0.0,
            samples=4,
        )
        run = DiagnosticRun(
            run_id="testrun01",
            started_at=datetime(2026, 7, 28, 12, 0, 0),
            finished_at=datetime(2026, 7, 28, 12, 0, 5),
            probes=[
                ProbeResult(
                    target_name="g",
                    target_ip="1.1.1.1",
                    provider="local",
                    outcome=ProbeOutcomeKind.SUCCESS,
                    stats=stats,
                    timestamp=datetime(2026, 7, 28, 12, 0, 0),
                ),
            ],
            traceroutes=[],
            active_game_server=None,
            recommendation=Recommendation(
                verdict="safe_to_play",
                headline="Todo OK",
                explanation=["ok"],
                score=90,
                responsible_component="local",
            ),
            dns_results=(
                DnsResolution(
                    hostname="auth.riotgames.com",
                    resolved_ip="23.45.67.89",
                    outcome=DnsOutcome.SUCCESS,
                    elapsed_ms=15.5,
                    family="ipv4",
                    error=None,
                ),
                DnsResolution(
                    hostname="slow.test",
                    resolved_ip=None,
                    outcome=DnsOutcome.TIMEOUT,
                    elapsed_ms=1000.0,
                    family="ipv4",
                    error="timeout 1000ms",
                ),
            ),
        )

        repo.save_run(run)
        conn = factory.create_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM dns_results WHERE run_id = ?",
                ("testrun01",),
            ).fetchone()
            assert row[0] == 2

            dns_row = conn.execute(
                """SELECT hostname, resolved_ip, outcome, elapsed_ms,
                          family, error
                   FROM dns_results WHERE run_id = ? AND hostname = ?""",
                ("testrun01", "auth.riotgames.com"),
            ).fetchone()
            assert dns_row is not None
            assert dns_row[0] == "auth.riotgames.com"
            assert dns_row[1] == "23.45.67.89"
            assert dns_row[2] == "SUCCESS"
            assert dns_row[3] == 15.5
            assert dns_row[4] == "ipv4"
            assert dns_row[5] is None
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 6. _looks_like_ip_literal helper
# ---------------------------------------------------------------------------


class TestLooksLikeIpLiteral:
    @pytest.mark.parametrize(
        "s,expected",
        [
            ("8.8.8.8", True),
            ("1.1.1.1", True),
            ("255.255.255.255", True),
            ("::1", True),
            ("2001:db8::1", True),
            ("auth.riotgames.com", False),
            ("localhost", False),
            ("lol.secure.dyn.riotcdn.net", False),
            ("", False),
        ],
    )
    def test_classification(self, s, expected):
        assert _looks_like_ip_literal(s) is expected
