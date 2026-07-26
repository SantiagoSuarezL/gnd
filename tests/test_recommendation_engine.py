"""Tests del motor de recomendacion — Fase 5.

Matriz de tests con TODAS las combinaciones relevantes
(IMPLEMENTATION_PLAN.md Fase 5 DoD).

Regla de oro: invariante "nunca safe_to_play si packet_loss >= critical"
es el test que mas importa de toda la fase.
"""

from datetime import datetime

import pytest

from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.recommendations.engine import (
    _get_probe,
    _is_degraded,
    _is_healthy,
    _rule1_gateway_local,
    _rule2_isp_degraded,
    _rule3_cloudflare_degraded,
    _rule4_riot_degraded,
    _rule5_riot_server_worse_than_baseline,
    evaluate_recommendation,
)

# ── Defaults ───────────────────────────────────────────────────────────

packet_loss_warning_pct = 1.0
packet_loss_critical_pct = 3.0
jitter_warning_ms = 20.0
jitter_critical_ms = 40.0

DEFAULTS = dict(
    packet_loss_warning_pct=packet_loss_warning_pct,
    packet_loss_critical_pct=packet_loss_critical_pct,
    jitter_warning_ms=jitter_warning_ms,
    jitter_critical_ms=jitter_critical_ms,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _probe(
    provider: str,
    avg_ms: float = 10.0,
    packet_loss: float = 0.0,
    jitter: float = 2.0,
    *,
    outcome: ProbeOutcomeKind = ProbeOutcomeKind.SUCCESS,
) -> ProbeResult:
    """Crea un ProbeResult con stats o sin ellos segun outcome."""
    stats = None
    if outcome == ProbeOutcomeKind.SUCCESS:
        stats = LatencyStats(
            avg_ms=avg_ms,
            min_ms=max(0, avg_ms - 5),
            max_ms=avg_ms + 5,
            jitter_ms=jitter,
            packet_loss_pct=packet_loss,
            samples=10,
        )
    return ProbeResult(
        target_name=f"t-{provider}",
        target_ip="1.2.3.4",
        provider=provider,
        outcome=outcome,
        stats=stats,
        timestamp=datetime.now(),
    )


def _filtered(provider: str) -> ProbeResult:
    """Probe que no responde (FILTERED = ICMP bloqueado)."""
    return _probe(provider, outcome=ProbeOutcomeKind.FILTERED)


def _timeout(provider: str) -> ProbeResult:
    """Probe con timeout."""
    return _probe(provider, outcome=ProbeOutcomeKind.TIMEOUT)


def _full_set(**overrides) -> list[ProbeResult]:
    """Set completo de probes sanos. Sobreescribe con kwargs."""
    defaults = dict(
        google_avg=10.0,
        cf_avg=12.0,
        quad9_avg=11.0,
        local_avg=5.0,
        riot_server_avg=25.0,
        riot_public_avg=20.0,
    )
    defaults.update(overrides)
    return [
        _probe("google", avg_ms=defaults["google_avg"]),
        _probe("cloudflare", avg_ms=defaults["cf_avg"]),
        _probe("quad9", avg_ms=defaults["quad9_avg"]),
        _probe("local", avg_ms=defaults["local_avg"]),
        _probe("riot_game_server", avg_ms=defaults["riot_server_avg"]),
        _probe("riot_public", avg_ms=defaults["riot_public_avg"]),
    ]


# ── Tests: helpers ─────────────────────────────────────────────────────


def test_get_probe_returns_last_match() -> None:
    probes = [_probe("google", 10.0), _probe("google", 20.0)]
    assert _get_probe(probes, "google").stats.avg_ms == 20.0


def test_get_probe_missing_returns_none() -> None:
    assert _get_probe([_probe("google")], "cloudflare") is None


def test_is_healthy_true() -> None:
    assert _is_healthy(_probe("google")) is True


def test_is_healthy_filtered() -> None:
    assert _is_healthy(_filtered("google")) is False


def test_is_healthy_none() -> None:
    assert _is_healthy(None) is False


def test_is_degraded_inverted() -> None:
    assert _is_degraded(_probe("google")) is False
    assert _is_degraded(_filtered("google")) is True


# ── Tests: Regla 1 — Gateway local ────────────────────────────────────


def test_rule1_gw_packet_loss_critical() -> None:
    """GW con loss critico → serious_issue, local."""
    probes = _full_set() + [_probe("local", packet_loss=4.0)]
    # El ultimo probe "local" sobreescribe al primero
    r = _rule1_gateway_local(
        probes,
        packet_loss_critical_pct=3.0,
        packet_loss_warning_pct=1.0,
        jitter_critical_ms=40.0,
        jitter_warning_ms=20.0,
    )
    assert r is not None
    assert r.verdict == "serious_issue"
    assert r.responsible_component == "local"


def test_rule1_gw_jitter_critical() -> None:
    """GW con jitter critico → serious_issue, local."""
    probes = _full_set() + [_probe("local", jitter=50.0)]
    r = _rule1_gateway_local(
        probes,
        packet_loss_critical_pct=3.0,
        packet_loss_warning_pct=1.0,
        jitter_critical_ms=40.0,
        jitter_warning_ms=20.0,
    )
    assert r is not None
    assert r.verdict == "serious_issue"
    assert r.responsible_component == "local"


def test_rule1_gw_packet_loss_warning() -> None:
    """GW con loss.warning → not_recommended_ranked, local."""
    probes = _full_set() + [_probe("local", packet_loss=1.5)]
    r = _rule1_gateway_local(
        probes,
        packet_loss_critical_pct=3.0,
        packet_loss_warning_pct=1.0,
        jitter_critical_ms=40.0,
        jitter_warning_ms=20.0,
    )
    assert r is not None
    assert r.verdict == "not_recommended_ranked"
    assert r.responsible_component == "local"


def test_rule1_gw_jitter_warning() -> None:
    """GW con jitter warning → not_recommended_ranked, local."""
    probes = _full_set() + [_probe("local", jitter=25.0)]
    r = _rule1_gateway_local(
        probes,
        packet_loss_critical_pct=3.0,
        packet_loss_warning_pct=1.0,
        jitter_critical_ms=40.0,
        jitter_warning_ms=20.0,
    )
    assert r is not None
    assert r.verdict == "not_recommended_ranked"


def test_rule1_gw_healthy_no_match() -> None:
    """GW sano → no match."""
    probes = _full_set()
    r = _rule1_gateway_local(
        probes,
        packet_loss_critical_pct=3.0,
        packet_loss_warning_pct=1.0,
        jitter_critical_ms=40.0,
        jitter_warning_ms=20.0,
    )
    assert r is None


def test_rule1_gw_missing_no_match() -> None:
    """GW no existe → no match (no penaliza)."""
    probes = [p for p in _full_set() if p.provider != "local"]
    r = _rule1_gateway_local(
        probes,
        packet_loss_critical_pct=3.0,
        packet_loss_warning_pct=1.0,
        jitter_critical_ms=40.0,
        jitter_warning_ms=20.0,
    )
    assert r is None


# ── Tests: Regla 2 — ISP degradado ────────────────────────────────────


def test_rule2_all_dns_degraded() -> None:
    """Google+CF+Quad9 todos degradados → ISP."""
    probes = [_filtered("google"), _filtered("cloudflare"), _filtered("quad9")]
    r = _rule2_isp_degraded(probes)
    assert r is not None
    assert r.verdict == "serious_issue"
    assert r.responsible_component == "isp"


def test_rule2_two_dns_degraded_no_match() -> None:
    """Solo 2 DNS degradados → no match (rule 3 puede aplicar)."""
    probes = [_filtered("google"), _filtered("cloudflare"), _probe("quad9")]
    r = _rule2_isp_degraded(probes)
    assert r is None


def test_rule2_one_dns_degraded_no_match() -> None:
    """Solo 1 DNS degradado → no match."""
    probes = [_probe("google"), _filtered("cloudflare"), _probe("quad9")]
    r = _rule2_isp_degraded(probes)
    assert r is None


def test_rule2_all_dns_healthy_no_match() -> None:
    """Todos sanos → no match."""
    probes = _full_set()
    r = _rule2_isp_degraded(probes)
    assert r is None


# ── Tests: Regla 3 — Cloudflare degradado ─────────────────────────────


def test_rule3_cf_degraded_google_quad9_ok() -> None:
    """CF degradado, Google+Quad9 OK → cloudflare."""
    probes = [_probe("google"), _filtered("cloudflare"), _probe("quad9")]
    r = _rule3_cloudflare_degraded(probes)
    assert r is not None
    assert r.verdict == "playable"
    assert r.responsible_component == "cloudflare"


def test_rule3_cf_ok_no_match() -> None:
    """CF OK → no match."""
    probes = _full_set()
    r = _rule3_cloudflare_degraded(probes)
    assert r is None


def test_rule3_cf_and_google_degraded_no_match() -> None:
    """CF+Google degradados → no match (rule 2 podria aplicar si Quad9 tambien)."""
    probes = [_filtered("google"), _filtered("cloudflare"), _probe("quad9")]
    r = _rule3_cloudflare_degraded(probes)
    assert r is None


# ── Tests: Regla 4 — Riot degradado ───────────────────────────────────


def test_rule4_riot_server_degraded_internet_ok() -> None:
    """Game server degradado, internet OK → riot, not_recommended_ranked."""
    probes = _full_set() + [_filtered("riot_game_server")]
    r = _rule4_riot_degraded(probes)
    assert r is not None
    assert r.verdict == "not_recommended_ranked"
    assert r.responsible_component == "riot"


def test_rule4_riot_public_degraded_no_game_server() -> None:
    """Riot public degradado, no hay game server, internet OK → riot, playable."""
    probes = [p for p in _full_set() if p.provider != "riot_game_server"]
    probes.append(_filtered("riot_public"))
    r = _rule4_riot_degraded(probes)
    assert r is not None
    assert r.verdict == "playable"
    assert r.responsible_component == "riot"


def test_rule4_both_riot_degraded() -> None:
    """Ambos Riot degradados → riot, not_recommended_ranked."""
    probes = _full_set()
    # Reemplazar ambos probes de riot con filtered
    probes = [
        p for p in probes if p.provider not in ("riot_game_server", "riot_public")
    ]
    probes.extend([_filtered("riot_game_server"), _filtered("riot_public")])
    r = _rule4_riot_degraded(probes)
    assert r is not None
    assert r.verdict == "not_recommended_ranked"
    assert r.responsible_component == "riot"


def test_rule4_internet_not_ok_no_match() -> None:
    """Internet no OK → rule 4 no matchea (rule 2 dispara primero)."""
    probes = [_filtered("google"), _filtered("cloudflare"), _filtered("quad9")]
    r = _rule4_riot_degraded(probes)
    assert r is None


def test_rule4_all_healthy_no_match() -> None:
    """Todo OK → no match."""
    probes = _full_set()
    r = _rule4_riot_degraded(probes)
    assert r is None


# ── Tests: Prioridad de reglas ────────────────────────────────────────


def test_priority_gw_before_isp() -> None:
    """GW inestable + ISP degradado → rule 1 gana (local, no isp)."""
    probes = [_filtered("google"), _filtered("cloudflare"), _filtered("quad9")]
    probes.append(_probe("local", packet_loss=5.0))
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "local"
    assert rec.verdict == "serious_issue"


def test_priority_isp_before_cloudflare() -> None:
    """ISP degradado + CF degradado → rule 2 gana (isp, no cloudflare)."""
    probes = [_filtered("google"), _filtered("cloudflare"), _filtered("quad9")]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "isp"


def test_priority_cloudflare_before_riot() -> None:
    """CF degradado + Riot degradado, internet OK → rule 3 gana (cloudflare)."""
    # CF filtered, Google+Quad9 OK, Riot degraded
    probes = [_probe("google"), _filtered("cloudflare"), _probe("quad9")]
    probes.append(_filtered("riot_game_server"))
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "cloudflare"
    assert rec.verdict == "playable"


# ── Tests: Default safe_to_play ───────────────────────────────────────


def test_all_healthy_safe_to_play() -> None:
    """Todos los probes OK → safe_to_play."""
    rec = evaluate_recommendation(_full_set(), **DEFAULTS)
    assert rec.verdict == "safe_to_play"
    assert rec.responsible_component == "unknown"


def test_no_probes_safe_to_play() -> None:
    """Sin probes → safe_to_play (no hay datos = no hay problema)."""
    rec = evaluate_recommendation([], **DEFAULTS)
    assert rec.verdict == "safe_to_play"


# ── Tests: Constraint 6 — Packet loss ─────────────────────────────────


def test_constraint6_downgrades_safe_to_not_recommended() -> None:
    """Constraint 6: safe_to_play + packet loss critico → not_recommended_ranked."""
    probes = _full_set() + [_probe("riot_game_server", packet_loss=4.0)]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    # Rule 4 no matchea porque riot_server tiene stats (no filtered)
    # pero constraint 6 detecta el packet loss alto
    assert rec.verdict != "safe_to_play"


def test_constraint6_on_local_provider() -> None:
    """Constraint 6: packet loss critico en local → no safe_to_play."""
    probes = _full_set() + [_probe("local", packet_loss=4.0)]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    # Rule 1 detecta local con loss critico → serious_issue
    assert rec.verdict == "serious_issue"
    assert rec.responsible_component == "local"


# ── Tests: Constraint 7 — Jitter ──────────────────────────────────────


def test_constraint7_downgrades_to_playable() -> None:
    """Constraint 7: jitter critico → maximo playable."""
    probes = _full_set() + [_probe("google", jitter=50.0)]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    # Rule 1-4 no matchean (GW OK, ISP OK, CF OK, Riot OK)
    # Default seria safe_to_play, pero constraint 7 lo baja a playable
    assert rec.verdict == "playable"


# ── INVARIANTE CRITICO: nunca safe_to_play con packet_loss critico ────


@pytest.mark.parametrize(
    "provider",
    ["local", "google", "cloudflare", "quad9", "riot_game_server", "riot_public"],
)
def test_invariant_never_safe_with_critical_packet_loss(provider: str) -> None:
    """INVARIANTE: ninguna combinacion produce safe_to_play si packet_loss >= critical.

    Este es el test que mas importa de toda la fase (Fase 5 DoD).
    Se parametriza por provider para cubrir todos los escenarios.
    """
    probes = _full_set()
    # Agregar probe con packet loss critico para el provider dado
    probes.append(_probe(provider, packet_loss=3.5))

    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert (
        rec.verdict != "safe_to_play"
    ), f"INVARIANTE ROTO: safe_to_play con packet_loss critico en {provider}"


def test_invariant_never_safe_with_critical_loss_any_provider() -> None:
    """INVARIANTE: probe con loss critico en cualquier provider impide safe_to_play.

    Escenario: todos los probes OK excepto uno con loss critico.
    Sin este test, el motor podria devolver safe_to_play ignorando el loss.
    """
    for provider in ("local", "google", "cloudflare", "quad9", "riot_game_server"):
        probes = _full_set()
        # Agregar un probe con loss critico
        probes.append(_probe(f"{provider}_lossy", packet_loss=3.5))
        # El helper _get_probe busca por provider, no por nombre exacto.
        # Necesitamos que el probe tenga el provider correcto.
        # Usamos un enfoque diferente: reemplazar el probe existente.
        probes = [p for p in _full_set() if p.provider != provider]
        probes.append(_probe(provider, packet_loss=3.5))

        rec = evaluate_recommendation(probes, **DEFAULTS)
        assert (
            rec.verdict != "safe_to_play"
        ), f"INVARIANTE ROTO: safe_to_play con packet_loss=3.5% en {provider}"


# ── Tests: Matriz de combinaciones (DoD Fase 5) ──────────────────────


def test_combo_local_bad_isp_ok() -> None:
    """Local malo, ISP OK → serious_issue, local."""
    probes = _full_set() + [_probe("local", packet_loss=5.0)]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "local"
    assert rec.verdict == "serious_issue"


def test_combo_isp_bad_local_ok() -> None:
    """ISP malo (3 DNS filtered), local OK → serious_issue, isp."""
    probes = [
        _filtered("google"),
        _filtered("cloudflare"),
        _filtered("quad9"),
        _probe("local"),
    ]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "isp"
    assert rec.verdict == "serious_issue"


def test_combo_only_cloudflare_bad() -> None:
    """Solo Cloudflare malo → playable, cloudflare."""
    probes = [
        _probe("google"),
        _filtered("cloudflare"),
        _probe("quad9"),
        _probe("local"),
    ]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "cloudflare"
    assert rec.verdict == "playable"


def test_combo_only_riot_public_bad() -> None:
    """Solo Riot public malo (sin game server) → playable, riot."""
    probes = [
        _probe("google"),
        _probe("cloudflare"),
        _probe("quad9"),
        _probe("local"),
        _filtered("riot_public"),
    ]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "riot"
    assert rec.verdict == "playable"


def test_combo_only_riot_game_server_bad() -> None:
    """Solo Riot game server malo → not_recommended_ranked, riot."""
    probes = _full_set() + [_filtered("riot_game_server")]
    # Reemplazar el riot_game_server sano con filtered
    probes = [p for p in probes if p.provider != "riot_game_server"]
    probes.append(_filtered("riot_game_server"))
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "riot"
    assert rec.verdict == "not_recommended_ranked"


def test_combo_high_packet_loss() -> None:
    """Packet loss alto en google → constraint 6 baja veredicto."""
    probes = _full_set() + [_probe("google", packet_loss=4.0)]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    # Google con loss alto: rule 1-4 no matchean (GW OK, ISP OK solo CF+Quad9
    # estan OK, riot OK). Constraint 6 detecta loss y baja de safe_to_play.
    assert rec.verdict != "safe_to_play"


def test_combo_high_jitter() -> None:
    """Jitter alto en cloudflare → constraint 7 baja a playable."""
    probes = _full_set() + [_probe("cloudflare", jitter=50.0)]
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.verdict == "playable"


def test_combo_everything_perfect() -> None:
    """Todos perfectos → safe_to_play."""
    rec = evaluate_recommendation(_full_set(), **DEFAULTS)
    assert rec.verdict == "safe_to_play"


def test_combo_riot_public_and_game_server_both_bad() -> None:
    """Ambos Riot degradados → not_recommended_ranked, riot."""
    probes = [
        p for p in _full_set() if p.provider not in ("riot_game_server", "riot_public")
    ]
    probes.extend([_filtered("riot_game_server"), _filtered("riot_public")])
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "riot"
    assert rec.verdict == "not_recommended_ranked"


# ── Tests: Explanation siempre no vacío ────────────────────────────────


def test_all_verdicts_have_explanation() -> None:
    """Toda Recommendation tiene explanation no vacío (EP §1.3)."""
    scenarios = [
        _full_set(),
        [],
        [_filtered("google"), _filtered("cloudflare"), _filtered("quad9")],
        _full_set() + [_probe("local", packet_loss=5.0)],
    ]
    for probes in scenarios:
        rec = evaluate_recommendation(probes, **DEFAULTS)
        assert (
            rec.explanation
        ), f"Explanation vacio para probes={[p.provider for p in probes]}"
        assert len(rec.explanation) > 0


# ── Tests: riot_public vs riot_game_server (criterio nuevo) ────────────


def test_riot_criteria_server_priority() -> None:
    """Game server tiene prioridad sobre riot_public."""
    # Ambos degradados → game server es el responsable
    probes = [
        p for p in _full_set() if p.provider not in ("riot_game_server", "riot_public")
    ]
    probes.extend([_filtered("riot_game_server"), _filtered("riot_public")])
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "riot"
    # La explicacion debe mencionar ambos
    assert any("publica" in e or "servidor" in e for e in rec.explanation)


def test_riot_criteria_no_server_uses_public() -> None:
    """Sin game server → riot_public es el proxy."""
    probes = [p for p in _full_set() if p.provider != "riot_game_server"]
    probes.append(_filtered("riot_public"))
    rec = evaluate_recommendation(probes, **DEFAULTS)
    assert rec.responsible_component == "riot"
    assert rec.verdict == "playable"


# ── Tests: Regla 5 — Riot >2x baseline ────────────────────────────────


def test_rule5_baseline_61ms_actual_126ms() -> None:
    """Test central del PRD: baseline 61ms, actual 126ms → rule 5 dispara.

    "Tu ruta es aproximadamente 2.1x mas lenta que tu promedio historico
    de 61ms." — este es el ejemplo literal del PRD original.
    """
    probes = _full_set() + [_probe("riot_game_server", avg_ms=126.0)]
    baselines = {
        "riot_game_server": HistoricalBaseline(
            provider="riot_game_server",
            period_days=30,
            avg_ms=61.0,
            stddev_ms=5.0,
            sample_count=30,
        ),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is not None
    assert r.responsible_component == "riot"
    assert r.verdict == "not_recommended_ranked"
    assert any("126" in e for e in r.explanation)
    assert any("61" in e for e in r.explanation)
    assert any("2.1" in e for e in r.explanation)


def test_rule5_uses_riot_server_when_available() -> None:
    """Rule 5 usa riot_game_server cuando existe (no riot_public)."""
    probes = _full_set() + [_probe("riot_game_server", avg_ms=100.0)]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 40.0, 3.0, 30),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is not None
    assert r.responsible_component == "riot"


def test_rule5_falls_back_to_riot_public() -> None:
    """Rule 5 usa riot_public cuando no hay game server."""
    probes = [p for p in _full_set() if p.provider != "riot_game_server"]
    # Agregar riot_public con latencia alta
    probes = [p for p in probes if p.provider != "riot_public"]
    probes.append(_probe("riot_public", avg_ms=100.0))
    baselines = {
        "riot_public": HistoricalBaseline("riot_public", 30, 20.0, 3.0, 30),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is not None
    assert "100" in r.explanation[0]
    assert "20" in r.explanation[0]


def test_rule5_no_baseline_no_match() -> None:
    """Sin baseline historico → rule 5 no matchea."""
    probes = _full_set() + [_probe("riot_game_server", avg_ms=200.0)]
    r = _rule5_riot_server_worse_than_baseline(probes, {})
    assert r is None


def test_rule5_within_threshold_no_match() -> None:
    """Latencia dentro de 2x baseline → no matchea."""
    probes = _full_set() + [_probe("riot_game_server", avg_ms=50.0)]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 30.0, 5.0, 30),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is None  # 50 <= 30*2 = 60


def test_rule5_at_exact_threshold_no_match() -> None:
    """Latencia exactamente en 2x baseline → NO matchea (debe ser >, no >=)."""
    probes = _full_set() + [_probe("riot_game_server", avg_ms=60.0)]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 30.0, 5.0, 30),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is None  # 60 = 30*2, no es > threshold


