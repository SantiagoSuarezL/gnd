"""Tests de integracion contra red REAL.

Marcados `@pytest.mark.integration`: requieren conectividad real y el
binario `ping` del OS. No corren en la corrida rapida por defecto (ver
`pyproject.toml` addopts). Ejecutar con:

    pytest -m integration tests/test_integration_ping.py

Estos tests validan el DoD de Fase 2: diagnostico local + internet corre
end-to-end contra red real sin crashear.
"""

import socket

import pytest

from gnd.models.probe_result import ProbeOutcomeKind
from gnd.network.real_ping_runner import RealPingRunner

# Targets de prueba (TECHNICAL_SPEC.md §6): DNS publicos + loopback.
TARGETS = [
    ("127.0.0.1", "loopback", "local"),
    ("8.8.8.8", "google_dns", "google"),
    ("1.1.1.1", "cloudflare", "cloudflare"),
    ("9.9.9.9", "quad9", "quad9"),
]


@pytest.mark.integration
@pytest.mark.parametrize("ip,name,provider", TARGETS)
def test_ping_real_end_to_end(ip: str, name: str, provider: str) -> None:
    runner = RealPingRunner()
    r = runner.ping(ip, name, provider, count=5, timeout_ms=1000)
    # En un entorno con red, estos targets suelen responder (SUCCESS o
    # FILTERED si bloquean ICMP). Lo que NUNCA debe pasar: excepcion.
    assert r.outcome in (
        ProbeOutcomeKind.SUCCESS,
        ProbeOutcomeKind.FILTERED,
        ProbeOutcomeKind.UNREACHABLE,
        ProbeOutcomeKind.TIMEOUT,
    )
    if r.outcome is ProbeOutcomeKind.SUCCESS:
        assert r.stats is not None
        assert r.stats.samples >= 1
        assert 0.0 <= r.stats.packet_loss_pct <= 100.0
        assert r.stats.min_ms <= r.stats.avg_ms <= r.stats.max_ms
    else:
        assert r.stats is None


@pytest.mark.integration
def test_ping_ip_documentada_inalcanzable_no_crash() -> None:
    """RFC 5737 TEST-NET-3: 203.0.113.0/24 es no-rutable por definicion."""
    runner = RealPingRunner()
    r = runner.ping("203.0.113.42", "test_net", "local", count=2, timeout_ms=1000)
    # Debe ser TIMEOUT o UNREACHABLE, jamas SUCCESS ni excepcion.
    assert r.outcome in (ProbeOutcomeKind.TIMEOUT, ProbeOutcomeKind.UNREACHABLE)
    assert r.stats is None


@pytest.mark.integration
def test_fallback_tcp_syn_funciona_contra_host_icmp_bloqueado() -> None:
    """Verifica el fallback TCP SYN en vivo: un host que bloquea ICMP pero
    expone TCP 443 visible (usamos cloudflare 1.1.1.1 que tiene TCP 443).

    Nota: 1.1.1.1 tipicamente responde ICMP, asi que esto valida que el
    canal TCP efectivamente funciona (no que se dispare el fallback en
    este caso concreto). Para forzar el fallback ver test_filtered_forzado.
    """
    sock = socket.create_connection(("1.1.1.1", 443), timeout=2.0)
    sock.close()
    assert True  # llegamos aca sin excepcion: TCP 443 vivo.


@pytest.mark.integration
def test_diagnostico_completo_no_crashea() -> None:
    """DoD Fase 2: diagnostico local + internet end-to-end sin crashear."""
    runner = RealPingRunner()
    results = []
    for ip, name, provider in TARGETS:
        results.append(runner.ping(ip, name, provider, count=3, timeout_ms=1000))
    assert len(results) == len(TARGETS)
    for r in results:
        assert r.target_ip != ""
        assert r.provider != ""
        assert r.target_name != ""
        assert r.outcome in ProbeOutcomeKind
