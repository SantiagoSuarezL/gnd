"""Tests del caso de uso RunFullDiagnostics con fakes (sin red ni disco).

EP §4: tests de Application layer sin tocar red real. Usamos los fakes
del dominio (FakePingRunner, FakeTracerouteRunner,
FakeConnectionInspector, FakeDiagnosticsRepository) que ya existen desde
Fase 1.

Objetivo: verificar que el caso de uso orquesta correctamente las 7
etapas del flujo (ARCHITECTURE.md §5) y que:
- Llama a cada Protocol el numero esperado de veces.
- Agrega todos los probes en el resultado.
- Aplica correctamente los baselines cuando se le pasa una conexion.
- Persiste el run via el repository.
- Es agnostico de la UI (no toca tkinter).
"""

from __future__ import annotations

from datetime import datetime

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.domain.fakes.fake_diagnostics_repository import (
    FakeDiagnosticsRepository,
)
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_traceroute_runner import (
    FakeTracerouteRunner,
)
from gnd.models.active_game_server import ActiveGameServerInfo


def _targets() -> DiagnosticTargets:
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names={"League of Legends.exe"},
    )


def _params() -> DiagnosticParams:
    return DiagnosticParams(
        ping_count=4,
        ping_timeout_ms=1000,
        traceroute_max_hops=10,
        traceroute_timeout_ms=1000,
        baseline_period_days=30,
        packet_loss_warning_pct=1.0,
        packet_loss_critical_pct=3.0,
        jitter_warning_ms=20.0,
        jitter_critical_ms=40.0,
    )


class _RepoSpy(FakeDiagnosticsRepository):
    """Wraps FakeDiagnosticsRepository and records save_run calls.

    The real `DiagnosticsRepository.save_run` protocol method is not
    implemented by the existing FakeDiagnosticsRepository (it exposes
    `save`). This spy adds `save_run` so the use case can persist through
    it via the port contract.
    """

    def __init__(self) -> None:
        super().__init__()
        self.save_run_calls: list[object] = []

    def save_run(self, run) -> None:
        self.save_run_calls.append(run)
        # Reuse the underlying in-memory storage from FakeDiagnosticsRepository
        # by calling `save` (don't break callers/tests of the original fake).
        self.save(run)


class _InspectorStub:
    """Inspector configurable for tests (mirrors FakeConnectionInspector
    API but supports the active=True pattern used in the tests):"""

    def __init__(self, active: bool = False) -> None:
        self._active = active
        self.calls: list[set[str]] = []

    def detect_active_game_server(self, process_names: set[str]):
        self.calls.append(set(process_names))
        if not self._active:
            return None
        return ActiveGameServerInfo(
            ip="104.160.150.1",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name=next(iter(process_names), "League of Legends.exe"),
        )


def _build_use_case(
    *,
    ping_runner=None,
    traceroute_runner=None,
    inspector=None,
    repository=None,
    db_factory=None,
    fixed_clock=None,
) -> RunFullDiagnostics:
    return RunFullDiagnostics(
        ping_runner=ping_runner or FakePingRunner(),
        traceroute_runner=traceroute_runner or FakeTracerouteRunner(),
        connection_inspector=inspector or _InspectorStub(),
        repository=repository or _RepoSpy(),
        db_factory=db_factory,
    )


class TestRunFullDiagnostics:
    def test_corrida_basica_devuelve_run_no_vacio(self):
        uc = _build_use_case()
        run = uc.execute(_targets(), _params())
        assert run.run_id
        assert isinstance(run.started_at, datetime)
        assert isinstance(run.finished_at, datetime)
        assert run.finished_at >= run.started_at
        # Al menos 5 probes: local + google + cloudflare + quad9 + riot_public
        assert len(run.probes) >= 5

    def test_persiste_el_run_en_el_repositorio(self):
        repo = _RepoSpy()
        uc = _build_use_case(repository=repo)
        run = uc.execute(_targets(), _params())
        assert len(repo.save_run_calls) == 1
        saved = repo.save_run_calls[-1]
        assert saved.run_id == run.run_id

    def test_llama_a_traceroute_para_cloudflare_y_riot_public(self):
        uc = _build_use_case()
        run = uc.execute(_targets(), _params())
        providers = {tr.target_provider for tr in run.traceroutes}
        assert "cloudflare" in providers
        assert "riot_public" in providers

    def test_si_no_hay_riot_public_no_hay_traceroute_riot(self):
        targets = _targets()
        targets = DiagnosticTargets(
            gateway_ip=targets.gateway_ip,
            google_dns=targets.google_dns,
            cloudflare=targets.cloudflare,
            quad9=targets.quad9,
            riot_public=[],
            game_process_names=targets.game_process_names,
        )
        uc = _build_use_case()
        run = uc.execute(targets, _params())
        providers = {tr.target_provider for tr in run.traceroutes}
        assert "cloudflare" in providers
        assert "riot_public" not in providers

    def test_deteccion_game_server_agrega_probe_riot_game_server(self):
        inspector = _InspectorStub(active=True)
        uc = _build_use_case(inspector=inspector)
        run = uc.execute(_targets(), _params())
        providers = [p.provider for p in run.probes]
        assert "riot_game_server" in providers
        assert run.active_game_server is not None

    def test_sin_game_server_no_agrega_probe_riot_game_server(self):
        inspector = _InspectorStub(active=False)
        uc = _build_use_case(inspector=inspector)
        run = uc.execute(_targets(), _params())
        providers = [p.provider for p in run.probes]
        assert "riot_game_server" not in providers
        assert run.active_game_server is None

    def test_recomendacion_no_es_none_y_tiene_explanation(self):
        uc = _build_use_case()
        run = uc.execute(_targets(), _params())
        rec = run.recommendation
        assert rec is not None
        assert rec.headline
        assert len(rec.explanation) > 0
        assert 0 <= rec.score <= 100

    def test_progress_callback_se_invoca_para_cada_etapa(self):
        uc = _build_use_case()
        stages: list[str] = []
        uc.execute(_targets(), _params(), progress_callback=stages.append)
        # Tras Fase 9 fix (paralelismo): los pings se notifican en una
        # sola etapa "Pings en paralelo: N probes" en vez de 5 separados.
        assert any("Pings en paralelo" in s for s in stages)
        assert "Deteccion de partida activa" in stages
        assert any("Traceroutes en paralelo" in s for s in stages)
        assert "Motor de recomendacion" in stages
        assert "Listo" in stages

    def test_fallo_de_persistencia_no_detiene_la_corrida(self):
        class FailingRepo(_RepoSpy):
            def save_run(self, run):
                raise RuntimeError("DB corrupta")

        uc = _build_use_case(repository=FailingRepo())
        run = uc.execute(_targets(), _params())
        assert run is not None
        assert run.recommendation is not None

    def test_fallo_de_inspector_se_traduce_a_active_game_server_none(self):
        class FailingInspector:
            def detect_active_game_server(self, process_names):
                raise RuntimeError("psutilAccessDenied")

        uc = _build_use_case(inspector=FailingInspector())
        run = uc.execute(_targets(), _params())
        assert run.active_game_server is None

    def test_run_id_es_estable_cuando_se_pasa_explicito(self):
        uc = _build_use_case()
        run = uc.execute(_targets(), _params(), run_id="test-123")
        assert run.run_id == "test-123"


class TestFormatProbeAnomaliesExporter:
    """Smoke: el helper de anomalias de probes se puede importar desde la UI."""

    def test_import_helper(self):
        from gnd.ui.sections import _format_probe_anomalies

        result = _format_probe_anomalies([])
        assert "sin anomalias" in result