def test_rule5_just_above_threshold() -> None:
    """Latencia justo por encima de 2x baseline → dispara."""
    probes = _full_set() + [_probe("riot_game_server", avg_ms=61.0)]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 30.0, 5.0, 30),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is not None


def test_rule5_no_riot_probes_no_match() -> None:
    """Sin probes de Riot → rule 5 no matchea."""
    probes = [
        _probe("google"),
        _probe("cloudflare"),
        _probe("quad9"),
        _probe("local"),
    ]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 30.0, 5.0, 30),
    }
    r = _rule5_riot_server_worse_than_baseline(probes, baselines)
    assert r is None


def test_rule5_via_evaluate_recommendation() -> None:
    """Rule 5 integrada en evaluate_recommendation con baselines."""
    probes = _full_set() + [_probe("riot_game_server", avg_ms=126.0)]
    baselines = {
        "riot_game_server": HistoricalBaseline("riot_game_server", 30, 61.0, 5.0, 30),
    }
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    assert rec.responsible_component == "riot"
    assert rec.verdict == "not_recommended_ranked"
    assert any("126" in e for e in rec.explanation)
    assert any("61" in e for e in rec.explanation)


# ── Tests: Constraint 8 — Internet baseline anomalies (Fase 9 fix) ───────


def test_constraint8_google_quad9_anomaly_degrades_safe_to_playable() -> None:
    """Anomalías en Google+Quad9 vs baseline → safe_to_play degradado a playable.

    Este es el test del bug central de Fase 9: antes del fix, el motor
    devolvia safe_to_play aunque Google/Quad9 estuvieran anómalos vs
    baseline. Constraint 8 detecta la anomalía (avg + 2*stddev), emite
    explicación concreta, y degrada a playable.
    """
    probes = [
        _probe("local", avg_ms=5.0),  # local sano (baseline 5.0)
        _probe(
            "google", avg_ms=18.8
        ),  # baseline 13.3, stddev 0.5 -> threshold 14.3, 18.8 > 14.3 = anomalia
        _probe("cloudflare", avg_ms=12.0),  # sano
        _probe(
            "quad9", avg_ms=17.8
        ),  # baseline 12.6, stddev 0.5 -> threshold 13.6, 17.8 > 13.6 = anomalia
        _probe("riot_public", avg_ms=20.0),  # sano
    ]
    baselines = {
        "local": HistoricalBaseline("local", 30, 5.0, 1.0, 30),
        "google": HistoricalBaseline("google", 30, 13.3, 0.5, 30),
        "cloudflare": HistoricalBaseline("cloudflare", 30, 12.0, 1.0, 30),
        "quad9": HistoricalBaseline("quad9", 30, 12.6, 0.5, 30),
        "riot_public": HistoricalBaseline("riot_public", 30, 20.0, 2.0, 30),
    }
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)

    # Veredicto degradado
    assert rec.verdict == "playable", f"verdict={rec.verdict}, expected playable"
    # Responsable: isp (anomalias solo en Internet externo, sin local)
    assert rec.responsible_component == "isp"
    # Explicacion menciona las 2 anomalías concretas
    assert any(
        "google" in e and "18.8" in e for e in rec.explanation
    ), f"google anomaly no en explanation: {rec.explanation}"
    assert any(
        "quad9" in e and "17.8" in e for e in rec.explanation
    ), f"quad9 anomaly no en explanation: {rec.explanation}"
    # NO dice "Todos normales" / "Es seguro jugar"
    assert not any(
        "normales" in e.lower() for e in rec.explanation
    ), "explicacion contradictoria: 'normales' + anomalia"
    assert not any("seguro jugar" in e.lower() for e in rec.explanation)


