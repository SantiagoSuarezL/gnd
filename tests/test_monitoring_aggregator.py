"""Tests unitarios del agregador puro (monitoring/aggregator.py).

Sin red, sin reloj, sin subprocess (EP §4). Cubre:

- aggregate_hops: agrupacion por hop_number, calculo de best/worst/avg/jitter/loss.
- fill_ip_hostname_mode: seleccion de IP/hostname por moda.
- Combinacion de ambos en el orquestador se testea aparte
  (tests/test_route_monitor.py).
"""

from __future__ import annotations

import statistics

import pytest

from gnd.models.monitoring import HopStats, MonitoringSample
from gnd.monitoring.aggregator import (
    aggregate_hops,
    fill_ip_hostname_mode,
    format_anomalies_text,
)

# --------------------------------------------------------------------------- #
# aggregate_hops
# --------------------------------------------------------------------------- #


class TestAggregateHopsEmpty:
    def test_iterable_vacio_devuelve_lista_vacia(self):
        assert aggregate_hops([]) == []

    def test_iterador_generador_vacio(self):
        def gen():
            return
            yield  # type: ignore[unreachable]

        assert aggregate_hops(gen()) == []


class TestAggregateHopsSingleHop:
    def test_una_muestra_respondida(self):
        samples = [MonitoringSample(0, 1, 15.0)]
        result = aggregate_hops(samples)
        assert len(result) == 1
        hs = result[0]
        assert hs.hop_number == 1
        assert hs.best_ms == 15.0
        assert hs.worst_ms == 15.0
        assert hs.avg_ms == 15.0
        assert hs.jitter_ms == 0.0  # 1 muestra -> jitter 0
        assert hs.loss_pct == 0.0
        assert hs.success_count == 1
        assert hs.samples == 1
        # Los campos de IP se rellenan con fill_ip_hostname_mode, no aqui.
        assert hs.ip is None
        assert hs.hostname is None

    def test_una_muestra_no_respondio(self):
        samples = [MonitoringSample(0, 3, None)]
        result = aggregate_hops(samples)
        assert len(result) == 1
        hs = result[0]
        assert hs.hop_number == 3
        assert hs.best_ms is None
        assert hs.worst_ms is None
        assert hs.avg_ms is None
        assert hs.jitter_ms == 0.0
        assert hs.loss_pct == 100.0
        assert hs.success_count == 0


class TestAggregateHopsMultiSample:
    def test_dos_muestras_respondidas(self):
        samples = [
            MonitoringSample(0, 1, 10.0),
            MonitoringSample(1, 1, 20.0),
        ]
        result = aggregate_hops(samples)
        assert len(result) == 1
        hs = result[0]
        assert hs.best_ms == 10.0
        assert hs.worst_ms == 20.0
        assert hs.avg_ms == 15.0
        assert hs.jitter_ms == statistics.stdev([10.0, 20.0])
        assert hs.success_count == 2
        assert hs.loss_pct == 0.0

    def test_tres_muestras_una_timeout(self):
        samples = [
            MonitoringSample(0, 1, 10.0),
            MonitoringSample(1, 1, None),
            MonitoringSample(2, 1, 30.0),
        ]
        result = aggregate_hops(samples)
        assert len(result) == 1
        hs = result[0]
        assert hs.samples == 3
        assert hs.success_count == 2
        # loss = (3 - 2) / 3 * 100 = 33.33...
        assert hs.loss_pct == pytest.approx(100.0 * 1 / 3, rel=1e-9)
        assert hs.best_ms == 10.0
        assert hs.worst_ms == 30.0
        assert hs.avg_ms == 20.0

    def test_todas_timeout_devuelve_loss_pct_100(self):
        samples = [
            MonitoringSample(0, 5, None),
            MonitoringSample(1, 5, None),
            MonitoringSample(2, 5, None),
        ]
        result = aggregate_hops(samples)
        assert len(result) == 1
        hs = result[0]
        assert hs.hop_number == 5
        assert hs.success_count == 0
        assert hs.loss_pct == 100.0
        assert hs.best_ms is None
        assert hs.avg_ms is None


