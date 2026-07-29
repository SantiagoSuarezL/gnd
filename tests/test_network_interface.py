"""Tests de la feature Fase 12a.3 — Detección Wi-Fi/Ethernet.

Estructura:
1. Modelos (`NetworkInterfaceSnapshot` invariantes).
2. Fake (`FakeNetworkInterfaceInspector` contract).
3. Adaptador real — parser de netsh (`_parse_netsh_output`) con
   fixtures EN/ES de outputs reales/semánticamente reales.
4. Adaptador real — `_detect_default_route_iface_name_windows` con
   psutil/socket fakes (no dependiente de la red del host).
5. Orquestador (`RunFullDiagnostics` etapa interface serial).
6. Persistencia SQLite (`interface_snapshots` tabla).

Verificación empírica in-vivo ejecutada en Windows 11 ES locale:
adaptador real contra `netsh wlan show interfaces` devolvió
`type=ETHERNET, name="Ethernet 2"` correctamente cuando la default-route
iface era Ethernet (output de netsh: Wi-Fi desconectada, sin SSID).
Ver `session_log` para el detalle del dictamen.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import (
    SqliteDiagnosticsRepository,
)
from gnd.domain.fakes import (
    FakeDiagnosticsRepository,
    FakeDnsResolver,
    FakeNetworkInterfaceInspector,
    FakePingRunner,
    FakeTracerouteRunner,
)
from gnd.models.network_interface import (
    InterfaceType,
    NetworkInterfaceSnapshot,
)
from gnd.network.real_network_interface_inspector import _parse_netsh_output

# ---------------------------------------------------------------------------
# 1. NetworkInterfaceSnapshot invariantes
# ---------------------------------------------------------------------------


class TestNetworkInterfaceSnapshotInvariants:
    def test_wifi_implies_ssid_non_none(self):
        with pytest.raises(ValueError, match="wifi_ssid no puede ser None"):
            NetworkInterfaceSnapshot(
                type=InterfaceType.WIFI,
                name="Wi-Fi",
                is_default_route=True,
                wifi_ssid=None,  # BAD — WIFI exige ssid
                wifi_signal_dbm=-65.0,
                error=None,
            )

    def test_ethernet_forbids_wifi_ssid(self):
        with pytest.raises(ValueError, match="wifi_ssid/wifi_signal_dbm"):
            NetworkInterfaceSnapshot(
                type=InterfaceType.ETHERNET,
                name="eth0",
                is_default_route=True,
                wifi_ssid="Shouldn't be here",  # BAD para ETH
                wifi_signal_dbm=None,
                error=None,
            )

    def test_ethernet_forbids_signal_dbm(self):
        with pytest.raises(ValueError, match="wifi_ssid/wifi_signal_dbm"):
            NetworkInterfaceSnapshot(
                type=InterfaceType.ETHERNET,
                name="eth0",
                is_default_route=True,
                wifi_ssid=None,
                wifi_signal_dbm=-70.0,  # BAD para ETH
                error=None,
            )

    def test_other_forbids_wifi_fields(self):
        with pytest.raises(ValueError, match="wifi_ssid/wifi_signal_dbm"):
            NetworkInterfaceSnapshot(
                type=InterfaceType.OTHER,
                name="vpn0",
                is_default_route=False,
                wifi_ssid="x",  # BAD para OTHER
                wifi_signal_dbm=None,
                error=None,
            )

    def test_signal_dbm_must_be_negative(self):
        with pytest.raises(ValueError, match="wifi_signal_dbm debe ser negativo"):
            NetworkInterfaceSnapshot(
                type=InterfaceType.WIFI,
                name="Wi-Fi",
                is_default_route=True,
                wifi_ssid="ok",
                wifi_signal_dbm=50.0,  # positivo ¡invalido!
                error=None,
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name no puede ser vacío"):
            NetworkInterfaceSnapshot(
                type=InterfaceType.OTHER,
                name="",
                is_default_route=False,
                wifi_ssid=None,
                wifi_signal_dbm=None,
                error=None,
            )

    def test_wifi_with_empty_ssid_is_allowed(self):
        # Algunos OS exponen SSID vacio cuando connected pero ssid oculto.
        snap = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="",  # OK — WIFI solo exige str (no None)
            wifi_signal_dbm=-55.0,
            error=None,
        )
        assert snap.type is InterfaceType.WIFI
        assert snap.wifi_ssid == ""

    def test_frozen_is_immutable(self):
        from dataclasses import FrozenInstanceError

        snap = NetworkInterfaceSnapshot(
            type=InterfaceType.ETHERNET,
            name="eth0",
            is_default_route=True,
            wifi_ssid=None,
            wifi_signal_dbm=None,
            error=None,
        )
        with pytest.raises(FrozenInstanceError):
            snap.name = "otro"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. FakeNetworkInterfaceInspector
# ---------------------------------------------------------------------------


class TestFakeNetworkInterfaceInspector:
    def test_default_returns_other_with_error(self):
        ins = FakeNetworkInterfaceInspector()
        snap = ins.inspect()
        assert snap.type is InterfaceType.OTHER
        assert "FakeNetworkInterfaceInspector" in (snap.error or "")
        assert len(ins.calls) == 1

    def test_set_snapshot_overrides(self):
        ins = FakeNetworkInterfaceInspector()
        configured = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="MyNet",
            wifi_signal_dbm=-60.0,
            error=None,
        )
        ins.set_snapshot(configured)
        snap = ins.inspect(default_route_iface_hint="Wi-Fi")
        assert snap.type is InterfaceType.WIFI
        assert snap.wifi_ssid == "MyNet"
        assert ins.calls[0]["default_route_iface_hint"] == "Wi-Fi"


# ---------------------------------------------------------------------------
# 3. Parser de netsh (_parse_netsh_output)
# ---------------------------------------------------------------------------

# Fixture de output de netsh en Windows 11 ES con Wi-Fi desconectada
# (output real capturado de la máquina de desarrollo).
NETSH_ES_DISCONNECTED = """
Hay 1 interfaz en el sistema:

    Nombre                   : Wi-Fi
    Descripción            : MediaTek Wi-Fi 6E MT7902 Wireless LAN Card
    GUID                   : 67a9fe21-c3a4-42f5-bf1d-b39579817ec2
    Dirección       : 10:68:38:0d:35:b2
    Tipo de interfaz         : Principal
    Estado                  : desconectado
    Estado de radio           : Hardware Activado
                             Software Desactivado
