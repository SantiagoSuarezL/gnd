"""Tests de ActiveGameServerInfo y HistoricalBaseline."""

import pytest

from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.historical_baseline import HistoricalBaseline


class TestActiveGameServerInfo:
    def test_valido_udp(self) -> None:
        s = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="LoL.exe",
        )
        assert s.protocol == "udp"

    def test_valido_tcp(self) -> None:
        s = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=443,
            protocol="tcp",
            detected_via="live_client_api_confirmed",
            process_name="LoL.exe",
        )
        assert s.protocol == "tcp"

    def test_protocol_invalido_falla(self) -> None:
        with pytest.raises(ValueError, match="protocol debe ser 'udp' o 'tcp'"):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=5000,
                protocol="icmp",
                detected_via="process_connection_scan",
                process_name="LoL.exe",
            )

    def test_detected_via_invalido_falla(self) -> None:
        with pytest.raises(ValueError, match="detected_via inválido"):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=5000,
                protocol="udp",
                detected_via="magic",
                process_name="LoL.exe",
            )

    def test_port_fuera_de_rango_falla(self) -> None:
        with pytest.raises(ValueError, match="port debe estar en \\[1, 65535\\]"):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=0,
                protocol="udp",
                detected_via="process_connection_scan",
                process_name="LoL.exe",
            )
        with pytest.raises(ValueError, match="port debe estar en \\[1, 65535\\]"):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=65536,
                protocol="udp",
                detected_via="process_connection_scan",
                process_name="LoL.exe",
            )

    def test_campos_vacios_falla(self) -> None:
        with pytest.raises(ValueError, match="ip no puede ser vacío"):
            ActiveGameServerInfo(
                ip="",
                port=5000,
                protocol="udp",
                detected_via="process_connection_scan",
                process_name="LoL.exe",
            )
        with pytest.raises(ValueError, match="process_name no puede ser vacío"):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=5000,
                protocol="udp",
                detected_via="process_connection_scan",
                process_name="",
            )


class TestActiveGameServerInfoFase14a:
    """Tests de la extensión Phase 14.0a: precision_tier y region_tag."""

    def test_defaults_backwards_compat(self) -> None:
        """Constructores pre-Fase 14 (sin precision_tier/region_tag) siguen funcionando."""
        s = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="LoL.exe",
        )
        assert s.precision_tier == "proxy_login"
        assert s.region_tag is None

    def test_detected_via_lcu_gameflow_aceptado(self) -> None:
        s = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=5000,
            protocol="udp",
            detected_via="lcu_gameflow",  # nuevo valor Phase 14.0a
            process_name="League of Legends.exe",
            precision_tier="exact_ip",
            region_tag="LA1",
        )
        assert s.detected_via == "lcu_gameflow"
        assert s.precision_tier == "exact_ip"
        assert s.region_tag == "LA1"

    def test_precision_tier_desconocido_rechaza(self) -> None:
        with pytest.raises(ValueError, match="precision_tier debe ser uno de"):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=5000,
                protocol="udp",
                detected_via="lcu_gameflow",
                process_name="LoL.exe",
                precision_tier="regional_edge",  # no habilitado en 14.0a
            )

    def test_region_tag_vacio_rechaza(self) -> None:
        with pytest.raises(
            ValueError, match="region_tag debe ser None o un str no vacío"
        ):
            ActiveGameServerInfo(
                ip="1.2.3.4",
                port=5000,
                protocol="udp",
                detected_via="lcu_gameflow",
                process_name="LoL.exe",
                precision_tier="exact_ip",
                region_tag="",
            )

    def test_proxy_login_con_region_tag_none_aceptado(self) -> None:
        """Caso típico de fallback: proxy_login + region_tag=None."""
        s = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=443,
            protocol="tcp",
            detected_via="live_client_api_confirmed",
            process_name="LoL.exe",
            precision_tier="proxy_login",
            region_tag=None,
        )
        assert s.precision_tier == "proxy_login"
        assert s.region_tag is None


class TestHistoricalBaseline:
    def test_valido(self) -> None:
        b = HistoricalBaseline(
            provider="google",
            period_days=30,
            avg_ms=20.0,
            stddev_ms=5.0,
            sample_count=100,
        )
        assert b.stddev_ms == 5.0

    def test_period_days_cero_falla(self) -> None:
        with pytest.raises(ValueError, match="period_days debe ser >= 1"):
            HistoricalBaseline(
                provider="google",
                period_days=0,
                avg_ms=20.0,
                stddev_ms=5.0,
                sample_count=100,
            )

    def test_sample_count_1_stddev_debe_ser_cero(self) -> None:
        with pytest.raises(ValueError, match="stddev_ms debe ser 0 si sample_count<=1"):
            HistoricalBaseline(
                provider="google",
                period_days=30,
                avg_ms=20.0,
                stddev_ms=5.0,
                sample_count=1,
            )

    def test_sample_count_negativo_falla(self) -> None:
        with pytest.raises(ValueError, match="sample_count debe ser >= 0"):
            HistoricalBaseline(
                provider="google",
                period_days=30,
                avg_ms=20.0,
                stddev_ms=0.0,
                sample_count=-1,
            )

    def test_valores_negativos_falla(self) -> None:
        with pytest.raises(ValueError, match="avg_ms debe ser >= 0"):
            HistoricalBaseline(
                provider="google",
                period_days=30,
                avg_ms=-1.0,
                stddev_ms=0.0,
                sample_count=0,
            )
        with pytest.raises(ValueError, match="stddev_ms debe ser >= 0"):
            HistoricalBaseline(
                provider="google",
                period_days=30,
                avg_ms=20.0,
                stddev_ms=-1.0,
                sample_count=0,
            )

    def test_provider_vacio_falla(self) -> None:
        with pytest.raises(ValueError, match="provider no puede ser vacío"):
            HistoricalBaseline(
                provider="", period_days=30, avg_ms=20.0, stddev_ms=0.0, sample_count=0
            )
