"""Tests unitarios de `network/real_ping_runner` con subprocess mockeado.

No tocan red ni socket real. Inyecto un `ProcessRunner` y mockeo
`tcp_syn_probe.probe` para cubrir las ramas FILTERED / UNREACHABLE /
TIMEOUT del fallback (EP §4: sin red en tests unitarios).
"""

import socket
from unittest.mock import patch

import pytest

from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.network import tcp_syn_probe
from gnd.network.real_ping_runner import RealPingRunner
from tests.conftest import load_fixture


class _StubProcess:
    """ProcessRunner falso: devuelve (stdout, stderr, rc) prefijados."""

    def __init__(self, stdout: str, stderr: str = "", rc: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._rc = rc

    def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]:
        return (self._stdout, self._stderr, self._rc)


def _tcp_open(*a: object, **kw: object) -> tcp_syn_probe.TcpSynOutcome:
    return tcp_syn_probe.TcpSynOutcome(tcp_syn_probe.TcpSynResult.OPEN, "open")


def _tcp_timeout(*a: object, **kw: object) -> tcp_syn_probe.TcpSynOutcome:
    return tcp_syn_probe.TcpSynOutcome(tcp_syn_probe.TcpSynResult.TIMEOUT, "tmo")


def _tcp_netunreach(*a: object, **kw: object) -> tcp_syn_probe.TcpSynOutcome:
    return tcp_syn_probe.TcpSynOutcome(
        tcp_syn_probe.TcpSynResult.NETWORK_UNREACHABLE, "netunreach"
    )


# --- Caso feliz ---


def test_success_produce_probe_result_success_con_stats() -> None:
    runner = RealPingRunner(process_runner=_StubProcess(load_fixture("linux_success")))
    r = runner.ping("8.8.8.8", "google_dns", "google", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.SUCCESS
    assert r.stats is not None
    assert r.stats.samples == 5
    assert r.stats.packet_loss_pct == 0.0
    assert 12.0 <= r.stats.avg_ms <= 14.0
    assert r.provider == "google"
    assert r.target_ip == "8.8.8.8"


def test_success_windows_formato() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_success"))
    )
    r = runner.ping("8.8.8.8", "google_dns", "google", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.SUCCESS
    assert r.stats is not None
    assert r.stats.samples == 5
    assert r.stats.min_ms == 10.0
    assert r.stats.max_ms == 13.0


# --- Perdida parcial -> SUCCESS con packet_loss > 0 ---


def test_partial_loss_sigue_siendo_success_con_loss_pct() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_partial_loss"))
    )
    r = runner.ping("192.168.1.1", "gateway", "local", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.SUCCESS
    assert r.stats is not None
    assert r.stats.packet_loss_pct == 40.0
    assert r.stats.samples == 3


# --- 100% ICMP loss + TCP open -> FILTERED ---


def test_icmp_loss_total_tcp_open_es_filtered() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_all_timeout"))
    )
    with patch("gnd.network.tcp_syn_probe.probe", side_effect=_tcp_open):
        r = runner.ping("104.160.136.3", "riot_public", "riot_public", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.FILTERED
    assert r.stats is None


def test_icmp_loss_total_tcp_rejected_es_filtered() -> None:
    def _rejected(*a: object, **kw: object) -> tcp_syn_probe.TcpSynOutcome:
        return tcp_syn_probe.TcpSynOutcome(tcp_syn_probe.TcpSynResult.REJECTED, "rst")

    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("linux_all_timeout"))
    )
    with patch("gnd.network.tcp_syn_probe.probe", side_effect=_rejected):
        r = runner.ping("104.160.136.3", "riot_public", "riot_public", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.FILTERED
    assert r.stats is None


# --- 100% ICMP loss + TCP fail -> UNREACHABLE / TIMEOUT ---


def test_icmp_unreachable_explicito_es_unreachable() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_host_unreachable"))
    )
    with patch("gnd.network.tcp_syn_probe.probe", side_effect=_tcp_timeout):
        r = runner.ping("10.255.255.1", "host", "local", 5, 1000)
    # error_letter="U" fuerza UNREACHABLE aunque TCP timeout.
    assert r.outcome is ProbeOutcomeKind.UNREACHABLE
    assert r.stats is None


def test_icmp_general_failure_es_unreachable() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_general_failure"))
    )
    with patch("gnd.network.tcp_syn_probe.probe", side_effect=_tcp_timeout):
        r = runner.ping("192.0.2.42", "host", "local", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.UNREACHABLE


def test_icmp_timeout_puro_tcp_timeout_es_timeout() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_all_timeout"))
    )
    with patch("gnd.network.tcp_syn_probe.probe", side_effect=_tcp_timeout):
        r = runner.ping("203.0.113.42", "host", "local", 5, 1000)
    # No error_letter + TCP timeout -> TIMEOUT (no UNREACHABLE).
    assert r.outcome is ProbeOutcomeKind.TIMEOUT
    assert r.stats is None