"""

# Output ES simulado con Wi-Fi conectada (basado en texto del OS Windows).
NETSH_ES_CONNECTED = """
Hay 1 interfaz en el sistema:

    Nombre                   : Wi-Fi
    Descripción            : MediaTek Wi-Fi 6E MT7902 Wireless LAN Card
    Estado                  : conectado
    SSID                    : CasaDeSantiago
    BSSID                   : aa:bb:cc:dd:ee:ff
    Tipo de red              : Infraestructura
    Autenticación            : WPA2-Personal
    Cifrado                  : CCMP
    Señal                   : 87%
"""

# Output EN simulado con Wi-Fi conectada.
NETSH_EN_CONNECTED = """
There is 1 interface on the system:

    Name                     : Wi-Fi
    Description              : Intel Wi-Fi 6 AX201
    State                    : connected
    SSID                     : HomeNetwork
    BSSID                    : aa:bb:cc:dd:ee:ff
    Network type             : Infrastructure
    Authentication           : WPA2-Personal
    Cipher                   : CCMP
    Signal                   : 73%
"""


class TestNetshParser:
    def test_disconnected_wifi_returns_other_without_hint(self):
        # Sin default_route_hint, sin SSID — no podemos inferir tipo.
        snap = _parse_netsh_output(NETSH_ES_DISCONNECTED, None)
        assert snap.type is InterfaceType.OTHER
        assert snap.error is not None
        assert snap.is_default_route is False

    def test_disconnected_wifi_returns_ethernet_with_hint(self):
        # Si sabemos que la default-route es Ethernet 2 -> el adaptador
        # Wi-Fi está desconectado pero hay Ethernet, tipo=ETHERNET.
        snap = _parse_netsh_output(NETSH_ES_DISCONNECTED, "Ethernet 2")
        assert snap.type is InterfaceType.ETHERNET
        assert snap.name == "Ethernet 2"
        assert snap.is_default_route is True
        assert snap.error is None

    def test_connected_es_produces_wifi_snapshot(self):
        snap = _parse_netsh_output(NETSH_ES_CONNECTED, "Wi-Fi")
        assert snap.type is InterfaceType.WIFI
        assert snap.wifi_ssid == "CasaDeSantiago"
        # 87% -> dBm = 87/2 - 100 = -56.5
        assert snap.wifi_signal_dbm == pytest.approx(-56.5)
        assert snap.error is None
        assert snap.name == "Wi-Fi"

    def test_connected_en_produces_wifi_snapshot(self):
        snap = _parse_netsh_output(NETSH_EN_CONNECTED, None)
        assert snap.type is InterfaceType.WIFI
        assert snap.wifi_ssid == "HomeNetwork"
        # 73% -> -63.5
        assert snap.wifi_signal_dbm == pytest.approx(-63.5)

    def test_empty_output_with_hint_returns_ethernet(self):
        snap = _parse_netsh_output("", "eth0")
        assert snap.type is InterfaceType.ETHERNET
        assert snap.name == "eth0"

    def test_empty_output_no_hint_returns_other(self):
        snap = _parse_netsh_output("", None)
        assert snap.type is InterfaceType.OTHER
        assert snap.error is not None

    def test_no_data_message_does_not_become_ssid(self):
        # ES-raro output "No hay datos disponibles" para SSID debe filtrarse.
        text = """
