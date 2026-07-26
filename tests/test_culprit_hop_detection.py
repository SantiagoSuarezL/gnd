"""Tests unitarios de `detect_culprit_hop` \u2014 logica pura (Fase 7).

Sin red, sin subprocess: solo la logica de deteccion del hop culpable del
salto de latencia, satisfy TECHNICAL_SPEC.md \u00a72.3:

1. Recorrer hops en orden, tracking el rtt del ultimo hop que respondio.
2. Marcar culpable cuando un hop respondio con rtt > prev + threshold.
3. Validar sosten en hops subsiguientes (descartar picos puntuales).
4. Hops no respondidos se saltan en comparacion (no son error, no son
   culpables).
5. No hay culpable -> None.

DoD explicito de Fase 7: fixture con salto sostenido de +80ms en hop 7
-> el sistema identifica ``culprit_hop_index = 6`` (0-based).
"""

from __future__ import annotations

from gnd.models.traceroute import TracerouteHop
from gnd.network.real_traceroute_runner import detect_culprit_hop


def _hops(rtts: list[float | None]) -> list[TracerouteHop]:
    """Helper: construye lista de hops donde cada RTT=None -> responded=False."""
    out: list[TracerouteHop] = []
    for i, rtt in enumerate(rtts, start=1):
        if rtt is None:
            out.append(TracerouteHop(i, None, None, None, responded=False))
        else:
            out.append(TracerouteHop(i, f"10.0.0.{i}", None, rtt, responded=True))
    return out


class TestDoD:
    """Definition of Done explicito: +80ms sostenido en hop 7 -> index 6."""

    def test_dod_hop7_80ms_sostenido_devuelve_hop6_index(self) -> None:
        # Salto: hop 6 (9.33) -> hop 7 (90.0). Delta = 80.66ms > 40ms threshold.
        # Hop 8 despues: rtt 132.66 >= 90 - 5 = 85 (sostiene).
        hops = _hops([1.0, 7.0, 9.0, 9.66, 7.66, 9.33, 90.0, 132.66])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx == 6, f"Esperado index 6 (hop 7). Recibido index {idx}."

    def test_dod_con_threshold_default_funciona(self) -> None:
        # Threshold default = 40 ( TECHNICAL_SPEC.md \u00a75).
        hops = _hops([1.0, 7.0, 9.0, 9.66, 7.66, 9.33, 90.0, 132.66])
        idx = detect_culprit_hop(hops)
        assert idx == 6


class TestPicoPuntualNoCulpable:
    """Si el incremento NO se sostiene en hops subsiguientes, no es culpable.

    Patron tipico: un router que desprioriza ICMP pero no afecta trafico real.
    """

    def test_pico_un_solo_hop_no_es_culpable(self) -> None:
        # Hop 4: 80.0 (delta ~72ms vs 7.66 anterior) -> candidato.
        # Hop 5: 8.66 (regresa al nivel anterior) -> NO sostenido -> None.
        hops = _hops([1.0, 7.0, 7.66, 80.0, 8.66, 9.33])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx is None

    def test_pico_unico_no_es_culpable_con_hop_sin_respuesta_despues(self) -> None:
        # Hop 3: 90.0 (delta +84 ms), hop 4 None, hop 5 vuelve a 8.0.
        # El hop 4 no aporta info, hop 5 baja -> no sostenido -> None.
        hops = _hops([1.0, 5.0, 90.0, None, 8.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx is None


class TestSosten:
    """Diferentes formas de 'sostener' el salto."""

    def test_sosten_con_hop_sin_respuesta_entre_medio(self) -> None:
        # Hop 3: 50.0 (delta 45ms vs 5.0). Hop 4 no responde. Hop 5: 49 (sostiene).
        hops = _hops([1.0, 5.0, 50.0, None, 49.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx == 2  # index 2 = hop 3

    def test_sosten_con_varios_hops_subsiguientes_sostenidos(self) -> None:
        # El hop 4 (46ms) es el culpable; hop 5, 6, 7 todos por encima de 40.
        # Delta 46-5 = 41 > 40 (threshold). Sostiene con 50, 48, 47.
        hops = _hops([1.0, 5.0, 5.0, 46.0, 50.0, 48.0, 47.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx == 3  # primer culpable detectado

    def test_sosten_con_baja_dentro_de_tolerancia(self) -> None:
        # Hop 4: 50.0 (delta +45ms). Threshold 40. Sosten tolerance 5ms.
        # Hop 5: 46.0 (50-5+1=46 esta dentro del floor 50-5=45). Sostenido.
        hops = _hops([1.0, 5.0, 5.0, 50.0, 46.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0, sustain_tolerance_ms=5.0)
        assert idx == 3

    def test_no_sosten_si_baja_justo_bajo_floor(self) -> None:
        # Hop 4: 50.0 (delta +45). Hop 5: 44.0 < floor 45 -> NO sostenido.
        hops = _hops([1.0, 5.0, 5.0, 50.0, 44.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0, sustain_tolerance_ms=5.0)
        assert idx is None


class TestHopsNoRespondidos:
    """Hops que no responden no son culpables ni son previos validos."""

    def test_all_hops_no_responden_devuelve_none(self) -> None:
        hops = _hops([None, None, None, None, None])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx is None

    def test_solo_un_hop_responde_devuelve_none(self) -> None:
        # No hay dos puntos de comparacion: devuelve None.
        hops = _hops([10.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx is None

    def test_hop_no_respondido_se_salta_en_comparacion(self) -> None:
        # Hop 5 no responde. Hop 4 (24) -> Hop 6 (75): delta 51ms. Hop 7 sostiene.
        hops = _hops([1.0, 7.0, 8.33, 24.33, None, 68.66, 70.33])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        assert idx == 5  # hop 6 (index 5)

    def test_varios_hops_no_respondidos_se_saltan(self) -> None:
        hops = _hops([1.0, None, None, None, 90.0, 90.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=40.0)
        # El primer hop que respondio es hop 1 (1.0). Despues None.. despues hop 5 (90).
        # Delta 90-1=89 > 40. Sosten hop 6 = 90 -> floor 85 OK.
        assert idx == 4


class TestThresholdConfigurable:
    """El threshold es configurable (TECHNICAL_SPEC.md \u00a76 thresholds)."""

    def test_threshold_20_mas_sensible_detecta_antes(self) -> None:
        # Con threshold 20ms, saltos de 25ms ya son culpables.
        hops = _hops([1.0, 5.0, 30.0, 30.0])  # salto hop2->hop3 = 25ms
        # Con default 40ms no detectaria, con 20ms si.
        assert detect_culprit_hop(hops, jump_threshold_ms=40.0) is None
        idx = detect_culprit_hop(hops, jump_threshold_ms=20.0)
        assert idx == 2

    def test_threshold_60_menos_sensible_no_detecta(self) -> None:
        # Salto de 50ms no supera threshold 60.
        hops = _hops([1.0, 5.0, 55.0, 55.0])
        idx = detect_culprit_hop(hops, jump_threshold_ms=60.0)
        assert idx is None