class TestAggregateHopsMultiHop:
    def test_dos_hops_se_agregan_separadamente(self):
        samples = [
            MonitoringSample(0, 1, 1.0),
            MonitoringSample(0, 2, 10.0),
            MonitoringSample(1, 1, 2.0),
            MonitoringSample(1, 2, None),  # hop 2 silencio en muestra 1
        ]
        result = aggregate_hops(samples)
        assert len(result) == 2
        assert [hs.hop_number for hs in result] == [1, 2]

        h1 = result[0]
        assert h1.hop_number == 1
        assert h1.samples == 2
        assert h1.success_count == 2
        assert h1.best_ms == 1.0
        assert h1.worst_ms == 2.0
        assert h1.avg_ms == 1.5
        assert h1.loss_pct == 0.0

        h2 = result[1]
        assert h2.hop_number == 2
        assert h2.samples == 2
        assert h2.success_count == 1
        assert h2.best_ms == 10.0
        assert h2.worst_ms == 10.0
        assert h2.avg_ms == 10.0
        assert h2.loss_pct == 50.0

    def test_hop_numbers_desordenados_se_ordenan_ascendente(self):
        samples = [
            MonitoringSample(0, 5, 1.0),
            MonitoringSample(1, 1, 1.0),
            MonitoringSample(2, 3, 1.0),
        ]
        result = aggregate_hops(samples)
        assert [hs.hop_number for hs in result] == [1, 3, 5]

    def test_hop_numbers_no_se_agrupan_cuando_distintos(self):
        samples = [
            MonitoringSample(0, 1, 1.0),
            MonitoringSample(0, 2, 2.0),
            MonitoringSample(0, 3, 3.0),
        ]
        result = aggregate_hops(samples)
        assert len(result) == 3

    def test_sample_indices_repetidos_iguales_hop_numbers(self):
        # Sample index puede repetirse entre hops (1 take = N hops).
        # El agregador solo agrupa por hop_number.
        samples = [
            MonitoringSample(0, 1, 1.0),
            MonitoringSample(0, 2, 10.0),
            MonitoringSample(0, 1, 2.0),  # mismo sample index, mismo hop
        ]
        result = aggregate_hops(samples)
        # 2 hops observados (1 y 2). Hop 1 tiene 2 samples por el repetido.
        assert len(result) == 2
        h1 = result[0]
        assert h1.hop_number == 1
        assert h1.samples == 2
        assert h1.success_count == 2


# --------------------------------------------------------------------------- #
# fill_ip_hostname_mode
# --------------------------------------------------------------------------- #