Hay 1 interfaz en el sistema:
    Estado                  : desconectado
    SSID                    : No hay datos disponibles
"""
        snap = _parse_netsh_output(text, "eth0")
        # SSID rechazado -> cae a ETHERNET con hint.
        assert snap.type is InterfaceType.ETHERNET
        assert snap.wifi_ssid is None


# ---------------------------------------------------------------------------
# 4. _detect_default_route_iface_name_windows — host-independiente
# ---------------------------------------------------------------------------


class TestDetectDefaultRouteIface:
    def test_returns_none_when_no_default_route_socket_raises(self, monkeypatch):
        # Si el socket.connect falla (sandbox), devuelve None sin lanzar.
        from gnd.network import real_network_interface_inspector as mod

        def boom(self, *a):
            raise OSError("boom")

        monkeypatch.setattr("socket.socket.connect", boom, raising=False)
        # socket.socket es la clase — patchear connect a nivel function.
        # monkeypatch.setattr socket.socket.connect intenta patchear la
        # clase completa — fallback: patchear todo el socket con un dummy.
        import socket as sock_module

        class BadSocket:
            def __init__(self, *a, **kw):
                pass

            def connect(self, *a):
                raise OSError("boom")

            def getsockname(self):
                return ("", 0)

            def close(self):
                pass

        monkeypatch.setattr(sock_module, "socket", BadSocket)
        assert mod._detect_default_route_iface_name_windows() is None

    def test_returns_iface_name_when_psutil_matches(self, monkeypatch):
        # Simula psutil.net_if_addrs con un iface "eth0" cuya IPv4 = local.
        import socket as sock_module

        from gnd.network import real_network_interface_inspector as mod

        class FakeSock:
            def __init__(self, *a, **kw):
                pass

            def connect(self, *a):
                pass

            def getsockname(self):
                return ("192.168.1.50", 0)

            def close(self):
                pass

        monkeypatch.setattr(sock_module, "socket", FakeSock)

        # Fake psutil: module with net_if_addrs returning dict.
        class FakeAddr:
            def __init__(self, family, address):
                self.family = family
                self.address = address

        class FakePsutil:
            @staticmethod
            def net_if_addrs():
                return {
                    "eth0": [FakeAddr(sock_module.AF_INET, "192.168.1.50")],
                    "wlan0": [FakeAddr(sock_module.AF_INET, "10.0.0.5")],
                }

        import sys

        monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
        result = mod._detect_default_route_iface_name_windows()
        assert result == "eth0"


# ---------------------------------------------------------------------------
# 5. Orquestador: etapa interface serial en RunFullDiagnostics.execute()
# ---------------------------------------------------------------------------


def _targets_basic():
    return DiagnosticTargets(
        gateway_ip="192.168.1.1",
        google_dns="8.8.8.8",
        cloudflare="1.1.1.1",
        quad9="9.9.9.9",
        riot_public=["auth.riotgames.com"],
        game_process_names={"League of Legends.exe"},
    )


def _params_with_interface(on: bool = True, hint: str | None = None):
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
        inspect_interface_enabled=on,
        default_route_iface_hint=hint,
    )


def _build_use_case(interface_inspector, repo=None):
    class NoopInspector:
        def detect_active_game_server(self, names):
            return None

    return RunFullDiagnostics(
        ping_runner=FakePingRunner(),
        traceroute_runner=FakeTracerouteRunner(),
        connection_inspector=NoopInspector(),
        repository=repo or FakeDiagnosticsRepository(),
        dns_resolver=FakeDnsResolver(),
        interface_inspector=interface_inspector,
    )


class TestRunFullDiagnosticsInterfaceStage:
    def test_disabled_skips_stage(self):
        inspector = FakeNetworkInterfaceInspector()
        uc = _build_use_case(inspector)
        run = uc.execute(
            _targets_basic(),
            _params_with_interface(on=False),
        )
        assert run.interface_snapshot is None
        assert len(inspector.calls) == 0

    def test_enabled_inspects_once_with_hint(self):
        inspector = FakeNetworkInterfaceInspector()
        snap = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="MyNet",
            wifi_signal_dbm=-55.0,
            error=None,
        )
        inspector.set_snapshot(snap)
        uc = _build_use_case(inspector)
        run = uc.execute(
            _targets_basic(),
            _params_with_interface(on=True, hint="Wi-Fi"),
        )
        assert run.interface_snapshot is snap
        assert inspector.calls[0]["default_route_iface_hint"] == "Wi-Fi"

    def test_buggy_inspector_does_not_abort_run(self):
        class BadInspector:
            def inspect(self, *, default_route_iface_hint=None):
                raise RuntimeError("oops")

        uc = _build_use_case(BadInspector())
        run = uc.execute(
            _targets_basic(),
            _params_with_interface(on=True),
        )
        # Belt-and-suspenders atrapa excepción -> snapshot None.
        assert run.interface_snapshot is None
        assert run.run_id  # la corrida finaliza bien

    def test_enabled_but_no_inspector_injected_skips_with_log(self):
        # composition_root mal hecho (no debería pasar) — feature enabled
        # pero el use case no tiene inspector. No aborta.
        uc = RunFullDiagnostics(
            ping_runner=FakePingRunner(),
            traceroute_runner=FakeTracerouteRunner(),
            connection_inspector=_NoopInspector(),
            repository=FakeDiagnosticsRepository(),
            dns_resolver=FakeDnsResolver(),
            interface_inspector=None,
        )
        run = uc.execute(
            _targets_basic(),
            _params_with_interface(on=True),
        )
        assert run.interface_snapshot is None


class _NoopInspector:
    def detect_active_game_server(self, names):
        return None


# ---------------------------------------------------------------------------
# 6. Persistencia SQLite interface_snapshots
# ---------------------------------------------------------------------------


class TestInterfaceSnapshotPersistence:
    def test_save_run_persists_interface_snapshot(self, tmp_path: Path):
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
        snap = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="MyNet",
            wifi_signal_dbm=-55.0,
            error=None,
        )
        run = DiagnosticRun(
            run_id="testrun02",
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
                headline="OK",
                explanation=["ok"],
                score=90,
                responsible_component="local",
            ),
            interface_snapshot=snap,
        )

        repo.save_run(run)
        conn = factory.create_connection()
        try:
            row = conn.execute(
                """SELECT type, name, is_default_route, wifi_ssid,
                          wifi_signal_dbm, error
                   FROM interface_snapshots WHERE run_id = ?""",
                ("testrun02",),
            ).fetchone()
            assert row is not None
            assert row[0] == "WIFI"
            assert row[1] == "Wi-Fi"
            assert row[2] == 1
            assert row[3] == "MyNet"
            assert row[4] == -55.0
            assert row[5] is None
        finally:
            conn.close()

    def test_save_run_without_snapshot_inserts_no_row(self, tmp_path: Path):
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
            run_id="testrun03",
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
                headline="OK",
                explanation=["ok"],
                score=90,
                responsible_component="local",
            ),
            interface_snapshot=None,  # feature off
        )

        repo.save_run(run)
        conn = factory.create_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM interface_snapshots WHERE run_id = ?",
                ("testrun03",),
            ).fetchone()
            assert row[0] == 0
        finally:
            conn.close()
