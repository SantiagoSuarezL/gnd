"""Tests del Protocol ``GameDiagnosticsModule`` (Fase 13.1).

Verifica:
  - El Protocol es ``runtime_checkable`` y acepta implementaciones con
    los 3 métodos del spec (ARCHITECTURE.md §7).
  - Clases que no implementan los 3 métodos NO pasan el ``isinstance``.
  - El fake y ``LeagueOfLegendsModule`` cumplen el Protocol.
"""

from __future__ import annotations

from gnd.diagnostics.games.league_of_legends import LeagueOfLegendsModule
from gnd.domain.fakes import FakeGameDiagnosticsModule
from gnd.domain.ports.game_diagnostics_module import GameDiagnosticsModule
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint

# ---------------------------------------------------------------------------
# Protocol compliance — runtime_checkable valida firma presencial
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """runtime_checkable valida présence de los 3 métodos, no tipos."""

    def test_league_of_legends_module_cumple_protocol(self) -> None:
        module = LeagueOfLegendsModule(connection_inspector=None)
        assert isinstance(module, GameDiagnosticsModule)

    def test_fake_cumple_protocol(self) -> None:
        fake = FakeGameDiagnosticsModule()
        assert isinstance(fake, GameDiagnosticsModule)

    def test_active_game_server_detector_no_cumple_protocol(self) -> None:
        # ActiveGameServerDetector solo implementa detect_active_game_server
        # (no public_endpoints ni process_names como atributos libres) ->
        # NO cumple GameDiagnosticsModule (motivo de la Fase 13:需要一个 adapter).
        from gnd.diagnostics.riot import ActiveGameServerDetector

        det = ActiveGameServerDetector()
        assert not isinstance(det, GameDiagnosticsModule)

    def test_clase_sin_metodos_no_cumple(self) -> None:
        class _Empty:
            pass

        assert not isinstance(_Empty(), GameDiagnosticsModule)

    def test_clase_con_un_solo_metodo_no_cumple(self) -> None:
        class _SoloEndpoint:
            def public_endpoints(self) -> list[GameEndpoint]:
                return []

        assert not isinstance(_SoloEndpoint(), GameDiagnosticsModule)


# ---------------------------------------------------------------------------
# Contracto del módulo: detect_active_server nunca lanza (EP §1.2)
# ---------------------------------------------------------------------------


class TestContractNoRaise:
    """El contrato del Protocol: detect_active_server nunca lanza."""

    def test_fake_detect_devuelve_none_por_default(self) -> None:
        fake = FakeGameDiagnosticsModule()
        # Sin setear detect_result, devuelve None (feature apagada).
        assert fake.detect_active_server() is None

    def test_fake_detect_devuelve_result_programado(self) -> None:
        info = ActiveGameServerInfo(
            ip="64.7.135.1",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="League of Legends.exe",
        )
        fake = FakeGameDiagnosticsModule(detect_result=info)
        assert fake.detect_active_server() is info

    def test_league_of_legends_sin_inspector_devuelve_none_sin_lanzar(self) -> None:
        # Sin ConnectionInspector inyectado -> None con log (no raise).
        module = LeagueOfLegendsModule(connection_inspector=None)
        assert module.detect_active_server() is None


# ---------------------------------------------------------------------------
# Defaults vacíos (backwards-compat con modulo apagado)
# ---------------------------------------------------------------------------


class TestDefaultsEmpty:
    """Defaults simulan modulo sin endpoints/processes (feature off)."""

    def test_fake_public_endpoints_vacio_por_default(self) -> None:
        assert FakeGameDiagnosticsModule().public_endpoints() == []

    def test_fake_process_names_vacio_por_default(self) -> None:
        assert FakeGameDiagnosticsModule().process_names() == set()

    def test_fake_devuelve_copia_no_referencia_interna(self) -> None:
        # El fake debe devolver copias (Regla inmutabilidad): el caller
        # mutating el resultado no afecta estado interno del fake.
        fake = FakeGameDiagnosticsModule(
            public_endpoints_result=[
                GameEndpoint(host="a", provider="p"),
                GameEndpoint(host="b", provider="p"),
            ],
            process_names_result={"x", "y"},
        )
        eps = fake.public_endpoints()
        eps.append(GameEndpoint(host="z", provider="p"))
        assert fake.public_endpoints() == [
            GameEndpoint(host="a", provider="p"),
            GameEndpoint(host="b", provider="p"),
        ]

        names = fake.process_names()
        names.add("mutated")
        assert fake.process_names() == {"x", "y"}


# ---------------------------------------------------------------------------
# Registro de llamadas del fake (para asserts en tests del orquestador)
# ---------------------------------------------------------------------------


class TestFakeCallRecording:
    """El fake registra cada llamada para asserts del orquestador."""

    def test_cuenta_llamadas_a_cada_metodo(self) -> None:
        fake = FakeGameDiagnosticsModule()
        fake.public_endpoints()
        fake.public_endpoints()
        fake.process_names()
        fake.detect_active_server()
        assert fake.public_endpoints_calls == 2
        assert fake.process_names_calls == 1
        assert fake.detect_calls == 1

    def test_setters_mutan_el_estado_programable(self) -> None:
        fake = FakeGameDiagnosticsModule()
        fake.set_public_endpoints(
            [
                GameEndpoint(host="ep1", provider="p"),
                GameEndpoint(host="ep2", provider="p"),
            ]
        )
        fake.set_process_names({"P1.exe"})
        info = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=7,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="P1.exe",
        )
        fake.set_detect_result(info)
        assert fake.public_endpoints() == [
            GameEndpoint(host="ep1", provider="p"),
            GameEndpoint(host="ep2", provider="p"),
        ]
        assert fake.process_names() == {"P1.exe"}
        assert fake.detect_active_server() is info
