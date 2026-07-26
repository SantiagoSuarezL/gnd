"""Tests de integracion RealTracerouteRunner contra red real (Fase 7).

Marcados con @pytest.mark.integration. No corren por defecto (addopts = "-m 'not integration'").
Para ejecutar: pytest -m integration tests/test_integration_tracert.py

Solo valida que el parser interpreta correctamente el formato de tracert en Windows real
y que culprit_hop_index funciona end-to-end. No requiere LoL corriendo.
"""

from __future__ import annotations

import pytest

from gnd.network.real_traceroute_runner import RealTracerouteRunner

pytestmark = pytest.mark.integration


class TestIntegrationTraceroute:
    """Tests contra red real."""

    def test_google_dns_8_8_8_8_success(self) -> None:
        """Google DNS 8.8.8.8 -> tracert completo, culprit_hop_index valido o None."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("8.8.8.8", "google", 15, 1500)
        assert isinstance(r.target_provider, str) and r.target_provider == "google"
        assert len(r.hops) >= 2  # al menos gateway + destino
        assert r.hops[0].responded is True  # gateway local responde
        # culprit_hop_index puede ser None (sin salto anomalo) o int valido
        if r.culprit_hop_index is not None:
            assert 0 <= r.culprit_hop_index < len(r.hops)

    def test_cloudflare_1_1_1_1_success(self) -> None:
        """Cloudflare 1.1.1.1 -> tracert completo."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("1.1.1.1", "cloudflare", 15, 1500)
        assert len(r.hops) >= 2
        assert r.hops[0].responded is True

    def test_quad9_9_9_9_9_success(self) -> None:
        """Quad9 9.9.9.9 -> tracert completo."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("9.9.9.9", "quad9", 15, 1500)
        assert len(r.hops) >= 2
        assert r.hops[0].responded is True

    def test_riot_public_auth_riotgames_com(self) -> None:
        """auth.riotgames.com (resuelve a Cloudflare) -> tracert completo."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("auth.riotgames.com", "riot_public", 15, 1500)
        assert len(r.hops) >= 2
        assert r.hops[0].responded is True

    def test_local_loopback_tracert(self) -> None:
        """Loopback 127.0.0.1 -> tracert trivial (1 hop)."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("127.0.0.1", "local", 10, 1000)
        assert len(r.hops) >= 1
        assert r.hops[0].responded is True
        assert r.hops[0].ip == "127.0.0.1"

    def test_host_no_rutable_testnet(self) -> None:
        """TEST-NET-3 203.0.113.42 -> timeout/UNREACHABLE, no crashea."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("203.0.113.42", "test_net", 8, 1500)
        # Puede ser todos timeout (hops no respondidos) o UNREACHABLE
        # Lo importante: no lanza excepcion y devuelve TracerouteResult
        assert isinstance(r.target_provider, str)
        assert len(r.hops) >= 1

    def test_max_hops_limit_respetado(self) -> None:
        """max_hops=5 limita la traza a 5 hops max."""
        runner = RealTracerouteRunner()
        r = runner.traceroute("8.8.8.8", "google", 5, 1500)
        # hops <= 5 (puede ser menos si llega al destino antes)
        assert len(r.hops) <= 5
        # El ultimo hop debe ser el destino o timeout
        assert r.hops[-1].hop_number <= 5

    def test_culprit_hop_index_en_rango_si_existe(self) -> None:
        """Si hay culprit, su index esta dentro de rango de hops."""
        runner = RealTracerouteRunner()
        for ip, prov in [
            ("8.8.8.8", "google"),
            ("1.1.1.1", "cloudflare"),
            ("9.9.9.9", "quad9"),
        ]:
            r = runner.traceroute(ip, prov, 15, 1500)
            if r.culprit_hop_index is not None:
                assert 0 <= r.culprit_hop_index < len(r.hops)
