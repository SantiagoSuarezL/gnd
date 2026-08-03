"""Tests de ``ValorantModule`` (Fase 13.3) — validan el DoD de Fase 13.

DoD (IMPLEMENTATION_PLAN.md Fase 13): agregar Valorant es mayormente
contenido dentro de ``diagnostics/games/valorant.py`` — NO requiere
tocar ``analysis/``, ``recommendations/``, ni ``database/``.

Cobertura:
  1. ``ValorantModule`` cumple ``GameDiagnosticsModule`` (Protocol).
  2. ``public_endpoints()`` usa provider ``"valorant_public"`` (distinto
     de ``"riot_public"`` — separa el baseline de Valorant del de LoL).
  3. ``process_names()`` devuelve ``{"VALORANT-Win64-Shipping.exe"}``.
  4. ``detect_active_server()`` delega al ``ConnectionInspector`` con
     los process_names de Valorant.
  5. ``game_server_provider()`` es ``"valorant_game_server"``.
  6. **DoD crítico**: ejecutar ``RunFullDiagnostics`` con un
     ``ValorantModule`` produce un ``DiagnosticRun`` con probes
     ``"valorant_public"`` y ``"valorant_game_server"`` — sin tocar
     ``analysis/``, ``recommendations/``, ni ``database/`` (verificamos
     que esos paquetes no referencian símbolos valorant-*).
"""

from __future__ import annotations

import pytest

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.diagnostics.games.valorant import ValorantModule
from gnd.domain.fakes.fake_diagnostics_repository import (
    FakeDiagnosticsRepository,
)
from gnd.domain.fakes.fake_ping_runner import FakePingRunner
from gnd.domain.fakes.fake_traceroute_runner import (
    FakeTracerouteRunner,
)
from gnd.domain.ports.game_diagnostics_module import GameDiagnosticsModule
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint


def _assert_package_does_not_mention(package_name: str, word: str) -> None:
    """Verifica que ningún ``.py`` del paquete mencione ``word``.

    DoD Fase 13: las capas ``analysis/``, ``recommendations/``, ``database/``
    no deben referenciar símbolos de un juego específico (Valorant) — el
    ``GameDiagnosticsModule`` Protocol abstrae el provider como string
    opaco. Si algún archivo las menciona, significa que se añadió lógica
    específica al juego — rompiendo el DoD.
    """
    import importlib
    import inspect
    import pkgutil

    pkg = importlib.import_module(package_name)
    if not hasattr(pkg, "__path__"):
        # Módulo simple (no paquete): inspecciona su propia source.
        assert word not in inspect.getsource(pkg).lower()
        return
    # Paquete: inspecciona la source de cada sub-módulo .py importable.
    for module_info in pkgutil.walk_packages(pkg.__path__, prefix=f"{package_name}."):
        try:
            module = importlib.import_module(module_info.name)
            assert (
                word not in inspect.getsource(module).lower()
            ), f"{module_info.name} menciona {word!r} — DoD Fase 13 roto"
        except OSError:
            continue


# ---------------------------------------------------------------------------
# Dobles de test: inspector configurable
# ---------------------------------------------------------------------------


class _InspectorStub:
    """ConnectionInspector configurable para tests."""

    def __init__(self, detect_active: bool = False) -> None:
        self._active = detect_active
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
            process_name=next(iter(process_names), "VALORANT-Win64-Shipping.exe"),
        )


class _RepoSpy(FakeDiagnosticsRepository):
    def __init__(self) -> None:
        super().__init__()
        self.save_run_calls: list[object] = []

    def save_run(self, run) -> None:
        self.save_run_calls.append(run)
        self.save(run)


def _targets() -> DiagnosticTargets:
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],  # ignorado cuando hay game_module
        game_process_names={"League of Legends.exe"},  # ignorado también
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


# ---------------------------------------------------------------------------
# Tests de ValorantModule (Protocol + métodos)
# ---------------------------------------------------------------------------


class TestValorantModuleProtocol:
    def test_cumple_game_diagnostics_module(self) -> None:
        module = ValorantModule(connection_inspector=None)
        assert isinstance(module, GameDiagnosticsModule)

    def test_devuelve_endpoints_con_provider_valorant_public(self) -> None:
        module = ValorantModule(connection_inspector=None)
        eps = module.public_endpoints()
        assert len(eps) > 0
        assert all(isinstance(ep, GameEndpoint) for ep in eps)
        # Provider de Valorant es distinto de "riot_public" — separa baseline.
        assert all(ep.provider == "valorant_public" for ep in eps)
        assert all(ep.family == "ipv4" for ep in eps)

    def test_process_names_es_valorant_shipping(self) -> None:
        module = ValorantModule(connection_inspector=None)
        assert module.process_names() == {"VALORANT-Win64-Shipping.exe"}

    def test_game_server_provider_es_valorant_game_server(self) -> None:
        module = ValorantModule(connection_inspector=None)
        assert module.game_server_provider() == "valorant_game_server"

    def test_detect_sin_inspector_devuelve_none_sin_lanzar(self) -> None:
        module = ValorantModule(connection_inspector=None)
        assert module.detect_active_server() is None


