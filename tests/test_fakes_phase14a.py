"""Tests de los Fakes y Protocols nuevos de Fase 14.0a.

Cubre:
- ``FakeLockfileReader``: programa/recupera/reset contadores de calls.
- ``FakeLcuClient``: idem + recibe el ``LockfileData`` correcto.
- ``LockfileReader`` Protocol: ``runtime_checkable`` reconoce el fake.
- ``LcuClient`` Protocol: ``runtime_checkable`` reconoce el fake.
- Cualquier objeto con la firma correcta es aceptado (duck typing de
  Protocol sin acoplamiento explícito al fake).
"""

from gnd.domain.fakes.fake_lcu_client import FakeLcuClient
from gnd.domain.fakes.fake_lockfile_reader import FakeLockfileReader
from gnd.domain.ports.lcu_client import LcuClient
from gnd.domain.ports.lockfile_reader import LockfileReader
from gnd.models.gameflow_session import GameflowSession
from gnd.models.lockfile_data import LockfileData


class TestFakeLockfileReader:
    def test_default_devuelve_none(self) -> None:
        r = FakeLockfileReader()
        assert r.read() is None
        assert r.read_calls == 1

    def test_programado_devuelve_lockfile(self) -> None:
        r = FakeLockfileReader()
        lf = LockfileData(
            process_name="LC",
            pid=123,
            port=5000,
            password="tok",
            protocol="remoting-auth-token",
        )
        r.set_result(lf)
        assert r.read() is lf

    def test_progama_none_reset(self) -> None:
        """Después de setear un lockfile, set_result(None) lo resetea."""
        r = FakeLockfileReader()
        lf = LockfileData(
            process_name="LC", pid=1, port=1, password="t", protocol="ssl"
        )
        r.set_result(lf)
        assert r.read() is lf
        r.set_result(None)
        assert r.read() is None

    def test_conta_calls_acumula(self) -> None:
        r = FakeLockfileReader()
        r.read()
        r.read()
        r.read()
        assert r.read_calls == 3


class TestFakeLcuClient:
    def test_default_devuelve_none(self) -> None:
        c = FakeLcuClient()
        lf = LockfileData(
            process_name="LC", pid=1, port=1, password="t", protocol="ssl"
        )
        assert c.get_gameflow_session(lf) is None
        assert len(c.get_session_calls) == 1
        assert c.get_session_calls[0] is lf

    def test_programado_devuelve_session(self) -> None:
        c = FakeLcuClient()
        sess = GameflowSession(
            phase="InProgress",
            region_tag="LA1",
            server_ip="1.2.3.4",
            server_port=5000,
        )
        c.set_result(sess)
        lf = LockfileData(
            process_name="LC",
            pid=123,
            port=5000,
            password="tok",
            protocol="remoting-auth-token",
        )
        assert c.get_gameflow_session(lf) is sess
        assert c.get_session_calls[-1] is lf


class TestProtocolsRuntimeCheckable:
    def test_lockfile_reader_reconoce_fake(self) -> None:
        r: LockfileReader = FakeLockfileReader()
        # runtime_checkable permite isinstance contra el Protocol
        assert isinstance(r, LockfileReader)

    def test_lcu_client_reconoce_fake(self) -> None:
        c: LcuClient = FakeLcuClient()
        assert isinstance(c, LcuClient)

    def test_lockfile_reader_reconoce_objeto_sin_hom(self) -> None:
        """Objeto cualquiera SIN el método ``read`` NO es LockfileReader."""
        assert not isinstance(42, LockfileReader)
        assert not isinstance("hola", LockfileReader)

    def test_lcu_client_reconoce_objeto_sin_hom(self) -> None:
        """Objeto cualquiera SIN ``get_gameflow_session`` NO es LcuClient."""
        assert not isinstance(object(), LcuClient)
