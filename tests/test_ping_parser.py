"""Tests unitarios de `network/ping_parser` usando fixtures grabadas.

IMPLEMENTATION_PLAN.md Fase 2: tests del parsing de output de `ping` con
outputs de ejemplo grabados como texto, no dependientes de red real. Esto
garantiza determinismo y reproducibilidad (EP §4).
"""

import pytest

from gnd.network import ping_parser
from tests.conftest import load_fixture

# --- Windows ---


def test_windows_success_parsea_rtts_y_stats() -> None:
    out = load_fixture("windows_success")
    p = ping_parser.parse(out)
    assert p.received == 5
    assert p.transmitted == 5
    assert p.packet_loss_pct == 0.0
    assert p.all_lost is False
    assert p.rtt_ms == (12.0, 11.0, 13.0, 10.0, 12.0)
    st = p.build_stats()
    assert st is not None
    avg, mn, mx, jitter, samples = st
    assert mn == 10.0
    assert mx == 13.0
    assert samples == 5
    assert 11.0 <= avg <= 12.0
    assert jitter >= 0.0
    assert p.error_letter is None


def test_windows_partial_loss_parsea() -> None:
    out = load_fixture("windows_partial_loss")
    p = ping_parser.parse(out)
    assert p.transmitted == 5
    assert p.received == 3
    assert p.packet_loss_pct == 40.0
    assert p.rtt_ms == (2.0, 3.0, 2.0)
    assert p.all_lost is False
    st = p.build_stats()
    assert st is not None
    avg, mn, mx, jitter, samples = st
    assert mn == 2.0
    assert mx == 3.0
    assert samples == 3


def test_windows_host_unreachable_error_letter_u() -> None:
    out = load_fixture("windows_host_unreachable")
    p = ping_parser.parse(out)
    assert p.received == 0
    assert p.transmitted == 5
    assert p.packet_loss_pct == 100.0
    assert p.all_lost is True
    assert p.error_letter == "U"
    assert p.build_stats() is None


def test_windows_all_timeout_sin_error_letter() -> None:
    out = load_fixture("windows_all_timeout")
    p = ping_parser.parse(out)
    assert p.received == 0
    assert p.packet_loss_pct == 100.0
    assert p.all_lost is True
    # "Request timed out" no marca error_letter (no es unreachable explicito).
    assert p.error_letter is None
    assert p.build_stats() is None


def test_windows_general_failure_error_letter_g() -> None:
    out = load_fixture("windows_general_failure")
    p = ping_parser.parse(out)
    assert p.received == 0
    assert p.error_letter == "G"
    assert p.all_lost is True


# --- Linux ---


def test_linux_success_parsea_rtts_y_stats() -> None:
    out = load_fixture("linux_success")
    p = ping_parser.parse(out)
    assert p.transmitted == 5
    assert p.received == 5
    assert p.packet_loss_pct == 0.0
    assert p.rtt_ms == (14.2, 13.0, 12.4, 13.5, 12.8)
    st = p.build_stats()
    assert st is not None
    avg, mn, mx, jitter, samples = st
    assert mn == 12.4
    assert mx == 14.2
    assert samples == 5


def test_linux_partial_loss_parsea() -> None:
    out = load_fixture("linux_partial_loss")
    p = ping_parser.parse(out)
    assert p.transmitted == 5
    assert p.received == 3
    assert p.packet_loss_pct == 40.0
    assert p.rtt_ms == (2.31, 2.42, 2.28)
    st = p.build_stats()
    assert st is not None
    avg, mn, mx, jitter, samples = st
    assert mn == 2.28
    assert mx == 2.42


def test_linux_all_timeout_sin_error_letter() -> None:
    out = load_fixture("linux_all_timeout")
    p = ping_parser.parse(out)
    assert p.received == 0
    assert p.packet_loss_pct == 100.0
    assert p.all_lost is True
    assert p.error_letter is None


def test_linux_host_unreachable_error_letter_u() -> None:
    out = load_fixture("linux_host_unreachable")
    p = ping_parser.parse(out)
    assert p.received == 0
    assert p.error_letter == "U"


def test_linux_net_unreachable_error_letter_g() -> None:
    out = load_fixture("linux_general_failure")
    p = ping_parser.parse(out)
    assert p.received == 0
    assert p.error_letter == "G"


# --- Robustez ---


def test_empty_output_no_crash() -> None:
    p = ping_parser.parse("")
    assert p.received == 0
    assert p.transmitted == 0
    assert p.all_lost is True


def test_garbage_output_no_crash() -> None:
    p = ping_parser.parse("laksjdlaksj\ndkasjdlaksjd\n")
    assert p.received == 0
    assert p.rtt_ms == ()


def test_windows_time_lt_1ms() -> None:
    p = ping_parser.parse(
        "Reply from 127.0.0.1: bytes=32 time<1ms TTL=128\n"
        "Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),"
    )
    assert p.received == 1
    assert p.rtt_ms == (1.0,)


def test_build_stats_jitter_unica_muestra_es_cero() -> None:
    p = ping_parser.parse(
        "64 bytes from 1.1.1.1: icmp_seq=1 ttl=55 time=135 ms\n"
        "1 packets transmitted, 1 received, 0% packet loss"
    )
    st = p.build_stats()
    assert st is not None
    avg, mn, mx, jitter, samples = st
    assert jitter == 0.0
    assert samples == 1


def test_parsed_ping_immutable() -> None:
    from dataclasses import FrozenInstanceError

    p = ping_parser.parse("64 bytes from 1.1.1.1: time=10 ms")
    with pytest.raises(FrozenInstanceError):
        p.received = 5  # type: ignore[misc]


# --- Windows Spanish ---


def test_windows_success_spanish_parsea_rtts_y_stats() -> None:
    out = load_fixture("windows_success_es")
    p = ping_parser.parse(out)
    assert p.received == 4
    assert p.transmitted == 4
    assert p.packet_loss_pct == 0.0
    assert p.all_lost is False
    assert p.rtt_ms == (1.0, 1.0, 1.0, 1.0)
    st = p.build_stats()
    assert st is not None
    avg, mn, mx, jitter, samples = st
    assert mn == 1.0
    assert mx == 1.0
    assert samples == 4
    assert avg == 1.0
    assert jitter == 0.0
    assert p.error_letter is None