class TestFillIpHostnameMode:
    def test_moda_ip_mas_frecuente(self):
        from gnd.monitoring.aggregator import aggregate_hops

        samples = [
            MonitoringSample(0, 1, 10.0),
            MonitoringSample(1, 1, 20.0),
        ]
        # Observaciones: hop 1 respondio con ip A en muestra 0, ip B en
        # muestra 1. La ipmas repetida es la que mas se ve. Si son
        # diferentes y sin mas tiene que devolver la que mas aparece.
        # Como usamos Counter.most_common(1), en empate devuelve arbitrario
        # pero reproducible.
        stats = aggregate_hops(samples)
        per_hop_obs = {
            1: [("10.0.0.1", None), ("10.0.0.2", None), ("10.0.0.1", None)]
        }  # 10.0.0.1 aparece 2 veces
        filled = fill_ip_hostname_mode(stats, per_hop_obs)
        assert filled[0].ip == "10.0.0.1"

    def test_sin_observaciones_ip_none(self):
        from gnd.monitoring.aggregator import aggregate_hops

        # Todas las muestras son None (timeout).
        samples = [MonitoringSample(0, 1, None), MonitoringSample(1, 1, None)]
        stats = aggregate_hops(samples)
        per_hop_obs = {1: []}  # sin observaciones validas
        filled = fill_ip_hostname_mode(stats, per_hop_obs)
        assert filled[0].ip is None
        assert filled[0].hostname is None

    def test_observaciones_con_hostname(self):
        from gnd.monitoring.aggregator import aggregate_hops

        samples = [MonitoringSample(0, 1, 10.0)]
        stats = aggregate_hops(samples)
        per_hop_obs = {1: [("1.1.1.1", "one.one.one.one")]}
        filled = fill_ip_hostname_mode(stats, per_hop_obs)
        assert filled[0].ip == "1.1.1.1"
        assert filled[0].hostname == "one.one.one.one"

    def test_hop_no_presente_en_obs_devuelve_none(self):
        from gnd.monitoring.aggregator import aggregate_hops

        samples = [MonitoringSample(0, 1, 10.0), MonitoringSample(0, 2, 20.0)]
        stats = aggregate_hops(samples)
        per_hop_obs = {1: [("1.1.1.1", None)]}  # hop 2 no observado
        filled = fill_ip_hostname_mode(stats, per_hop_obs)
        assert filled[0].ip == "1.1.1.1"
        assert filled[1].ip is None

    def test_observaciones_con_none_se_ignoran(self):
        from gnd.monitoring.aggregator import aggregate_hops

        samples = [MonitoringSample(0, 1, 10.0)]
        stats = aggregate_hops(samples)
        # Mezcla de (None, None) y validos
        per_hop_obs = {
            1: [(None, None), ("9.9.9.9", None), (None, None)],
        }
        filled = fill_ip_hostname_mode(stats, per_hop_obs)
        assert filled[0].ip == "9.9.9.9"

    def test_lista_vacia_stats_vacia_devuelve_vacia(self):
        filled = fill_ip_hostname_mode([], {})
        assert filled == []

    def test_los_otros_campos_se_preservan(self):
        from gnd.monitoring.aggregator import aggregate_hops

        samples = [
            MonitoringSample(0, 1, 10.0),
            MonitoringSample(1, 1, 20.0),
        ]
        stats = aggregate_hops(samples)
        per_hop_obs = {1: [("1.1.1.1", None)]}
        filled = fill_ip_hostname_mode(stats, per_hop_obs)
        hs = filled[0]
        # Preserva lo que aggregate_hops calculo:
        assert hs.best_ms == 10.0
        assert hs.worst_ms == 20.0
        assert hs.avg_ms == 15.0
        assert hs.jitter_ms == statistics.stdev([10.0, 20.0])
        assert hs.samples == 2
        assert hs.success_count == 2
        assert hs.loss_pct == 0.0


# --------------------------------------------------------------------------- #
# format_anomalies_text — regla fija: nunca omitir perdida parcial
# --------------------------------------------------------------------------- #


def _hs(
    hop_number: int,
    *,
    ip: str | None = None,
    samples: int = 2,
    success: int = 1,
    loss_pct: float = 0.0,
    jitter: float = 0.0,
) -> HopStats:
    """Fabrica HopStats validos para tests de format_anomalies_text."""
    if success == 0:
        return HopStats(
            hop_number=hop_number,
            ip=ip,
            hostname=None,
            best_ms=None,
            worst_ms=None,
            avg_ms=None,
            jitter_ms=0.0,
            loss_pct=100.0,
            samples=max(samples, 1),
            success_count=0,
        )
    best = 10.0
    worst = best + jitter
    avg = (best + worst) / 2.0
    return HopStats(
        hop_number=hop_number,
        ip=ip,
        hostname=None,
        best_ms=best,
        worst_ms=worst,
        avg_ms=avg,
        jitter_ms=jitter,
        loss_pct=loss_pct,
        samples=samples,
        success_count=success,
    )


