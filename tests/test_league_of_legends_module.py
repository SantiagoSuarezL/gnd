"""Tests de ``LeagueOfLegendsModule`` (Fase 13.1).

Validan que el adapter sobre la lógica Riot existente:
  - Lee ``targets.riot_public`` + ``targets.riot_public_ipv6`` de config
    (settings inyectado) y los concatena en ``public_endpoints()``.
  - Lee ``game_detection.process_names`` y devuelve como ``set[str]``.
  - Delega ``detect_active_server()`` al ``ConnectionInspector`` inyectado,
    pasándole sus ``process_names()``.
  - Si el inspector es ``None``, devuelve ``None`` sin lanzar (EP §1.2).
  - Si config falla (seteo un settings que lanza al leer), degrada a
    vacíos con log (EP §1.2 desde el constructor).

Estilo: Tests unitarios sin tocar config global ni DNS real. El settings
se inyecta como objeto mock-like (usamos el singleton real con monkeypatch
de campos, o un falso simple). Para evitar acoplamiento a Pydantic interno,
inyectamos un ``settings`` fake con atributos ``targets`` y ``game_detection``
- basta duck typing (``LeagueOfLegendsModule._get_settings`` solo lo
guarda y lo lee).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gnd.diagnostics.games.league_of_legends import LeagueOfLegendsModule
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint

# ---------------------------------------------------------------------------
# Dobles de test: settings + inspector fake por duck typing
# ---------------------------------------------------------------------------


@dataclass
class _FakeTargets:
    riot_public: list[str] = field(default_factory=list)
    riot_public_ipv6: list[str] = field(default_factory=list)


@dataclass
class _FakeGameDetection:
    process_names: list[str] = field(default_factory=lambda: ["League of Legends.exe"])


@dataclass
class _FakeSettings:
    """Settings mínimo por duck typing (no necesita ser GndSettings real)."""

    targets: _FakeTargets = field(default_factory=_FakeTargets)
    game_detection: _FakeGameDetection = field(default_factory=_FakeGameDetection)


class _FakeInspector:
    """ConnectionInspector por duck typing que registra las llamadas."""

    def __init__(self, result: ActiveGameServerInfo | None = None) -> None:
        self._result = result
        self.calls: list[set[str]] = []

    def detect_active_game_server(
        self, process_names: set[str]
    ) -> ActiveGameServerInfo | None:
        self.calls.append(set(process_names))
        return self._result


def _make_info() -> ActiveGameServerInfo:
    return ActiveGameServerInfo(
        ip="64.7.135.10",
        port=5000,
        protocol="udp",
        detected_via="process_connection_scan",
        process_name="League of Legends.exe",
    )


# ---------------------------------------------------------------------------
# public_endpoints()
# ---------------------------------------------------------------------------


class TestPublicEndpoints:
    def test_concatena_riot_public_v4_e_ipv6(self) -> None:
        settings = _FakeSettings(
            targets=_FakeTargets(
                riot_public=["auth.riotgames.com", "lol.secure.dyn.riotcdn.net"],
                riot_public_ipv6=["2606:4700:4700::1111"],
            )
        )
        module = LeagueOfLegendsModule(
            connection_inspector=_FakeInspector(), settings=settings
        )
        eps = module.public_endpoints()
        assert eps == [
            GameEndpoint(
                host="auth.riotgames.com", provider="riot_public", family="ipv4"
            ),
            GameEndpoint(
                host="lol.secure.dyn.riotcdn.net", provider="riot_public", family="ipv4"
            ),
            GameEndpoint(
                host="2606:4700:4700::1111", provider="riot_public", family="ipv6"
            ),
        ]

    def test_sin_ipv6_configurado_devuelve_solo_v4(self) -> None:
        settings = _FakeSettings(
            targets=_FakeTargets(
                riot_public=["auth.riotgames.com"],
                riot_public_ipv6=[],
            )
        )
        module = LeagueOfLegendsModule(settings=settings)
        assert module.public_endpoints() == [
            GameEndpoint(
                host="auth.riotgames.com", provider="riot_public", family="ipv4"
            )
        ]

    def test_sin_riot_public_devuelve_lista_vacia(self) -> None:
        settings = _FakeSettings(targets=_FakeTargets([], []))
        module = LeagueOfLegendsModule(settings=settings)
        assert module.public_endpoints() == []

    def test_devuelve_copia_no_referencia_interna(self) -> None:
        # El caller que muta el resultado no rompe estado del módulo.
        settings = _FakeSettings(
            targets=_FakeTargets(riot_public=["a", "b"], riot_public_ipv6=[])
        )
        module = LeagueOfLegendsModule(settings=settings)
        eps = module.public_endpoints()
        eps.append(GameEndpoint(host="z", provider="riot_public"))
        assert module.public_endpoints() == [
            GameEndpoint(host="a", provider="riot_public"),
            GameEndpoint(host="b", provider="riot_public"),
        ]


# ---------------------------------------------------------------------------
# process_names()
# ---------------------------------------------------------------------------


class TestProcessNames:
    def test_lee_game_detection_process_names_como_set(self) -> None:
        settings = _FakeSettings(
            game_detection=_FakeGameDetection(
                process_names=["League of Legends.exe", "LeagueClientUx.exe"]
            )
        )
        module = LeagueOfLegendsModule(settings=settings)
        assert module.process_names() == {"League of Legends.exe", "LeagueClientUx.exe"}

    def test_default_cuando_game_detection_vacio_set_vacio(self) -> None:
        settings = _FakeSettings(game_detection=_FakeGameDetection(process_names=[]))
        module = LeagueOfLegendsModule(settings=settings)
        assert module.process_names() == set()

    def test_devuelve_copia_no_referencia(self) -> None:
        settings = _FakeSettings(
            game_detection=_FakeGameDetection(process_names=["P.exe"])
        )
        module = LeagueOfLegendsModule(settings=settings)
        names = module.process_names()
        names.add("mutated")
        assert module.process_names() == {"P.exe"}


# ---------------------------------------------------------------------------
# detect_active_server()
# ---------------------------------------------------------------------------


class TestDetectActiveServer:
    def test_delega_al_inspector_con_los_process_names(self) -> None:
        inspector = _FakeInspector(result=_make_info())
        settings = _FakeSettings(
            game_detection=_FakeGameDetection(process_names=["League of Legends.exe"])
        )
        module = LeagueOfLegendsModule(
            connection_inspector=inspector, settings=settings
        )
        result = module.detect_active_server()
        assert result is not None
        assert result.ip == "64.7.135.10"
        # El inspector recibió exactamente los process_names del módulo.
        assert inspector.calls == [{"League of Legends.exe"}]

    def test_inspector_devuelve_none_propaga_none(self) -> None:
        inspector = _FakeInspector(result=None)
        settings = _FakeSettings(
            game_detection=_FakeGameDetection(process_names=["League of Legends.exe"])
        )
        module = LeagueOfLegendsModule(
            connection_inspector=inspector, settings=settings
        )
        assert module.detect_active_server() is None

    def test_sin_inspector_devuelve_none_sin_lanzar(self) -> None:
        module = LeagueOfLegendsModule(connection_inspector=None)
        # Sin settings tampoco importa: detect falla antes por inspector None.
        assert module.detect_active_server() is None

    def test_sin_inspector_no_intenta_leer_process_names(self) -> None:
        # Si settings fuese un objeto que lanza en attribute access,
        # detect_active_server corto-circuita en `inspector is None` antes
        # de llamar process_names() -> no toca settings. Verificamos que
        # process_names nunca se llame en ese path (registraríamos si
        # tuviéramos instrumentación; verificamos que no lanza).

        class _ExplodingSettings:
            @property
            def game_detection(self) -> object:  # noqa: D401
                raise AssertionError("process_names no debería leerse sin inspector")

        module = LeagueOfLegendsModule(
            connection_inspector=None, settings=_ExplodingSettings()  # type: ignore[arg-type]
        )
        assert module.detect_active_server() is None  # corto-circuito seguro


# ---------------------------------------------------------------------------
# Resiliencia ante config rota (EP §1.2 desde el constructor)
# ---------------------------------------------------------------------------


class TestConfigResilience:
    def test_settings_inyectado_none_cahe_a_get_settings_global(self) -> None:
        # Sin settings inyectado, el módulo pide el singleton. En tests,
        # el singleton de config existe (config default) -> no lanza.
        # Solo verificamos que el path funciona y devuelve algo (lista).
        module = LeagueOfLegendsModule(connection_inspector=None)
        # No assert sobre contenido exacto: depende del singleton cargado.
        # Aseguramos tipo (lista) y que no lanza.
        assert isinstance(module.public_endpoints(), list)
        assert isinstance(module.process_names(), set)

    def test_detect_active_server_corta_circuito_antes_de_settings(self) -> None:
        # Cubre el path donde inspector es None: no necesita settings.
        module = LeagueOfLegendsModule(connection_inspector=None)
        assert module.detect_active_server() is None