def test_constraint8_with_local_anomaly_responsible_local() -> None:
    """Anomalia en local + Internet -> responsable = local (heuristic)."""
    probes = [
        _probe(
            "local", avg_ms=15.0
        ),  # baseline 5.0, stddev 1.0 -> threshold 7.0, 15.0 > 7.0 = anomalia
        _probe("google", avg_ms=18.8),  # anomalia
    ]
    baselines = {
        "local": HistoricalBaseline("local", 30, 5.0, 1.0, 30),
        "google": HistoricalBaseline("google", 30, 13.3, 0.5, 30),
    }
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    assert rec.verdict == "playable"
    assert rec.responsible_component == "local"  # heuristic: local anomalo domina


def test_constraint8_no_baseline_no_effect() -> None:
    """Sin baseline para un provider -> constraint 8 no se aplica a ese provider."""
    probes = [
        _probe("google", avg_ms=100.0),  # muy alto pero sin baseline
    ]
    baselines = {}  # sin baseline
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    # Sin baseline, constraint 8 no puede evaluar anomalía -> safe_to_play
    assert rec.verdict == "safe_to_play"


def test_constraint8_sample_count_zero_no_effect() -> None:
    """Baseline con sample_count=0 -> constraint 8 no se aplica."""
    probes = [_probe("google", avg_ms=100.0)]
    baselines = {"google": HistoricalBaseline("google", 30, 0.0, 0.0, 0)}
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    assert rec.verdict == "safe_to_play"


