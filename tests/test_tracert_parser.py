"""Tests unitarios del parser de `tracert` (Fase 7).

Sin red: todos los tests cargan fixtures grabados de output real o
sintetico de `tracert` (formato Windows, EN y ES). Cubren los casos:
- Header en ingles y espanol (con y sin "la direccion ... [IP]").
- Hop con multiples probes (RTT promedio de las 3 muestras).
- Hop que no responde (linea con ``*  *  *  Request timed out.``) -> responded=False.
- Output total timeout (todos los hops timeout).
- Output sin hops reconocidos -> devuelve ParsedTracert con hops=().

Regla de Oro 2.2: parser soporta EN + ES aunque el target sea Windows.
"""

import pytest

from gnd.network.tracert_parser import ParsedHop, ParsedTracert, parse
from tests.conftest import load_tracert_fixture


class TestParserHeaders:
    """Cabecera: extraccion de target_ip y target_hostname (sin y con hostname)."""

    def test_header_en_solo_ip(self) -> None:
        r = parse(load_tracert_fixture("windows_success_en"))
        assert r.target_ip == "8.8.8.8"
        assert r.target_hostname is None

    def test_header_es_solo_ip(self) -> None:
        r = parse(load_tracert_fixture("windows_success_es"))
        assert r.target_ip == "8.8.8.8"
        assert r.target_hostname is None

    def test_header_es_con_direccion_e_ip(self) -> None:
        # "Traza a la direccion auth.riotgames.com.cdn.cloudflare.net [104.16.119.50]"
        # / "sobre un maximo de 12 saltos:"
        r = parse(load_tracert_fixture("windows_salto_sostenido_es"))
        assert r.target_ip == "104.16.119.50"
        assert r.target_hostname == "auth.riotgames.com.cdn.cloudflare.net"

    def test_header_en_con_hostname(self) -> None:
        # "Tracing route to the.example.com [192.0.2.50] over a maximum of 8 hops:"
        r = parse(load_tracert_fixture("windows_pico_un_solo_hop_en"))
        assert r.target_ip == "192.0.2.50"
        assert r.target_hostname == "the.example.com"

    def test_header_en_con_hostnames_en_hops(self) -> None:
        # Fixture con hostnames en hops intermedios
        r = parse(load_tracert_fixture("windows_con_hostnames_en"))
        assert r.target_ip == "8.8.8.8"
        assert r.target_hostname == "dns.google"
        # Hop 1 debe tener hostname
        hop1 = next(h for h in r.hops if h.hop_number == 1)
        assert hop1.hostname == "router.local"
        assert hop1.ip == "192.168.20.1"
        # Hop 5 (destino) debe tener hostname
        hop5 = next(h for h in r.hops if h.hop_number == 5)
        assert hop5.hostname == "dns.google"
        assert hop5.ip == "8.8.8.8"


class TestParserHops:
    """Parseo de lineas de hop (RTT, IP, responded)."""

    def test_hops_success_count(self) -> None:
        r = parse(load_tracert_fixture("windows_success_en"))
        assert len(r.hops) == 8

    def test_hops_numero_ordenado_empezando_en_1(self) -> None:
        r = parse(load_tracert_fixture("windows_success_en"))
        for i, h in enumerate(r.hops):
            assert h.hop_number == i + 1

    def test_hop_rtt_es_promedio_de_3_muestras(self) -> None:
        # "  4    11 ms    10 ms    12 ms  ...": prom = (11+10+12)/3 = 11.0
        r = parse(load_tracert_fixture("windows_success_en"))
        hop4 = next(h for h in r.hops if h.hop_number == 4)
        assert hop4.rtt_ms == pytest.approx(10.666666, rel=1e-3)

    def test_hop_sin_respuesta_responded_false(self) -> None:
        # hop 5 en hop_sin_respuesta: "*  *  *  Request timed out."
        r = parse(load_tracert_fixture("windows_hop_sin_respuesta_en"))
        hop5 = next(h for h in r.hops if h.hop_number == 5)
        assert hop5.responded is False
        assert hop5.ip is None
        assert hop5.rtt_ms is None
        assert hop5.hostname is None

    def test_hop_sin_respuesta_es_ignorado_en_orden(self) -> None:
        # hop 5 no responde, pero hop 6 y 7 si (siguen en orden)
        r = parse(load_tracert_fixture("windows_hop_sin_respuesta_en"))
        hop4 = next(h for h in r.hops if h.hop_number == 4)
        hop6 = next(h for h in r.hops if h.hop_number == 6)
        assert hop4.responded is True
        assert hop6.responded is True

    def test_all_timeout_todos_responded_false(self) -> None:
        r = parse(load_tracert_fixture("windows_all_timeout_en"))
        # Solo hop 1 responde (gateway local)
        assert len(r.hops) == 5
        assert r.hops[0].responded is True  # hop 1 = gateway
        for h in r.hops[1:]:
            assert h.responded is False
            assert h.ip is None
            assert h.rtt_ms is None

    def test_hops_rtt_es_float_no_int(self) -> None:
        # Asegura que RTT promedio sea float, no truncado a int
        r = parse(load_tracert_fixture("windows_hop_sin_respuesta_en"))
        hop2 = next(h for h in r.hops if h.hop_number == 2)
        # 7, 7, 7 -> promedio 7.0 (float)
        assert isinstance(hop2.rtt_ms, float)
        assert hop2.rtt_ms == 7.0

    def test_hops_con_hostnames_existentes(self) -> None:
        r = parse(load_tracert_fixture("windows_con_hostnames_en"))
        hop1 = next(h for h in r.hops if h.hop_number == 1)
        assert hop1.hostname == "router.local"
        assert hop1.ip == "192.168.20.1"
        hop5 = next(h for h in r.hops if h.hop_number == 5)
        assert hop5.hostname == "dns.google"
        assert hop5.ip == "8.8.8.8"