class TestValorantModuleDetect:
    def test_delega_al_inspector_con_process_names_de_valorant(self) -> None:
        inspector = _InspectorStub(detect_active=True)
        module = ValorantModule(connection_inspector=inspector)
        result = module.detect_active_server()
        assert result is not None
        assert result.process_name == "VALORANT-Win64-Shipping.exe"
        assert inspector.calls == [{"VALORANT-Win64-Shipping.exe"}]

    def test_inspector_devuelve_none_propaga_none(self) -> None:
        inspector = _InspectorStub(detect_active=False)
        module = ValorantModule(connection_inspector=inspector)
        assert module.detect_active_server() is None


# ---------------------------------------------------------------------------
# DoD crítico: orquestador + Valorant no requiere tocar analysis/database/recommendations
# ---------------------------------------------------------------------------


class TestDoDValorantNoTocaAnalysisDatabaseRecommendations:
    """DoD Fase 13: agregar Valorant no requiere tocar las capas inferiores.

    Verificamos end-to-end: ``RunFullDiagnostics`` con ``ValorantModule``
    produce un ``DiagnosticRun`` con probes ``"valorant_public"`` y
    ``"valorant_game_server"`` (no ``"riot_public"`` ni ``"riot_game_server"``),
    y las capas ``analysis/``, ``recommendations/``, ``database/`` no
    referencian símbolos valorant-* (no fueron modificadas para soportar
    Valorant — el Protocol abstrae el provider como string opaco).
    """

    def test_run_con_valorant_module_produce_probes_valorant(self) -> None:
        inspector = _InspectorStub(detect_active=True)
        module = ValorantModule(connection_inspector=inspector)
        uc = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=inspector,
            repository=_RepoSpy(),
            game_module=module,
        )
        run = uc.execute(_targets(), _params())
        providers = {p.provider for p in run.probes}
        # Valorant aporta sus propios providers (no los de LoL).
        assert "valorant_public" in providers
        assert "valorant_game_server" in providers
        # No hay fuga de los providers hardcodeados de LoL:
        assert "riot_public" not in providers
        assert "riot_game_server" not in providers

    def test_run_con_valorant_detect_none_no_agrega_probe_game_server(self) -> None:
        inspector = _InspectorStub(detect_active=False)
        module = ValorantModule(connection_inspector=inspector)
        uc = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=inspector,
            repository=_RepoSpy(),
            game_module=module,
        )
        run = uc.execute(_targets(), _params())
        providers = {p.provider for p in run.probes}
        assert "valorant_game_server" not in providers
        assert run.active_game_server is None

    def test_traceroute_usa_provider_valorant_public(self) -> None:
        inspector = _InspectorStub(detect_active=False)
        module = ValorantModule(connection_inspector=inspector)
        uc = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=inspector,
            repository=_RepoSpy(),
            game_module=module,
        )
        run = uc.execute(_targets(), _params())
        traceroute_providers = {tr.target_provider for tr in run.traceroutes}
        assert "valorant_public" in traceroute_providers
        assert "riot_public" not in traceroute_providers

    def test_analysis_no_referencia_simbolos_valorant(self) -> None:
        """DoD: ``analysis/`` no fue modificado para soportar Valorant.

        Si lo hubiera sido, contendría strings "valorant" — el Protocol
        abstrae el provider como string opaco, así que analysis NO debe
        mencionar a Valorant. (Verificación estática del invariant.)
        """
        _assert_package_does_not_mention("gnd.analysis", "valorant")

    def test_recommendations_no_referencia_simbolos_valorant(self) -> None:
        """DoD: ``recommendations/`` no fue modificado para soportar Valorant."""
        _assert_package_does_not_mention("gnd.recommendations", "valorant")

    def test_database_schema_no_referencia_simbolos_valorant(self) -> None:
        """DoD: ``database/`` no fue modificado para soportar Valorant.

        La schema SQLite guarda ``provider`` como string opaco. Si
        ``database/`` mencionara a Valorant, significaría que se añadió
        lógica específica — rompiendo el DoD.
        """
        _assert_package_does_not_mention("gnd.database", "valorant")


# ---------------------------------------------------------------------------
# build_game_module: config "valorant" -> ValorantModule
# ---------------------------------------------------------------------------


class TestBuildGameModuleValorant:
    def test_config_valorant_devuelve_valorant_module(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gnd.composition_root import build_game_module
        from gnd.config import get_settings

        original = get_settings()
        original_game = original.game_detection.active_game
        try:
            monkeypatch.setattr(original.game_detection, "active_game", "valorant")
            module = build_game_module(connection_inspector=_InspectorStub())
            assert isinstance(module, ValorantModule)
            assert module.game_server_provider() == "valorant_game_server"
        finally:
            monkeypatch.setattr(original.game_detection, "active_game", original_game)