def test_constraint8_no_probe_no_effect() -> None:
    """Provider sin probe -> constraint 8 ignora ese provider."""
    probes = [_probe("local", avg_ms=5.0)]  # solo local
    baselines = {
        "local": HistoricalBaseline("local", 30, 5.0, 1.0, 30),
        "google": HistoricalBaseline(
            "google", 30, 13.3, 0.5, 30
        ),  # baseline existe pero NO hay probe
    }
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    # Google no tiene probe, no puede ser anomalía -> safe_to_play
    assert rec.verdict == "safe_to_play"


def test_constraint8_failsafe_no_ghost_text_when_rules_match() -> None:
    """Si reglas 1-5 matchean, constraint 8 no borra sus explicaciones."""
    # GW con packet loss critical -> rule 1 dispara (veredicto serious_issue)
    probes = [
        _probe("local", avg_ms=5.0, packet_loss=5.0),  # rule 1
        _probe("google", avg_ms=18.8),  # anomalia baseline
    ]
    baselines = {
        "local": HistoricalBaseline("local", 30, 5.0, 1.0, 30),
        "google": HistoricalBaseline("google", 30, 13.3, 0.5, 30),
    }
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    assert rec.verdict == "serious_issue"
    # La explicación de rule 1 DEBE seguir ahi
    assert any("Gateway local" in e for e in rec.explanation)
    # Y constraint 8 tambien añade su linea
    assert any("anomalía" in e or "anomalia" in e for e in rec.explanation)


def test_constraint8_no_safe_to_play_ghost_text() -> None:
    """Verifica que no quede 'normales' + anomalia cuando constraint 8 degrada."""
    probes = [
        _probe("local", avg_ms=5.0),
        _probe("google", avg_ms=18.8),  # anomalia
        _probe("quad9", avg_ms=17.8),  # anomalia
    ]
    baselines = {
        "local": HistoricalBaseline("local", 30, 5.0, 1.0, 30),
        "google": HistoricalBaseline("google", 30, 13.3, 0.5, 30),
        "quad9": HistoricalBaseline("quad9", 30, 12.6, 0.5, 30),
    }
    rec = evaluate_recommendation(probes, baselines=baselines, **DEFAULTS)
    assert rec.verdict == "playable"
    # Explicacion NO debe contener el texto ghost "Todos los diagnosticos son normales"
    full = " ".join(rec.explanation).lower()
    assert "todos los diagnosticos son normales" not in full
    assert "es seguro jugar ranked" not in full
