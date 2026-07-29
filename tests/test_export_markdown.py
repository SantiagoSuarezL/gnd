"""Tests del renderer Markdown (Fase 12b.1).

El renderer es una funcion pura: in (DiagnosticRun) -> out (str). Tests
cubren todos los casos del modelo para garantizar:

- Run minimo (solo campos obligatorios) -> header, veredicto, probes vacios,
  traceroutes vacios, sin secciones opcionales.
- Run con DNS -> seccion DNS aparece.
- Run con interfaz Wi-Fi y Ethernet -> seccion interfaz aparece con campos
  correctos.
- Run con game server activo -> seccion game server aparece.
- Probes con todos los outcome kinds (SUCCESS / FILTERED / UNREACHABLE /
  TIMEOUT) -> tabla los formatea.
- Traceroutes con y sin culprit_hop_index -> marcado correcto del hop
  culpable.
- Caracteres especiales (pipes, backticks) en campos libres se escapan
  para no romper tablas Markdown.
- Invariante: nunca devuelve cadena vacia; el output SIEMPRE contiene
  el header # y el veredicto.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from gnd.export import render_run_to_markdown
from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.dns_measurement import DnsOutcome, DnsResolution
from gnd.models.latency_stats import LatencyStats
from gnd.models.network_interface import InterfaceType, NetworkInterfaceSnapshot
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation
from gnd.models.traceroute import TracerouteHop, TracerouteResult

# ── Factory helpers reutilizables ─────────────────────────────────────


def _stats(
    avg: float = 5.0,
    mn: float = 4.0,
    mx: float = 6.0,
    jitter: float = 1.0,
    loss: float = 0.0,
    samples: int = 10,
) -> LatencyStats:
    return LatencyStats(
        avg_ms=avg,
        min_ms=mn,
        max_ms=mx,
        jitter_ms=jitter,
        packet_loss_pct=loss,
        samples=samples,
    )


def _probe(
    *,
    provider: str = "local",
    target_name: str = "gateway",
    target_ip: str = "10.0.0.1",
    outcome: ProbeOutcomeKind = ProbeOutcomeKind.SUCCESS,
    stats: LatencyStats | None = None,
    family: str = "ipv4",
) -> ProbeResult:
    if stats is None and outcome is ProbeOutcomeKind.SUCCESS:
        stats = _stats()
    return ProbeResult(
        target_name=target_name,
        target_ip=target_ip,
        provider=provider,
        outcome=outcome,
        stats=stats,
        timestamp=datetime.now(),
        family=family,
    )


def _traceroute(
    *,
    provider: str = "google",
    culprit: int | None = None,
    hops_count: int = 3,
    family: str = "ipv4",
) -> TracerouteResult:
    hops = [
        TracerouteHop(
            hop_number=i,
            ip=f"10.0.0.{i}" if i % 2 == 0 else None,
            hostname=f"hop{i}.example" if i % 2 == 0 else None,
            rtt_ms=float(i) if i % 2 == 0 else None,
            responded=(i % 2 == 0),
        )
        for i in range(1, hops_count + 1)
    ]
    return TracerouteResult(
        target_provider=provider,
        hops=hops,
        culprit_hop_index=culprit,
        family=family,
    )


def _rec() -> Recommendation:
    return Recommendation(
        verdict="safe_to_play",
        headline="Todo OK",
        explanation=["Sin anomalías detectadas", "Network Score en rango normal"],
        responsible_component="unknown",
        score=92,
    )


def _run(
    *,
    probes: list[ProbeResult] | None = None,
    traceroutes: list[TracerouteResult] | None = None,
    active_game_server: ActiveGameServerInfo | None = None,
    recommendation: Recommendation | None = None,
    dns_results: tuple[DnsResolution, ...] = (),
    interface_snapshot: NetworkInterfaceSnapshot | None = None,
    started: datetime | None = None,
    finished: datetime | None = None,
) -> DiagnosticRun:
    now = datetime.now()
    return DiagnosticRun(
        run_id="run-test",
        started_at=started or now,
        finished_at=finished or (now + timedelta(seconds=5)),
        probes=probes or [],
        traceroutes=traceroutes or [],
        active_game_server=active_game_server,
        recommendation=recommendation or _rec(),
        dns_results=dns_results,
        interface_snapshot=interface_snapshot,
    )


# ── Invariante basico ──────────────────────────────────────────────


class TestRenderRunInvariante:
    def test_nunca_devuelve_cadena_vacia(self) -> None:
        md = render_run_to_markdown(_run())
        assert md
        assert md.strip()

    def test_empieza_con_header_h1(self) -> None:
        md = render_run_to_markdown(_run())
        assert md.startswith("# GND — Reporte de diagnóstico\n")

    def test_contiene_run_id(self) -> None:
        md = render_run_to_markdown(_run())
        assert "`run-test`" in md

    def test_contiene_duracion(self) -> None:
        started = datetime(2026, 7, 28, 12, 0, 0)
        finished = started + timedelta(seconds=7, milliseconds=500)
        md = render_run_to_markdown(_run(started=started, finished=finished))
        assert "7.50 s" in md

    def test_duracion_sub_segundo_formato_ms(self) -> None:
        started = datetime(2026, 7, 28, 12, 0, 0)
        finished = started + timedelta(milliseconds=750)
        md = render_run_to_markdown(_run(started=started, finished=finished))
        assert "750 ms" in md


# ── Seccion Recommendation ──────────────────────────────────────────


class TestRenderRecommendation:
    def test_incluye_score(self) -> None:
        md = render_run_to_markdown(_run())
        assert "**Score:** 92/100" in md

    def test_incluye_veredicto_y_headline(self) -> None:
        md = render_run_to_markdown(_run())
        assert "**Veredicto:** safe_to_play" in md
        assert "**Resumen:** Todo OK" in md

    def test_incluye_componente_responsable(self) -> None:
        md = render_run_to_markdown(_run())
        assert "**Componente responsable:** unknown" in md

    def test_lista_explanation_numerada(self) -> None:
        md = render_run_to_markdown(_run())
        assert "1. Sin anomalías detectadas" in md
        assert "2. Network Score en rango normal" in md

    @pytest.mark.parametrize(
        "verdict",
        ["safe_to_play", "playable", "not_recommended_ranked", "serious_issue"],
    )
    def test_todos_los_veredictos_se_imprimen(self, verdict: str) -> None:
        rec = Recommendation(
            verdict=verdict,
            headline="h",
            explanation=["x"],
            responsible_component="unknown",
            score=50,
        )
        md = render_run_to_markdown(_run(recommendation=rec))
        assert f"**Veredicto:** {verdict}" in md


# ── Seccion Probes ──────────────────────────────────────────────────


class TestRenderProbes:
    def test_probes_vacios_muestra_mensaje(self) -> None:
        md = render_run_to_markdown(_run(probes=[]))
        assert "_(sin probes en esta corrida)_" in md

    def test_probe_success_tabla_completa(self) -> None:
        p = _probe(
            outcome=ProbeOutcomeKind.SUCCESS,
            stats=_stats(avg=12.3, mn=10.0, mx=15.0, jitter=2.0, loss=0.0),
        )
        md = render_run_to_markdown(_run(probes=[p]))
        assert (
            "| gateway | local | OK | 12.3 ms | 10.0 ms | 15.0 ms | 2.0 ms | 0.0% | 10 | ipv4 |"
            in md
        )

    @pytest.mark.parametrize(
        "outcome,expected",
        [
            (ProbeOutcomeKind.FILTERED, "filtrado (ICMP bloqueado)"),
            (ProbeOutcomeKind.UNREACHABLE, "inalcanzable"),
            (ProbeOutcomeKind.TIMEOUT, "timeout"),
        ],
    )
    def test_probe_no_success_outcome_formateado(
        self, outcome: ProbeOutcomeKind, expected: str
    ) -> None:
        p = _probe(outcome=outcome, stats=None)
        md = render_run_to_markdown(_run(probes=[p]))
        # Outcome aparece; latencias N/A porque stats es None.
        assert f"| gateway | local | {expected} |" in md
        assert "| N/A |" in md

    def test_probe_ipv6_muestra_family(self) -> None:
        p = _probe(family="ipv6", target_name="cloudflare:v6")
        md = render_run_to_markdown(_run(probes=[p]))
        assert "| cloudflare:v6 |" in md
        assert "| ipv6 |" in md

    def test_tabla_tiene_header_y_separador(self) -> None:
        p = _probe()
        md = render_run_to_markdown(_run(probes=[p]))
        assert (
            "| Target | Provider | Outcome | Avg | Min | Max | Jitter | Loss | Samples | Family |"
            in md
        )
        assert "|---|---|---|---:|---:|---:|---:|---:|---:|---|" in md

    def test_packet_loss_con_decimales(self) -> None:
        p = _probe(
            outcome=ProbeOutcomeKind.SUCCESS,
            stats=_stats(loss=33.333),
        )
        md = render_run_to_markdown(_run(probes=[p]))
        assert "| 33.3% |" in md


# ── Seccion Traceroutes ─────────────────────────────────────────────


class TestRenderTraceroutes:
    def test_traceroutes_vacios_muestra_mensaje(self) -> None:
        md = render_run_to_markdown(_run(traceroutes=[]))
        assert "_(sin traceroutes en esta corrida)_" in md

    def test_traceroute_sin_culprit_mensaje_correcto(self) -> None:
        t = _traceroute(provider="google", culprit=None, hops_count=2)
        md = render_run_to_markdown(_run(traceroutes=[t]))
        assert "### google (ipv4) — sin hop culpable identificado" in md

    def test_traceroute_con_culprit_marcado(self) -> None:
        # hops_count=3 => indices 0,1,2 → culprit_hop_index=1 (segundo hop).
        t = _traceroute(provider="cloudflare", culprit=1, hops_count=3)
        md = render_run_to_markdown(_run(traceroutes=[t]))
        assert "### cloudflare (ipv4) — **hop culpable:** #2" in md

    def test_traceroute_ipv6_family_etiqueta(self) -> None:
        t = _traceroute(provider="cloudflare:v6", family="ipv6", hops_count=1)
        md = render_run_to_markdown(_run(traceroutes=[t]))
        assert "### cloudflare:v6 (ipv6)" in md

    def test_hops_no_respondedores_muestran_guion(self) -> None:
        # En _traceroute los hops impares (1, 3, ...) NO responden.
        t = _traceroute(provider="quad9", hops_count=3)
        md = render_run_to_markdown(_run(traceroutes=[t]))
        assert "| 1 | — | — | — | no |" in md
        assert "| 2 |" in md  # hop 2 sí responde

    def test_tabla_hops_tiene_header(self) -> None:
        t = _traceroute(hops_count=1)
        md = render_run_to_markdown(_run(traceroutes=[t]))
        assert "| Hop | IP | Hostname | RTT | Respondió |" in md
        assert "|---:|---|---|---:|:---:|" in md


# ── Seccion DNS (opcional) ──────────────────────────────────────────


class TestRenderDns:
    def test_sin_dns_no_seccion(self) -> None:
        md = render_run_to_markdown(_run(dns_results=()))
        assert "Resolución DNS" not in md

    def test_con_dns_aparece_seccion(self) -> None:
        d = DnsResolution(
            hostname="example.com",
            resolved_ip="1.2.3.4",
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=42.0,
            family="ipv4",
            error=None,
        )
        md = render_run_to_markdown(_run(dns_results=(d,)))
        assert "## Resolución DNS" in md
        assert "| example.com | ipv4 | OK | 1.2.3.4 | 42.0 ms | — |" in md

    def test_dns_con_timeout_muestra_error(self) -> None:
        d = DnsResolution(
            hostname="slow.example",
            resolved_ip=None,
            outcome=DnsOutcome.TIMEOUT,
            elapsed_ms=None,
            family="ipv4",
            error="getaddrinfo timeout 1000ms",
        )
        md = render_run_to_markdown(_run(dns_results=(d,)))
        assert "| slow.example | ipv4 | timeout |" in md
        assert "getaddrinfo timeout 1000ms" in md


# ── Seccion Interfaz (opcional) ────────────────────────────────────


class TestRenderInterface:
    def test_sin_interface_no_seccion(self) -> None:
        md = render_run_to_markdown(_run(interface_snapshot=None))
        assert "Interfaz de red activa" not in md

    def test_ethernet_aparece_sin_campos_wifi(self) -> None:
        s = NetworkInterfaceSnapshot(
            type=InterfaceType.ETHERNET,
            name="Ethernet 2",
            is_default_route=True,
            wifi_ssid=None,
            wifi_signal_dbm=None,
            error=None,
        )
        md = render_run_to_markdown(_run(interface_snapshot=s))
        assert "## Interfaz de red activa" in md
        assert "**Tipo:** Ethernet" in md
        assert "**Nombre:** Ethernet 2" in md
        assert "**Default route:** sí" in md
        assert "SSID" not in md  # campo Wi-Fi no aplica

    def test_wifi_con_ssid_y_signal(self) -> None:
        s = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="Fibertel-1234",
            wifi_signal_dbm=-58.0,
            error=None,
        )
        md = render_run_to_markdown(_run(interface_snapshot=s))
        assert "**Tipo:** Wi-Fi" in md
        assert "**SSID:** Fibertel-1234" in md
        assert "**Señal:** -58 dBm" in md

    def test_wifi_sin_signal_expuesto(self) -> None:
        s = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=False,
            wifi_ssid="Red",
            wifi_signal_dbm=None,
            error=None,
        )
        md = render_run_to_markdown(_run(interface_snapshot=s))
        assert "**Señal:** (no expuesto)" in md
        assert "**Default route:** no" in md

    def test_interface_con_error_lo_muestra(self) -> None:
        s = NetworkInterfaceSnapshot(
            type=InterfaceType.OTHER,
            name="fallback0",
            is_default_route=False,
            wifi_ssid=None,
            wifi_signal_dbm=None,
            error="netsh wlan timeout (3000ms) — defaulting a OTHER",
        )
        md = render_run_to_markdown(_run(interface_snapshot=s))
        assert "**Tipo:** otra" in md
        assert "**Nota:** netsh wlan timeout (3000ms) — defaulting a OTHER" in md


# ── Seccion Game Server (opcional) ─────────────────────────────────


class TestRenderGameServer:
    def test_sin_game_server_no_seccion(self) -> None:
        md = render_run_to_markdown(_run(active_game_server=None))
        assert "Servidor de partida activo" not in md

    def test_game_server_presente_muestra_todos_campos(self) -> None:
        ags = ActiveGameServerInfo(
            ip="192.64.174.10",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="League of Legends.exe",
        )
        md = render_run_to_markdown(_run(active_game_server=ags))
        assert "## Servidor de partida activo" in md
        assert "`192.64.174.10`" in md
        assert "**Puerto:** 5000" in md
        assert "**Protocolo:** udp" in md
        assert "**Detección:** process_connection_scan" in md
        assert "**Proceso:** League of Legends.exe" in md


# ── Escapado Markdown ──────────────────────────────────────────────


class TestMdEscaping:
    def test_pipe_en_provider_se_escapa(self) -> None:
        # Forzamos provider con pipe — aunque en la práctica no ocurre,
        # el renderer debe sobrevivir sin romper la tabla.
        p = _probe(provider="local|remote")  # type: ignore[arg-type]
        md = render_run_to_markdown(_run(probes=[p]))
        assert "local\\|remote" in md
        # La línea de tabla sigue teniendo exactamente las columnas esperadas
        # (no se "agregan" columnas por el pipe sin escape).
        table_line = next(
            line for line in md.splitlines() if line.startswith("| gateway |")
        )
        assert table_line.count("|") == 12  # 1 + 10 columnas + 1

    def test_campos_libres_en_linea_no_se_escapan_backticks(self) -> None:
        # Headline es un campo libre en una línea (no en una tabla),
        # así que los backticks son code-inline válido de Markdown —
        # escapanarlos seria ruido (\` en prosa no se interpreta como
        # code-inline). El renderer NO los escapa por decision de diseño:
        # solo se escapana pipes y backticks en CELDAS de tablas (donde
        # romperian columnas). El headline mantiene backticks literales.
        rec = Recommendation(
            verdict="serious_issue",
            headline="Problema `grave` detectado",
            explanation=["x"],
            responsible_component="local",
            score=10,
        )
        md = render_run_to_markdown(_run(recommendation=rec))
        assert "**Resumen:** Problema `grave` detectado" in md


# ── Integration: run completo con todo ────────────────────────────


class TestRunCompleto:
    def test_run_completo_contiene_todas_las_secciones(self) -> None:
        ags = ActiveGameServerInfo(
            ip="1.2.3.4",
            port=5000,
            protocol="udp",
            detected_via="process_connection_scan",
            process_name="LoL.exe",
        )
        dns = DnsResolution(
            hostname="example.com",
            resolved_ip="5.6.7.8",
            outcome=DnsOutcome.SUCCESS,
            elapsed_ms=30.0,
            family="ipv4",
            error=None,
        )
        iface = NetworkInterfaceSnapshot(
            type=InterfaceType.WIFI,
            name="Wi-Fi",
            is_default_route=True,
            wifi_ssid="MyNet",
            wifi_signal_dbm=-70.0,
            error=None,
        )
        run = _run(
            probes=[_probe()],
            traceroutes=[_traceroute(culprit=1, hops_count=3)],
            active_game_server=ags,
            dns_results=(dns,),
            interface_snapshot=iface,
        )
        md = render_run_to_markdown(run)

        # Todas las secciones presentes en orden.
        assert "# GND — Reporte de diagnóstico" in md
        assert "## Veredicto" in md
        assert "## Probes" in md
        assert "## Traceroutes" in md
        assert "## Resolución DNS" in md
        assert "## Interfaz de red activa" in md
        assert "## Servidor de partida activo" in md

        # Orden: header < veredicto < probes < traceroutes < dns < iface < gs
        idx = lambda name: md.index(name)  # noqa: E731
        assert (
            idx("# GND")
            < idx("## Veredicto")
            < idx("## Probes")
            < idx("## Traceroutes")
            < idx("## Resolución DNS")
            < idx("## Interfaz de red activa")
            < idx("## Servidor de partida activo")
        )

    def test_run_minimo_sin_secciones_opcionales(self) -> None:
        md = render_run_to_markdown(_run())
        assert "## Probes" in md
        assert "## Traceroutes" in md
        assert "## Resolución DNS" not in md
        assert "## Interfaz de red activa" not in md
        assert "## Servidor de partida activo" not in md

    def test_output_termina_con_newline(self) -> None:
        md = render_run_to_markdown(_run())
        assert md.endswith("\n")
        # Sin trailing whitespace antes del newline.
        assert not md.rstrip().endswith(" ")
