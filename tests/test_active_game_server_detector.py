"""Tests unitarios de `diagnostics/riot/active_game_server_detector`.

No tocan psutil ni procesos reales (EP §4). Inyecto un `ProcessEnumerator`
falso que devuelve una lista de objetos `FakeProc` prefabricados. Cubre:

- Caso feliz: proceso del juego con UDP a IP publica -> ActiveGameServerInfo.
- Filtrado de IPs privadas (RFC1918/loopback/link-local/CGNAT/multicast/TEST-NET).
- Sin proceso del juego corriendo -> None sin error.
- Proceso sin conexiones UDP -> None.
- Proceso solo con conexiones locales (UDP a 127.0.0.1 / 192.168.x) -> None.
- Proceso con mix local+publica -> devuelve la publica.
- `psutil.AccessDenied` en `net_connections` -> None (degrada, no crashea).
- `psutil.NoSuchProcess` en `net_connections` -> None/siguiente proceso.
- `process_names` vacio -> None temprano.
- Falla total del `process_iter` (enumerator lanza) -> None.

Tambien tests puros de la funccion `is_public_ipv4` (casos borde).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pytest

from gnd.diagnostics.riot.active_game_server_detector import (
    ActiveGameServerDetector,
    is_public_ipv4,
)

# ---------------------------------------------------------------------------
# Fakes que emulant la API de psutil.Process
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeAddr:
    ip: str
    port: int


@dataclass(frozen=True)
class _FakeConn:
    raddr: _FakeAddr | None


class _FakeProc:
    """Proceso falso con .info y .net_connections configurable."""

    def __init__(
        self,
        name: str | None,
        pid: int,
        conns: list[_FakeConn] | None = None,
        raise_on_conns: type[Exception] | None = None,
    ) -> None:
        self.info = {"name": name, "pid": pid}
        self._conns = conns if conns is not None else []
        self._raise = raise_on_conns

    def net_connections(self, kind: str) -> list[_FakeConn]:
        assert kind == "udp", f"TestFakeProc.net_connections: kind={kind!r} != 'udp'"
        if self._raise is not None:
            raise self._raise(f"fake raise en net_connections de {self.info}")
        return list(self._conns)


class _FakeEnumerator:
    """ProcessEnumerator falso: lista de procesos prefabricada."""

    def __init__(self, procs: Iterable[_FakeProc]) -> None:
        # Devuelve una lista (no generator) — suficiente para tests; la
        # API real devuelve un generator pero el Protocol solo requiere
        # que sea iterable.
        self._procs = list(procs)
        self.calls: list[list[str]] = []

    def __call__(self, attrs: list[str]) -> list[_FakeProc]:
        self.calls.append(list(attrs))
        return list(self._procs)


class _RaisingEnumerator:
    """Enumerator que simula psutil.process_iter fallando a nivel sistema."""

    def __init__(self, exc: type[Exception]) -> None:
        self._exc = exc

    def __call__(self, attrs: list[str]) -> list[_FakeProc]:
        raise self._exc("fake raise de process_iter")


class _FakeRiotPublicProvider:
    """Fake de RiotPublicHostsProvider para tests sin config/DNS real."""

    def __init__(self, hostnames: list[str] | None = None) -> None:
        self._hostnames = hostnames if hostnames is not None else []

    def get_hostnames(self) -> list[str]:
        return list(self._hostnames)


# Excepciones falsas con el mismo nombre que las reales de psutil —
# el detector brancha por `type(exc).__name__` que contiene "AccessDenied"
# o "NoSuchProcess".
class AccessDenied(Exception):
    pass


class NoSuchProcess(Exception):
    pass


class ZombieProcess(Exception):
    pass


# ---------------------------------------------------------------------------
# Helper para tests que no prueban anti-telemetria: inyecta un provider
# vacio para que el detector NO resuelva DNS real (Regla de Oro 2.1).
# Los tests que SI prueban anti-telemetria inyectan su propio provider.
# ---------------------------------------------------------------------------


def _make_detector(procs: list[_FakeProc]) -> ActiveGameServerDetector:
    """Construye un detector con ProcessEnumerator fake y SIN exclusion.

    Para tests de anti-telemetria, construir el detector a mano e inyectar
    `_FakeRiotPublicProvider([...])` con las IPs a excluir.
    """
    return ActiveGameServerDetector(
        process_enumerator=_FakeEnumerator(procs),
        riot_public_provider=_FakeRiotPublicProvider([]),
    )


# ---------------------------------------------------------------------------
# Tests de is_public_ipv4 (filtrado puro)
# ---------------------------------------------------------------------------


class TestIsPublicIpv4:
    @pytest.mark.parametrize(
        "ip,expected",
        [
            # Publicas reales
            ("8.8.8.8", True),
            ("1.1.1.1", True),
            ("9.9.9.9", True),
            ("104.16.119.50", True),  # Cloudflare / Riot actual
            ("64.7.135.1", True),
            ("172.32.0.1", True),  # fuera del rango 172.16/12
            ("172.15.0.1", True),
            ("255.255.255.255", True),  # broadcast no esta en nuestro filtro
            # Loopback
            ("127.0.0.1", False),
            ("127.255.255.254", False),
            ("127.0.0.53", False),  # systemd-resolved local
            # RFC1918
            ("10.0.0.1", False),
            ("10.255.255.255", False),
            ("192.168.0.1", False),
            ("192.168.1.100", False),
            ("172.16.0.1", False),
            ("172.31.255.255", False),
            ("172.20.10.5", False),
            # Link-local
            ("169.254.1.1", False),
            ("169.254.0.0", False),
            # CGNAT
            ("100.64.0.1", False),
            ("100.127.255.255", False),
            # TEST-NET (RFC 5737) — reservadas para doc, no ruteables
            ("192.0.2.1", False),
            ("198.51.100.1", False),
            # Multicast
            ("224.0.0.1", False),
            ("239.255.255.1", False),
            # No-IP / malformadas
            ("not_an_ip", False),
            ("", False),
            ("8.8.8", False),
            ("8.8.8.8.8", False),
            ("999.999.999.999", False),  # octetos invalidos
            ("256.1.1.1", False),
        ],
    )
    def test_casos(self, ip: str, expected: bool) -> None:
        assert is_public_ipv4(ip) is expected


# ---------------------------------------------------------------------------
# Tests de ActiveGameServerDetector — caso feliz
# ---------------------------------------------------------------------------


class TestDetectActiveGameServerHappyPath:
    def test_proceso_lol_con_udp_publica_devuelve_info(self) -> None:
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1234,
            conns=[
                _FakeConn(_FakeAddr("127.0.0.1", 51820)),  # local, ignorar
                _FakeConn(_FakeAddr("64.7.135.10", 5000)),  # publica
            ],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is not None
        assert info.ip == "64.7.135.10"
        assert info.port == 5000
        assert info.protocol == "udp"
        assert info.detected_via == "process_connection_scan"
        assert info.process_name == "League of Legends.exe"

    def test_varios_procesos_devuelve_el_primero_matching(self) -> None:
        unrelated = _FakeProc(name="chrome.exe", pid=1, conns=[])
        lol = _FakeProc(
            name="League of Legends.exe",
            pid=2,
            conns=[_FakeConn(_FakeAddr("64.7.135.10", 5000))],
        )
        det = _make_detector([unrelated, lol])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is not None
        assert info.ip == "64.7.135.10"
        assert info.process_name == "League of Legends.exe"

    def test_respeta_el_set_de_process_names(self) -> None:
        # Si pido buscar "Valorant.exe" y no esta, None.
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[_FakeConn(_FakeAddr("64.7.135.10", 5000))],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"Valorant.exe"})
        assert info is None

    def test_attrs_pedidos_al_enumerator_son_name_y_pid(self) -> None:
        proc = _FakeProc(name="League of Legends.exe", pid=1, conns=[])
        enum = _FakeEnumerator([proc])
        det = ActiveGameServerDetector(
            process_enumerator=enum,
            riot_public_provider=_FakeRiotPublicProvider([]),
        )
        det.detect_active_game_server({"League of Legends.exe"})
        assert enum.calls == [["name", "pid"]]


# ---------------------------------------------------------------------------
# Tests: sin proceso / sin conexiones / solo locales -> None
# ---------------------------------------------------------------------------


class TestDetectActiveGameServerNoMatch:
    def test_sin_procesos_devuelve_none(self) -> None:
        det = _make_detector([])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_proceso_matching_sin_conexiones_devuelve_none(self) -> None:
        proc = _FakeProc(name="League of Legends.exe", pid=1, conns=[])
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_proceso_con_solo_conexiones_locales_devuelve_none(self) -> None:
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[
                _FakeConn(_FakeAddr("127.0.0.1", 51820)),
                _FakeConn(_FakeAddr("192.168.1.10", 5000)),
                _FakeConn(_FakeAddr("10.0.0.5", 5000)),
                _FakeConn(_FakeAddr("169.254.1.1", 5000)),
                _FakeConn(_FakeAddr("100.64.0.5", 5000)),
            ],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_conexiones_con_raddr_none_se_ignoran(self) -> None:
        # listening sockets tienen raddr=None
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[
                _FakeConn(None),
                _FakeConn(None),
            ],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_conexiones_con_raddr_tupla_vacia_se_ignoran(self) -> None:
        # psutil 6.x/7.x: raddr puede ser () (regla de Oro 6.6).
        # NO debe lanzar AttributeError.
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[
                _FakeConn(raddr=()),  # tuple vacia, NO None
                _FakeConn(raddr=("127.0.0.1", 1234)),  # tupla plana 2 items
                _FakeConn(raddr=("192.168.1.1", 53)),
            ],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        # Todas locales/invalidas -> None, pero NO debe crashear.
        assert info is None

    def test_raddr_como_tupla_plana_con_ip_publica_se_devuelve(self) -> None:
        # psutil polimorfico (Regla de Oro 6.6): raddr como tupla (ip, port).
        # El detector debe normalizar y devolver la IP publica correctamente.
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[
                _FakeConn(raddr=()),  # listening, ignorar
                _FakeConn(raddr=("127.0.0.1", 1234)),  # local, ignorar
                _FakeConn(raddr=("64.7.135.10", 5000)),  # publica tupla plana
            ],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is not None
        assert info.ip == "64.7.135.10"
        assert info.port == 5000

    def test_ip_publica_despues_de_varias_locales_se_devuelve(self) -> None:
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[
                _FakeConn(None),
                _FakeConn(_FakeAddr("127.0.0.1", 1234)),
                _FakeConn(_FakeAddr("192.168.0.5", 53)),
                _FakeConn(_FakeAddr("64.7.135.10", 5000)),  # publica (no riot)
            ],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is not None
        assert info.ip == "64.7.135.10"
        assert info.port == 5000

    def test_process_names_vacio_devuelve_none_sin_llamar_enumerator(self) -> None:
        # Si el set de nombres esta vacio, no hay nada que buscar.
        enum = _FakeEnumerator([_FakeProc(name="x", pid=1)])
        det = ActiveGameServerDetector(
            process_enumerator=enum,
            riot_public_provider=_FakeRiotPublicProvider([]),
        )
        info = det.detect_active_game_server(set())
        assert info is None
        # El enumerator no se llama (devuelve temprano)
        assert enum.calls == []

    def test_name_none_en_info_se_ignora(self) -> None:
        # Un proceso que psutil no pudo leer el nombre -> name=None
        proc = _FakeProc(
            name=None,
            pid=1,
            conns=[_FakeConn(_FakeAddr("8.8.8.8", 5000))],
        )
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None


# ---------------------------------------------------------------------------
# Tests: manejo de errores — AccessDenied / NoSuchProcess / Zombie
# ---------------------------------------------------------------------------


class TestDetectActiveGameServerErrors:
    def test_access_denied_en_unproceso_sigue_al_siguiente(self) -> None:
        denegado = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            raise_on_conns=AccessDenied,
        )
        bueno = _FakeProc(
            name="League of Legends.exe",
            pid=2,
            conns=[_FakeConn(_FakeAddr("64.7.135.10", 5000))],
        )
        det = _make_detector([denegado, bueno])
        info = det.detect_active_game_server({"League of Legends.exe"})
        # El primero lanza AccessDenied (skip), el segundo funciona.
        assert info is not None
        assert info.ip == "64.7.135.10"
        assert info.process_name == "League of Legends.exe"

    def test_access_denied_en_todos_devuelve_none(self) -> None:
        d1 = _FakeProc(name="League of Legends.exe", pid=1, raise_on_conns=AccessDenied)
        d2 = _FakeProc(name="League of Legends.exe", pid=2, raise_on_conns=AccessDenied)
        det = _make_detector([d1, d2])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_nosuchprocess_sigue_al_siguiente(self) -> None:
        muerto = _FakeProc(
            name="League of Legends.exe", pid=1, raise_on_conns=NoSuchProcess
        )
        vivo = _FakeProc(
            name="League of Legends.exe",
            pid=2,
            conns=[_FakeConn(_FakeAddr("64.7.135.10", 5000))],
        )
        det = _make_detector([muerto, vivo])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is not None
        assert info.ip == "64.7.135.10"

    def test_zombieprocess_se_cubre_en_rama_generica(self) -> None:
        zombie = _FakeProc(
            name="League of Legends.exe", pid=1, raise_on_conns=ZombieProcess
        )
        det = _make_detector([zombie])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_excepcion_generica_de_net_connections_devuelve_none(self) -> None:
        # Cualquier otra excepcion (runtime, OOM, etc.) no debe burbujear
        class _Weird(Exception):
            pass

        proc = _FakeProc(name="League of Legends.exe", pid=1, raise_on_conns=_Weird)
        det = _make_detector([proc])
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None

    def test_falla_total_de_process_iter_devuelve_none(self) -> None:
        det = ActiveGameServerDetector(
            process_enumerator=_RaisingEnumerator(AccessDenied),
            riot_public_provider=_FakeRiotPublicProvider([]),
        )
        info = det.detect_active_game_server({"League of Legends.exe"})
        assert info is None


# ---------------------------------------------------------------------------
# Tests de ActiveGameServerInfo exportado
# ---------------------------------------------------------------------------


class TestDetectorImplementaProtocol:
    def test_es_subtipo_de_connection_inspector(self) -> None:
        # Structural typing: Protocol con @runtime_checkable
        from gnd.domain.ports.connection_inspector import ConnectionInspector

        det = _make_detector([])
        # isinstance con Protocol runtime_checkable solo valida que tiene
        # el atributo/metodo, no signature — pero suficiente para la
        # derivacion L de EP §2.
        assert isinstance(det, ConnectionInspector)

    def test_fake_y_real_son_intercambiables(self) -> None:
        # Liskov: el consumidor debe poder usar el fake o el real sin
        # notar diferencia. Llamamos la misma firma.
        from gnd.domain.fakes.fake_connection_inspector import (
            FakeConnectionInspector,
        )

        fake = FakeConnectionInspector()
        real = _make_detector([])
        # Ambos aceptan un set de nombres y devuelven None o info.
        assert fake.detect_active_game_server({"x"}) is None
        assert real.detect_active_game_server({"x"}) is None


# ---------------------------------------------------------------------------
# Tests anti-telemetria (exclusion de IPs riot_public resueltas)
# ---------------------------------------------------------------------------


class TestAntiTelemetriaExclusion:
    """Tests de exclusion de IPs de riot_public (Cloudflare/Akamai telemetria)."""

    def test_dos_udps_publicas_una_riotpublic_otra_nueva_devuelve_nueva(
        self,
    ) -> None:
        """Proceso con 2 UDP publicas: una IP de riot_public, otra distinta.

        El detector debe EXCLUIR la que coincide con riot_public y
        devolver la otra (el server real), NO la primera que encuentra.
        """
        riot_ip = "104.16.119.50"  # Cloudflare / auth.riotgames.com
        game_server_ip = "64.7.135.10"  # IP hipotetica del game server real

        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1234,
            conns=[
                _FakeConn(_FakeAddr(riot_ip, 443)),  # Telemetria a Cloudflare
                _FakeConn(_FakeAddr(game_server_ip, 5000)),  # Game server real
            ],
        )
        # Inyectar provider que resuelve riot_public a la IP de telemetria
        det = ActiveGameServerDetector(
            process_enumerator=_FakeEnumerator([proc]),
            riot_public_provider=_FakeRiotPublicProvider([riot_ip]),
        )
        info = det.detect_active_game_server({"League of Legends.exe"})

        assert info is not None
        assert info.ip == game_server_ip
        assert info.port == 5000
        assert info.protocol == "udp"
        assert info.detected_via == "process_connection_scan"

    def test_todas_las_udps_publicas_son_riotpublic_devuelve_none(
        self,
    ) -> None:
        """Si TODAS las conexiones UDP publicas coinciden con riot_public -> None.

        Esto evita un falso positivo: si el detector solo ve telemetria/CDN
        (ej. partida no iniciada aun, o solo telemetria activa), no debe
        reportar una IP de Cloudflare como si fuera el game server.
        """
        riot_ip = "104.16.119.50"
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[
                _FakeConn(_FakeAddr(riot_ip, 443)),
                _FakeConn(_FakeAddr(riot_ip, 5222)),  # Otra conexion a Cloudflare
            ],
        )
        det = ActiveGameServerDetector(
            process_enumerator=_FakeEnumerator([proc]),
            riot_public_provider=_FakeRiotPublicProvider([riot_ip]),
        )
        info = det.detect_active_game_server({"League of Legends.exe"})

        assert info is None, (
            "Detector no debe devolver IP de riot_public como game server "
            "(falso positivo de telemetria)"
        )

    def test_hostname_riotpublic_que_no_resuelve_se_ignora_sin_crashear(
        self,
    ) -> None:
        """Hostname en riot_public que no resuelve a IP -> se ignora, no crashea.

        El detector no debe fallar si un hostname de config no resuelve
        (rotacion de CDN, error DNS temporal, etc.). Debe comportarse como
        si ese hostname no existiera en la lista.
        """
        proc = _FakeProc(
            name="League of Legends.exe",
            pid=1,
            conns=[_FakeConn(_FakeAddr("64.7.135.10", 5000))],
        )
        # Hostname que no existe / no resuelve
        det = ActiveGameServerDetector(
            process_enumerator=_FakeEnumerator([proc]),
            riot_public_provider=_FakeRiotPublicProvider(
                ["noexiste.invalido.riotgames.com"]
            ),
        )
        info = det.detect_active_game_server({"League of Legends.exe"})

        # La IP real del game server debe detectarse correctamente
        assert info is not None
        assert info.ip == "64.7.135.10"
