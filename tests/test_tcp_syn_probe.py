"""Tests unitarios de `network/tcp_syn_probe` con socket mockeado.

No toca red real. Verifica la clasificacion de outcomes (EP §4: sin red
en tests unitarios).
"""

from unittest.mock import patch

import pytest

from gnd.network import tcp_syn_probe
from gnd.network.tcp_syn_probe import TcpSynResult


def test_probe_open_cuando_connect_exito() -> None:
    fake_sock = _FakeSock()
    with patch("gnd.network.tcp_syn_probe.socket.create_connection") as mock:
        mock.return_value = fake_sock
        outcome = tcp_syn_probe.probe("1.1.1.1", port=443, timeout_s=0.5)
    assert outcome.result is TcpSynResult.OPEN
    assert outcome.detail == "tcp connect ok"
    assert tcp_syn_probe.is_host_alive(outcome) is True
    assert fake_sock._closed is True


def test_probe_rejected_cuando_connection_refused() -> None:
    with patch("gnd.network.tcp_syn_probe.socket.create_connection") as mock:
        mock.side_effect = ConnectionRefusedError("refused")
        outcome = tcp_syn_probe.probe("1.1.1.1", port=443, timeout_s=0.5)
    assert outcome.result is TcpSynResult.REJECTED
    assert "RST" in outcome.detail
    assert tcp_syn_probe.is_host_alive(outcome) is True


def test_probe_timeout_cuando_socket_timeout() -> None:
    with patch("gnd.network.tcp_syn_probe.socket.create_connection") as mock:
        mock.side_effect = TimeoutError("timed out")
        outcome = tcp_syn_probe.probe("1.1.1.1", port=443, timeout_s=0.5)
    assert outcome.result is TcpSynResult.TIMEOUT
    assert tcp_syn_probe.is_host_alive(outcome) is False


def test_probe_network_unreachable_cuando_oserror() -> None:
    with patch("gnd.network.tcp_syn_probe.socket.create_connection") as mock:
        mock.side_effect = OSError("Network is unreachable")
        outcome = tcp_syn_probe.probe("1.1.1.1", port=443, timeout_s=0.5)
    assert outcome.result is TcpSynResult.NETWORK_UNREACHABLE
    assert tcp_syn_probe.is_host_alive(outcome) is False


def test_is_host_alive_cobertura() -> None:
    alive = [
        tcp_syn_probe.TcpSynOutcome(TcpSynResult.OPEN, ""),
        tcp_syn_probe.TcpSynOutcome(TcpSynResult.REJECTED, ""),
    ]
    not_alive = [
        tcp_syn_probe.TcpSynOutcome(TcpSynResult.TIMEOUT, ""),
        tcp_syn_probe.TcpSynOutcome(TcpSynResult.NETWORK_UNREACHABLE, ""),
    ]
    for o in alive:
        assert tcp_syn_probe.is_host_alive(o) is True
    for o in not_alive:
        assert tcp_syn_probe.is_host_alive(o) is False


def test_tcp_syn_outcome_immutable() -> None:
    from dataclasses import FrozenInstanceError

    o = tcp_syn_probe.TcpSynOutcome(TcpSynResult.OPEN, "x")
    with pytest.raises(FrozenInstanceError):
        o.result = TcpSynResult.TIMEOUT  # type: ignore[misc]


class _FakeSock:
    """Context manager socket dummy para el caso OPEN."""

    def __init__(self) -> None:
        self._closed = False

    def __enter__(self) -> "_FakeSock":
        return self

    def __exit__(self, *exc: object) -> None:
        self._closed = True

    def close(self) -> None:
        self._closed = True