def test_tcp_network_unreachable_es_unreachable() -> None:
    runner = RealPingRunner(
        process_runner=_StubProcess(load_fixture("windows_all_timeout"))
    )
    with patch("gnd.network.tcp_syn_probe.probe", side_effect=_tcp_netunreach):
        r = runner.ping("203.0.113.42", "host", "local", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.UNREACHABLE


# --- subprocess que expira / ping inexistente ---


def test_subprocess_timeout_expired_devuelve_timeout() -> None:
    import subprocess

    class _Explodes:
        def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]:
            raise subprocess.TimeoutExpired(cmd=args, timeout=1.0)

    runner = RealPingRunner(process_runner=_Explodes())  # type: ignore[arg-type]
    r = runner.ping("8.8.8.8", "google_dns", "google", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.TIMEOUT
    assert r.stats is None


def test_subprocess_oserror_devuelve_unreachable() -> None:
    class _Explodes:
        def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]:
            raise OSError("ping not found")

    runner = RealPingRunner(process_runner=_Explodes())  # type: ignore[arg-type]
    r = runner.ping("8.8.8.8", "google_dns", "google", 5, 1000)
    assert r.outcome is ProbeOutcomeKind.UNREACHABLE


# --- Invariantes del modelo ---


def test_resultado_es_probe_result_inmutable() -> None:
    from dataclasses import FrozenInstanceError

    runner = RealPingRunner(process_runner=_StubProcess(load_fixture("linux_success")))
    r = runner.ping("8.8.8.8", "google_dns", "google", 5, 1000)
    assert isinstance(r, ProbeResult)
    with pytest.raises(FrozenInstanceError):
        r.outcome = ProbeOutcomeKind.TIMEOUT  # type: ignore[misc]


def test_build_args_linux_formato() -> None:
    with patch("gnd.network.real_ping_runner.platform.system", return_value="Linux"):
        runner = RealPingRunner()
        args = runner._build_args("8.8.8.8", 5, 1000)  # noqa: SLF001
    assert "ping" in args
    assert "-c" in args and "5" in args
    assert "8.8.8.8" in args


def test_build_args_timeout_minimo_1s_linux() -> None:
    with patch("gnd.network.real_ping_runner.platform.system", return_value="Linux"):
        runner = RealPingRunner()
        # timeout_ms 100 -> max(1, 0) = 1s (no 0).
        args = runner._build_args("1.1.1.1", 1, 100)  # noqa: SLF001
    idx = args.index("-W")
    assert args[idx + 1] == "1"


def test_build_args_windows_formato() -> None:
    with patch("gnd.network.real_ping_runner.platform.system", return_value="Windows"):
        runner = RealPingRunner()
        args = runner._build_args("8.8.8.8", 5, 1000)  # noqa: SLF001
    assert "ping" in args
    assert "-n" in args and "5" in args
    assert "-w" in args and "1000" in args
    assert "8.8.8.8" in args


def test_build_args_windows_timeout_unidad_ms() -> None:
    with patch("gnd.network.real_ping_runner.platform.system", return_value="Windows"):
        runner = RealPingRunner()
        args = runner._build_args("1.1.1.1", 1, 500)  # noqa: SLF001
    idx = args.index("-w")
    assert args[idx + 1] == "500"


# --- DNS resolution ---


def test_resolve_target_literal_ipv4_passthrough() -> None:
    runner = RealPingRunner(process_runner=_StubProcess(load_fixture("linux_success")))
    resolved = runner._resolve_target("8.8.8.8")
    assert resolved == "8.8.8.8"


def test_resolve_target_hostname_success() -> None:
    with patch("gnd.network.real_ping_runner.socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.16.119.50", 0))
        ]
        runner = RealPingRunner(
            process_runner=_StubProcess(load_fixture("linux_success"))
        )
        resolved = runner._resolve_target("auth.riotgames.com")
        assert resolved == "104.16.119.50"
        mock_getaddrinfo.assert_called_once_with(
            "auth.riotgames.com", None, socket.AF_INET
        )


def test_resolve_target_hostname_failure_returns_none() -> None:
    with patch("gnd.network.real_ping_runner.socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
        runner = RealPingRunner(
            process_runner=_StubProcess(load_fixture("linux_success"))
        )
        resolved = runner._resolve_target("invalid.invalid.tld")
        assert resolved is None


def test_ping_with_hostname_resolves_and_uses_resolved_ip() -> None:
    """End-to-end: hostname se resuelve internamente, pero target_ip
    guarda el valor original del caller para estabilidad del baseline."""
    with patch("gnd.network.real_ping_runner.socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.16.119.50", 0))
        ]
        runner = RealPingRunner(
            process_runner=_StubProcess(load_fixture("linux_success"))
        )
        r = runner.ping("auth.riotgames.com", "auth_riot", "riot_public", 2, 1000)
    # target_ip = hostname original (estable), no la IP resuelta
    assert r.target_ip == "auth.riotgames.com"
    assert r.target_name == "auth_riot"
