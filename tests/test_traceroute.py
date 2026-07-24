"""Tests de TracerouteHop y TracerouteResult."""

import pytest

from gnd.models.traceroute import TracerouteHop, TracerouteResult


class TestTracerouteHop:
    def test_hop_valido_responded_true(self) -> None:
        h = TracerouteHop(
            hop_number=1,
            ip="1.2.3.4",
            hostname="r1.example.com",
            rtt_ms=10.0,
            responded=True,
        )
        assert h.responded is True

    def test_hop_responded_true_sin_rtt_falla(self) -> None:
        with pytest.raises(
            ValueError, match="rtt_ms no puede ser None si responded=True"
        ):
            TracerouteHop(
                hop_number=1, ip="1.2.3.4", hostname=None, rtt_ms=None, responded=True
            )

    def test_hop_responded_false_rtt_none_ok(self) -> None:
        h = TracerouteHop(
            hop_number=2, ip=None, hostname=None, rtt_ms=None, responded=False
        )
        assert h.rtt_ms is None

    def test_hop_number_cero_falla(self) -> None:
        with pytest.raises(ValueError, match="hop_number debe ser >= 1"):
            TracerouteHop(
                hop_number=0, ip=None, hostname=None, rtt_ms=None, responded=False
            )

    def test_rtt_negativo_falla(self) -> None:
        with pytest.raises(ValueError, match="rtt_ms debe ser >= 0"):
            TracerouteHop(
                hop_number=1, ip="1.2.3.4", hostname=None, rtt_ms=-1.0, responded=True
            )


class TestTracerouteResult:
    def test_valido(self) -> None:
        r = TracerouteResult(
            target_provider="google",
            hops=[
                TracerouteHop(
                    hop_number=1,
                    ip="8.8.8.8",
                    hostname=None,
                    rtt_ms=10.0,
                    responded=True,
                )
            ],
            culprit_hop_index=None,
        )
        assert r.culprit_hop_index is None

    def test_culprit_fuera_de_rango_falla(self) -> None:
        with pytest.raises(ValueError, match="culprit_hop_index fuera de rango"):
            TracerouteResult(
                target_provider="google",
                hops=[
                    TracerouteHop(
                        hop_number=1,
                        ip="8.8.8.8",
                        hostname=None,
                        rtt_ms=10.0,
                        responded=True,
                    )
                ],
                culprit_hop_index=5,  # solo hay 1 hop
            )

    def test_culprit_valido(self) -> None:
        r = TracerouteResult(
            target_provider="google",
            hops=[
                TracerouteHop(
                    hop_number=1,
                    ip="10.0.0.1",
                    hostname=None,
                    rtt_ms=1.0,
                    responded=True,
                ),
                TracerouteHop(
                    hop_number=2,
                    ip="8.8.8.8",
                    hostname=None,
                    rtt_ms=10.0,
                    responded=True,
                ),
            ],
            culprit_hop_index=1,
        )
        assert r.culprit_hop_index == 1

    def test_hops_vacio_falla(self) -> None:
        with pytest.raises(ValueError, match="hops no puede ser vacío"):
            TracerouteResult(target_provider="google", hops=[], culprit_hop_index=None)

    def test_target_provider_vacio_falla(self) -> None:
        with pytest.raises(ValueError, match="target_provider no puede ser vacío"):
            TracerouteResult(
                target_provider="",
                hops=[
                    TracerouteHop(
                        hop_number=1,
                        ip="8.8.8.8",
                        hostname=None,
                        rtt_ms=10.0,
                        responded=True,
                    )
                ],
                culprit_hop_index=None,
            )