class TestFormatAnomaliesText:
    """Cubre la regla fijada con Santiago (2026-07-25): nunca omitir
    perdida parcial en hops intermedios, sin importar n."""

    def test_hop_con_perdida_parcial_n_bajo_aparece_siempre(self):
        # Escenario real: n=2, 1 exito, 1 perdida -> 50% loss.
        # Este caso fue omitido en el resumen previo. Debe aparecer ahora.
        hop_stats = [_hs(5, ip="213.248.70.68", samples=2, success=1, loss_pct=50.0)]
        text = format_anomalies_text(hop_stats)
        assert "hop  5" in text
        assert "213.248.70.68" in text
        assert "50.0%" in text
        assert "samples=2" in text
        assert "success=1" in text

    def test_hop_con_perdida_parcial_n_moderado_aparece(self):
        # Escenario real: n=12, 11 exitos, 1 perdida -> 8.3% loss.
        hop_stats = [_hs(5, ip="213.248.70.68", samples=12, success=11, loss_pct=8.3)]
        text = format_anomalies_text(hop_stats)
        assert "hop  5" in text
        assert "8.3%" in text
        assert "samples=12" in text

    def test_hop_perdida_total_no_aparece_en_partial_si_solo_no_response(self):
        # loss 100% con success=0 -> se reporta como "sin respuesta",
        # no como perdida parcial. No debe mezclarse categorias.
        hop_stats = [_hs(3, ip=None, samples=4, success=0)]
        text = format_anomalies_text(hop_stats)
        assert "sin respuesta" in text
        assert "perdida parcial" not in text

    def test_varios_hops_solo_loss_parcial_se_listan_todos(self):
        # Regla fija: nunca omitir. Si hay 3 hops con perdida parcial,
        # los 3 aparecen en el output.
        hop_stats = [
            _hs(2, ip="10.0.0.1", samples=2, success=1, loss_pct=50.0),
            _hs(5, ip="213.248.70.68", samples=12, success=11, loss_pct=8.3),
            _hs(8, ip="104.16.0.1", samples=5, success=4, loss_pct=20.0),
        ]
        text = format_anomalies_text(hop_stats)
        assert "hop  2" in text
        assert "hop  5" in text
        assert "hop  8" in text
        assert "10.0.0.1" in text
        assert "213.248.70.68" in text
        assert "104.16.0.1" in text

    def test_sin_anomalias_devuelve_mensaje_conocido(self):
        hop_stats = [_hs(1, ip="1.1.1.1", samples=3, success=3, loss_pct=0.0)]
        text = format_anomalies_text(hop_stats)
        assert "sin anomalias observadas" in text

    def test_lista_vacia_devuelve_sin_anomalias(self):
        text = format_anomalies_text([])
        assert "sin anomalias observadas" in text

    def test_jitter_alto_se_reporta_cuando_supera_umbral(self):
        hop_stats = [
            _hs(4, ip="8.8.8.8", samples=3, success=3, loss_pct=0.0, jitter=35.0),
        ]
        text = format_anomalies_text(hop_stats)
        assert "jitter alto" in text
        assert "hop  4" in text
        assert "35.00ms" in text

    def test_jitter_bajo_no_se_reporta(self):
        hop_stats = [
            _hs(4, ip="8.8.8.8", samples=3, success=3, loss_pct=0.0, jitter=5.0),
        ]
        text = format_anomalies_text(hop_stats)
        assert "jitter alto" not in text

    def test_no_omitir_perdida_parcial_nunca_devuelve_vacio(self):
        # Invariante de presentacion: el resumen nunca es cadena vacia.
        text = format_anomalies_text([])
        assert text != ""
        assert isinstance(text, str)

    def test_categorias_se_combinan_en_un_solo_texto(self):
        # Mezcla: un hop sin respuesta, uno con perdida parcial,
        # uno con jitter alto, uno sano. El output debe mencionar
        # los 3 problematicos y no mencionar el sano.
        hop_stats = [
            _hs(2, ip=None, samples=3, success=0),  # sin respuesta
            _hs(5, ip="213.248.70.68", samples=2, success=1, loss_pct=50.0),
            _hs(7, ip="9.9.9.9", samples=4, success=4, loss_pct=0.0, jitter=30.0),
            _hs(9, ip="1.1.1.1", samples=4, success=4, loss_pct=0.0),  # sano
        ]
        text = format_anomalies_text(hop_stats)
        assert "hop  2" in text  # sin respuesta
        assert "hop  5" in text  # perdida parcial
        assert "hop  7" in text  # jitter
        # El sano (hop 9) no debe aparecer como anomalia.
        # (Aparece solo si otra categoria lo exhibe, pero no hay).
        assert "hop  9" not in text
