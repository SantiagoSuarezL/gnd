"""Tests de la Fase 12a.4 — soporte IPv6 opt-in.

Cubre:
- Orquestador duplica specs IPv6 solo cuando targets.*_ipv6 estan seteados.
- Sin targets IPv6, el comportamiento es identico a pre-12a.4 (retro-compat).
- `DiagnosticTargets.has_any_ipv6_target()` responde correctamente.
- Persistence: `family` se persiste en probe_results y traceroute_results
  y se puede leer de vuelta.
- Composition root smoke: DiagnosticTargets carga *_ipv6=None por defecto.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.database.schema import ensure_schema
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository
from gnd.domain.fakes import FakeDatabaseConnectionFactory
from gnd.domain.fakes.fake_diagnostics_repository import FakeDiagnosticsRepository
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_traceroute_runner import FakeTracerouteRunner
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult


class _InspectorStub:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def detect_active_game_server(self, process_names: set[str]):
        return None


class _RepoSpy(FakeDiagnosticsRepository):
    def __init__(self) -> None:
        super().__init__()
        self.save_run_calls: list[DiagnosticRun] = []

    def save_run(self, run: DiagnosticRun) -> None:
        self.save_run_calls.append(run)
        self.save(run)


def _build_use_case(
    *,
    ping_runner=None,
    traceroute_runner=None,
    repository=None,
) -> RunFullDiagnostics:
    return RunFullDiagnostics(
        ping_runner=ping_runner or FakePingRunner(),
        traceroute_runner=traceroute_runner or FakeTracerouteRunner(),
        connection_inspector=_InspectorStub(),
        repository=repository or _RepoSpy(),
    )


def _targets_v4_only() -> DiagnosticTargets:
    """DiagnosticTargets con todos los *_ipv6 en None/[] (default)."""
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names=set(),
    )


def _targets_with_v6() -> DiagnosticTargets:
    """DiagnosticTargets con todos los *_ipv6 seteados."""
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names=set(),
        google_dns_ipv6="2606:4700:4700::1111",
        cloudflare_ipv6="2606:4700:4700::1001",
        quad9_ipv6="2620:fe::fe",
        riot_public_ipv6=["auth.riotgames.com"],
    )


def _params() -> DiagnosticParams:
    return DiagnosticParams(
        ping_count=2,
        ping_timeout_ms=500,
        traceroute_max_hops=10,
        traceroute_timeout_ms=500,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
    )


# --------------------------------------------------------------------------- #
# has_any_ipv6_target
# --------------------------------------------------------------------------- #


class TestHasAnyIpv6Target:
    def test_false_cuando_todos_none(self):
        assert _targets_v4_only().has_any_ipv6_target() is False

    def test_true_cuando_uno_seteado(self):
        t = DiagnosticTargets(
            gateway_ip="192.168.1.1",
            google_dns="8.8.8.8",
            cloudflare="1.1.1.1",
            quad9="9.9.9.9",
            riot_public=[],
            game_process_names=set(),
            google_dns_ipv6="2606:4700:4700::1111",
        )
        assert t.has_any_ipv6_target() is True

    def test_true_cuando_riot_public_ipv6_no_vacio(self):
        t = DiagnosticTargets(
            gateway_ip="192.168.1.1",
            google_dns="8.8.8.8",
            cloudflare="1.1.1.1",
            quad9="9.9.9.9",
            riot_public=[],
            game_process_names=set(),
            riot_public_ipv6=["auth.riotgames.com"],
        )
        assert t.has_any_ipv6_target() is True

    def test_false_cuando_riot_public_ipv6_vacio(self):
        t = DiagnosticTargets(
            gateway_ip="192.168.1.1",
            google_dns="8.8.8.8",
            cloudflare="1.1.1.1",
            quad9="9.9.9.9",
            riot_public=[],
            game_process_names=set(),
            riot_public_ipv6=[],
        )
        assert t.has_any_ipv6_target() is False


# --------------------------------------------------------------------------- #
# Orquestador: dupplicacion de specs IPv6
# --------------------------------------------------------------------------- #


class TestOrquestadorDuplicaSpecsV6:
    def test_sin_v6_solo_pings_v4(self):
        """Sin targets IPv6, el orquestador solo hace probes IPv4
        (backwards-compat con runs pre-12a.4)."""
        ping = FakePingRunner()
        uc = _build_use_case(ping_runner=ping)
        uc.execute(_targets_v4_only(), _params())
        # 4 fixos (gateway/google/cloudflare/quad9) + 1 riot_public = 5.
        assert len(ping.calls) == 5
        assert all(c["family"] == "ipv4" for c in ping.calls)

    def test_con_v6_duplica_specs(self):
        """Con todos los *_ipv6 seteados, el orquestador anade probes
        IPv6 ademas de los IPv4 (5 v4 + 4 v6 = 9)."""
        ping = FakePingRunner()
        uc = _build_use_case(ping_runner=ping)
        uc.execute(_targets_with_v6(), _params())
        # 5 IPv4 + 4 IPv6 (google, cloudflare, quad9, riot_public).
        assert len(ping.calls) == 9
        v6_calls = [c for c in ping.calls if c["family"] == "ipv6"]
        v4_calls = [c for c in ping.calls if c["family"] == "ipv4"]
        assert len(v6_calls) == 4
        assert len(v4_calls) == 5

    def test_v6_calls_usan_targets_ipv6(self):
        """Los probes v6 apuntan a las IPs v6 seteadas en config."""
        ping = FakePingRunner()
        uc = _build_use_case(ping_runner=ping)
        uc.execute(_targets_with_v6(), _params())
        v6_ips = {c["target_ip"] for c in ping.calls if c["family"] == "ipv6"}
        assert "2606:4700:4700::1111" in v6_ips  # google
        assert "2606:4700:4700::1001" in v6_ips  # cloudflare
        assert "2620:fe::fe" in v6_ips  # quad9

    def test_v6_calls_nombres_distintos_a_v4(self):
        """Los target_name de v6 llevan sufijo ':v6' para distinguir."""
        ping = FakePingRunner()
        uc = _build_use_case(ping_runner=ping)
        uc.execute(_targets_with_v6(), _params())
        v6_names = {c["target_name"] for c in ping.calls if c["family"] == "ipv6"}
        assert "google_dns:v6" in v6_names
        assert "cloudflare:v6" in v6_names
        assert "quad9:v6" in v6_names
        # riot_public usa patron riot_public:<host>:v6
        assert any(n.startswith("riot_public:") and n.endswith(":v6") for n in v6_names)

    def test_parcial_v6_solo_seteados(self):
        """Si solo algunos *_ipv6 estan seteados, solo esos se duplican."""
        t = DiagnosticTargets(
            gateway_ip="192.168.1.1",
            google_dns="8.8.8.8",
            cloudflare="1.1.1.1",
            quad9="9.9.9.9",
            riot_public=[],
            game_process_names=set(),
            # Solo google y cloudflare seteados v6.
            google_dns_ipv6="2606:4700:4700::1111",
            cloudflare_ipv6="2606:4700:4700::1001",
        )
        ping = FakePingRunner()
        uc = _build_use_case(ping_runner=ping)
        uc.execute(t, _params())
        v6_calls = [c for c in ping.calls if c["family"] == "ipv6"]
        # 4 v4 (gateway, google, cloudflare, quad9) + 2 v6 (google, cloudflare).
        assert len(ping.calls) == 6
        assert len(v6_calls) == 2
        v6_ips = {c["target_ip"] for c in v6_calls}
        assert v6_ips == {"2606:4700:4700::1111", "2606:4700:4700::1001"}


# --------------------------------------------------------------------------- #
# Orquestador: traceroutes duplicados
# --------------------------------------------------------------------------- #


class TestOrquestadorDuplicaTraceroutesV6:
    def test_sin_v6_solo_traceroutes_v4(self):
        """Sin targets IPv6, solo 2 traceroutes v4 (cloudflare + riot_public)."""
        tracer = FakeTracerouteRunner()
        uc = _build_use_case(traceroute_runner=tracer)
        uc.execute(_targets_v4_only(), _params())
        assert len(tracer.calls) == 2
        assert all(c["family"] == "ipv4" for c in tracer.calls)

    def test_con_v6_duplica_traceroutes(self):
        """Con cloudflare_ipv6 + riot_public_ipv6, se anaden 2 traceroutes v6
        ademas de los 2 v4."""
        tracer = FakeTracerouteRunner()
        uc = _build_use_case(traceroute_runner=tracer)
        uc.execute(_targets_with_v6(), _params())
        assert len(tracer.calls) == 4
        v6 = [c for c in tracer.calls if c["family"] == "ipv6"]
        v4 = [c for c in tracer.calls if c["family"] == "ipv4"]
        assert len(v6) == 2
        assert len(v4) == 2

    def test_v6_traceroute_usa_target_ipv6(self):
        """El traceroute v6 apunta a la IP v6 seteada (cloudflare v6)."""
        tracer = FakeTracerouteRunner()
        uc = _build_use_case(traceroute_runner=tracer)
        uc.execute(_targets_with_v6(), _params())
        v6_ips = {c["target_ip"] for c in tracer.calls if c["family"] == "ipv6"}
        assert "2606:4700:4700::1001" in v6_ips  # cloudflare v6


# --------------------------------------------------------------------------- #
# Orquestador: probes resultantes con family correcta
# --------------------------------------------------------------------------- #


class TestProbesFamilyEnRun:
    def test_run_incluye_probes_v6_con_family(self):
        """Los probes v6 en el DiagnosticRun final tienen family='ipv6'."""
        uc = _build_use_case()
        run = uc.execute(_targets_with_v6(), _params())
        v6_probes = [p for p in run.probes if p.family == "ipv6"]
        v4_probes = [p for p in run.probes if p.family == "ipv4"]
        assert len(v6_probes) == 4
        assert len(v4_probes) == 5

    def test_run_sin_v6_solo_probes_v4(self):
        """Sin targets IPv6, todos los probes tienen family='ipv4'."""
        uc = _build_use_case()
        run = uc.execute(_targets_v4_only(), _params())
        assert all(p.family == "ipv4" for p in run.probes)


# --------------------------------------------------------------------------- #
# Persistence: family en SQLite
# --------------------------------------------------------------------------- #


def _make_run_v4_v6(run_id: str = "v6-run") -> DiagnosticRun:
    """Crea un DiagnosticRun con probes y traceroutes de ambas families."""
    t0 = datetime(2026, 7, 28, 12, 0, 0)
    t1 = datetime(2026, 7, 28, 12, 0, 5)
    from gnd.models.latency_stats import LatencyStats

    stats = LatencyStats(
        avg_ms=10.0,
        min_ms=8.0,
        max_ms=12.0,
        jitter_ms=1.0,
        packet_loss_pct=0.0,
        samples=4,
    )
    return DiagnosticRun(
        run_id=run_id,
        started_at=t0,
        finished_at=t1,
        probes=[
            ProbeResult(
                target_name="google_dns",
                target_ip="8.8.8.8",
                provider="google",
                outcome=ProbeOutcomeKind.SUCCESS,
                stats=stats,
                timestamp=t0,
                family="ipv4",
            ),
            ProbeResult(
                target_name="google_dns:v6",
                target_ip="2606:4700:4700::1111",
                provider="google",
                outcome=ProbeOutcomeKind.SUCCESS,
                stats=stats,
                timestamp=t0,
                family="ipv6",
            ),
        ],
        traceroutes=[
            TracerouteResult(
                target_provider="cloudflare",
                hops=[
                    TracerouteHop(
                        hop_number=1,
                        ip="1.2.3.4",
                        hostname=None,
                        rtt_ms=5.0,
                        responded=True,
                    ),
                ],
                culprit_hop_index=None,
                family="ipv4",
            ),
            TracerouteResult(
                target_provider="cloudflare",
                hops=[
                    TracerouteHop(
                        hop_number=1,
                        ip="2606:4700::1",
                        hostname=None,
                        rtt_ms=8.0,
                        responded=True,
                    ),
                ],
                culprit_hop_index=None,
                family="ipv6",
            ),
        ],
        active_game_server=None,
        recommendation=Recommendation(
            verdict="playable",
            headline="ok",
            explanation=["razon"],
            responsible_component="unknown",
            score=80,
        ),
    )


class TestPersistenceFamily:
    def test_persiste_family_en_probes(self):
        """probe_results persiste y lee la columna `family` correctamente."""
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        repo = SqliteDiagnosticsRepository(FakeDatabaseConnectionFactory(conn))
        repo.save_run(_make_run_v4_v6())

        rows = conn.execute(
            "SELECT target_name, family FROM probe_results ORDER BY target_name"
        ).fetchall()
        assert rows == [
            ("google_dns", "ipv4"),
            ("google_dns:v6", "ipv6"),
        ]

    def test_persiste_family_en_traceroutes(self):
        """traceroute_results persiste la columna `family`."""
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        repo = SqliteDiagnosticsRepository(FakeDatabaseConnectionFactory(conn))
        repo.save_run(_make_run_v4_v6())

        rows = conn.execute(
            "SELECT target_provider, family FROM traceroute_results"
        ).fetchall()
        # Dos filas: una v4, una v6.
        assert len(rows) == 2
        families = {r[1] for r in rows}
        assert families == {"ipv4", "ipv6"}

    def test_run_solo_v4_funciona(self):
        """Un run con probes solo v4 se persiste correctamente (backwards-compat).
        La columna family se llena con 'ipv4' por default del modelo."""
        t0 = datetime(2026, 7, 28)
        t1 = datetime(2026, 7, 28, 0, 0, 1)
        from gnd.models.latency_stats import LatencyStats

        stats = LatencyStats(
            avg_ms=10.0,
            min_ms=8.0,
            max_ms=12.0,
            jitter_ms=1.0,
            packet_loss_pct=0.0,
            samples=4,
        )
        run = DiagnosticRun(
            run_id="v4-only",
            started_at=t0,
            finished_at=t1,
            probes=[
                ProbeResult(
                    target_name="google_dns",
                    target_ip="8.8.8.8",
                    provider="google",
                    outcome=ProbeOutcomeKind.SUCCESS,
                    stats=stats,
                    timestamp=t0,
                    # No pasar family: debe default a 'ipv4'.
                ),
            ],
            traceroutes=[],
            active_game_server=None,
            recommendation=Recommendation(
                verdict="playable",
                headline="ok",
                explanation=["x"],
                responsible_component="unknown",
                score=80,
            ),
        )
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        repo = SqliteDiagnosticsRepository(FakeDatabaseConnectionFactory(conn))
        repo.save_run(run)
        row = conn.execute(
            "SELECT family FROM probe_results WHERE run_id = ?", ("v4-only",)
        ).fetchone()
        assert row[0] == "ipv4"


# --------------------------------------------------------------------------- #
# Composition root smoke: targets IPv6 por defecto
# --------------------------------------------------------------------------- #


class TestCompositionRootDefaults:
    def test_targets_ipv6_defaults_none(self):
        """build_run_full_diagnostics carga *_ipv6=None/[] desde GndSettings
        default (sin config.toml con overrides IPv6). Smoke: no rompe."""
        from gnd.composition_root import build_run_full_diagnostics

        _, targets, _ = build_run_full_diagnostics()
        assert targets.google_dns_ipv6 is None
        assert targets.cloudflare_ipv6 is None
        assert targets.quad9_ipv6 is None
        assert targets.riot_public_ipv6 == []
        assert targets.has_any_ipv6_target() is False