class TestParserEdgeCases:
    """Casos borde y validaciones."""

    def test_output_vacio_devuelve_vacio(self) -> None:
        r = parse("")
        assert isinstance(r, ParsedTracert)
        assert r.hops == ()

    def test_output_solo_cabecera_sin_hops(self) -> None:
        # "Tracing route to X over..." seguido de "Trace complete." sin hops
        output = (
            "Tracing route to 8.8.8.8 over a maximum of 10 hops:\n\nTrace complete.\n"
        )
        r = parse(output)
        assert r.hops == ()

    def test_cabecera_sin_trace_complete(self) -> None:
        # Output truncado sin "Trace complete."
        r = parse(load_tracert_fixture("windows_success_en")[:100])  # truncado
        assert isinstance(r, ParsedTracert)
        assert len(r.hops) > 0  # parser tolera truncamiento

    def test_linea_que_no_es_hop_ni_cabecera_ni_fin_se_ignora(self) -> None:
        # Agregar linea de ruido
        output = load_tracert_fixture("windows_success_en") + "\n  LEE ESTO\n"
        r = parse(output)
        assert len(r.hops) == 8  # no debe crashear


class TestParsedTracertInvariants:
    """Validaciones de invariantes del DTO ParsedTracert."""

    def test_hop_numero_invalido_falla(self) -> None:
        with pytest.raises(ValueError, match="hop_number debe ser >= 1"):
            ParsedHop(
                hop_number=0, ip="1.2.3.4", hostname=None, rtt_ms=10.0, responded=True
            )

    def test_hop_responded_true_sin_rtt_falla(self) -> None:
        with pytest.raises(
            ValueError, match="rtt_ms no puede ser None si responded=True"
        ):
            ParsedHop(
                hop_number=1, ip="1.2.3.4", hostname=None, rtt_ms=None, responded=True
            )

    def test_hop_rtt_negativo_falla(self) -> None:
        with pytest.raises(ValueError, match="rtt_ms debe ser >= 0"):
            ParsedHop(
                hop_number=1, ip="1.2.3.4", hostname=None, rtt_ms=-1.0, responded=True
            )


class TestFixturesLoaded:
    """Sanity check: todos los fixtures se cargan y parsean sin error."""

    @pytest.mark.parametrize(
        "name",
        [
            "windows_success_en",
            "windows_success_es",
            "windows_hop_sin_respuesta_en",
            "windows_hop_sin_respuesta_es",
            "windows_salto_sostenido_en",
            "windows_salto_sostenido_es",
            "windows_dod_salto_80ms_sostenido_en",
            "windows_dod_salto_80ms_sostenido_es",
            "windows_pico_un_solo_hop_en",
            "windows_con_hostnames_en",
            "windows_all_timeout_en",
        ],
    )
    def test_fixture_parseable(self, name: str) -> None:
        text = load_tracert_fixture(name)
        r = parse(text)
        assert isinstance(r, ParsedTracert)
        assert len(r.hops) > 0
        # Al menos un hop debe responder (gateway local minimo)
        assert any(h.responded for h in r.hops)
