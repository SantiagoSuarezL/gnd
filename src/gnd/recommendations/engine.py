"""Motor de recomendacion — el corazon del proyecto.

TECHNICAL_SPEC.md §5: 7 reglas ordenadas por prioridad de diagnostico.
Cada regla es una funcion pura testeable de forma aislada
(ENGINEERING_PRINCIPLES.md §2.S).

Diseño del motor:
  - Fase 1 (reglas 1-5): determina responsible_component y veredicto inicial.
    Evalua de arriba hacia abajo; la primera que matchea define el componente.
  - Fase 2 (reglas 6-7): restricciones que solo pueden DEGRADAR el veredicto,
    nunca mejorarlo. Se aplican siempre despues de la fase 1.

Criterio riot_public vs riot_game_server (§5.4):
  - Si hay game server activo → riot_game_server tiene prioridad.
  - Si no hay game server → riot_public es el proxy.
  - Si ambos estan degradados → riot_game_server gana como responsible.
"""

from __future__ import annotations

from dataclasses import dataclass

from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.models.recommendation import Recommendation

# ── Resultado interno de una regla ─────────────────────────────────────


@dataclass(frozen=True)
class _RuleResult:
    """Resultado de una regla individual. No es un Recommendation final."""

    responsible_component: str
    verdict: str
    explanation: list[str]


# ── Helpers puros ──────────────────────────────────────────────────────


def _get_probe(probes: list[ProbeResult], provider: str) -> ProbeResult | None:
    """Busca el probe con el provider dado. Si hay multiples, devuelve el ultimo."""
    found: ProbeResult | None = None
    for p in probes:
        if p.provider == provider:
            found = p
    return found


def _is_healthy(p: ProbeResult | None) -> bool:
    """True si el probe existe, es SUCCESS, y tiene stats."""
    return (
        p is not None and p.outcome == ProbeOutcomeKind.SUCCESS and p.stats is not None
    )


def _is_degraded(p: ProbeResult | None) -> bool:
    """True si el probe no esta sano (None, no SUCCESS, o sin stats)."""
    return not _is_healthy(p)


def _maxPacket_loss(*probes: ProbeResult) -> float:
    """Maximo packet loss entre probes con stats."""
    losses = [p.stats.packet_loss_pct for p in probes if p.stats is not None]
    return max(losses) if losses else 0.0


def _max_jitter(*probes: ProbeResult) -> float:
    """Maximo jitter entre probes con stats."""
    jitters = [p.stats.jitter_ms for p in probes if p.stats is not None]
    return max(jitters) if jitters else 0.0


# ── Reglas 1-5: determinan componente y veredicto ──────────────────────


def _rule1_gateway_local(
    probes: list[ProbeResult],
    *,
    packet_loss_critical_pct: float,
    packet_loss_warning_pct: float,
    jitter_critical_ms: float,
    jitter_warning_ms: float,
) -> _RuleResult | None:
    """Regla 1: Gateway local inestable (TECHNICAL_SPEC §5.1).

    Si provider='local' tiene packet loss O jitter por encima del threshold,
    responsible_component = 'local'.
    """
    gw = _get_probe(probes, "local")
    if gw is None or gw.stats is None:
        return None

    loss = gw.stats.packet_loss_pct
    jitter = gw.stats.jitter_ms

    if loss >= packet_loss_critical_pct or jitter >= jitter_critical_ms:
        return _RuleResult(
            responsible_component="local",
            verdict="serious_issue",
            explanation=[
                (
                    f"Gateway local con packet loss {loss:.1f}% "
                    f"(critico >= {packet_loss_critical_pct}%)"
                    if loss >= packet_loss_critical_pct
                    else f"Gateway local con jitter {jitter:.1f}ms "
                    f"(critico >= {jitter_critical_ms}ms)"
                ),
                "Problema en la red local o router"
                " — no es un problema de ISP ni de Riot.",
            ],
        )

    if loss >= packet_loss_warning_pct or jitter >= jitter_warning_ms:
        return _RuleResult(
            responsible_component="local",
            verdict="not_recommended_ranked",
            explanation=[
                (
                    f"Gateway local con packet loss {loss:.1f}% "
                    f"(advertencia >= {packet_loss_warning_pct}%)"
                    if loss >= packet_loss_warning_pct
                    else f"Gateway local con jitter {jitter:.1f}ms "
                    f"(advertencia >= {jitter_warning_ms}ms)"
                ),
                "Inestabilidad en la red local detectada"
                " — jugar ranked no es recomendable.",
            ],
        )

    return None


def _rule2_isp_degraded(
    probes: list[ProbeResult],
) -> _RuleResult | None:
    """Regla 2: Todo malo — ISP (TECHNICAL_SPEC §5.2).

    Si Google, Cloudflare Y Quad9 estan todos degradados → ISP.
    Probes que no existen (None) se ignoran — no se cuentan como degradados.
    Solo matchea si los 3 existen Y estan degradados.
    """
    google = _get_probe(probes, "google")
    cloudflare = _get_probe(probes, "cloudflare")
    quad9 = _get_probe(probes, "quad9")

    # Si alguno no existe, no podemos determinar que "todos" estan mal
    if any(p is None for p in [google, cloudflare, quad9]):
        return None

    if all(_is_degraded(p) for p in [google, cloudflare, quad9]):
        return _RuleResult(
            responsible_component="isp",
            verdict="serious_issue",
            explanation=[
                "Los 3 DNS publicos (Google, Cloudflare, Quad9) estan degradados.",
                "El problema es del proveedor de internet (ISP)"
                ", no de Riot ni de tu red local.",
            ],
        )
    return None


def _rule3_cloudflare_degraded(
    probes: list[ProbeResult],
) -> _RuleResult | None:
    """Regla 3: Solo Cloudflare degradado (TECHNICAL_SPEC §5.3).

    Si Google y Quad9 OK, pero Cloudflare degradado → cloudflare.
    Si Cloudflare no existe (None), no matchea.
    """
    google = _get_probe(probes, "google")
    cloudflare = _get_probe(probes, "cloudflare")
    quad9 = _get_probe(probes, "quad9")

    if cloudflare is None:
        return None

    if _is_healthy(google) and _is_healthy(quad9) and _is_degraded(cloudflare):
        return _RuleResult(
            responsible_component="cloudflare",
            verdict="playable",
            explanation=[
                "Google y Quad9 responden correctamente,"
                " pero Cloudflare esta degradado.",
                "Cloudflare afecta a algunos servicios pero no impide jugar.",
            ],
        )
    return None


def _rule4_riot_degraded(
    probes: list[ProbeResult],
) -> _RuleResult | None:
    """Regla 4: Solo Riot degradado (TECHNICAL_SPEC §5.4).

    Si Internet general OK, pero Riot (publico o game server) esta degradado.

    Criterio riot_public vs riot_game_server:
      - Si hay game server activo → tiene prioridad.
      - Si no hay game server → se usa riot_public como proxy.
      - Si ambos estan degradados → riot_game_server gana.
    """
    google = _get_probe(probes, "google")
    cloudflare = _get_probe(probes, "cloudflare")
    quad9 = _get_probe(probes, "quad9")

    internet_ok = all(_is_healthy(p) for p in [google, cloudflare, quad9])
    if not internet_ok:
        return None

    riot_server = _get_probe(probes, "riot_game_server")
    riot_public = _get_probe(probes, "riot_public")

    # Distincion clave: "no existe" != "existe pero degradado"
    riot_server_present = riot_server is not None
    riot_server_degraded = riot_server_present and _is_degraded(riot_server)
    riot_public_degraded = _is_degraded(riot_public)

    if not riot_server_degraded and not riot_public_degraded:
        return None

    # Ambos degradados (server existe y falla + public falla) → game server gana
    if riot_server_degraded and riot_public_degraded:
        return _RuleResult(
            responsible_component="riot",
            verdict="not_recommended_ranked",
            explanation=[
                "La infraestructura publica de Riot y el servidor de partida "
                "estan ambos degradados.",
                "El problema es de Riot — no es tu red ni tu ISP.",
            ],
        )

    # Solo game server degradado (existe y no responde)
    if riot_server_degraded:
        explanation_lines = [
            "Internet funciona correctamente, pero el servidor de partida "
            "de Riot esta degradado.",
        ]
        if riot_server is not None and riot_server.stats is not None:
            explanation_lines.append(
                f"Latencia al servidor de partida: {riot_server.stats.avg_ms:.0f}ms."
            )
        explanation_lines.append("El problema es de Riot — no es tu red ni tu ISP.")
        return _RuleResult(
            responsible_component="riot",
            verdict="not_recommended_ranked",
            explanation=explanation_lines,
        )

    # Solo public degradado (game server no existe o esta OK)
    return _RuleResult(
        responsible_component="riot",
        verdict="playable",
        explanation=[
            "La infraestructura publica de Riot (login/patcher) esta degradada, "
            "y NO se detecto el servidor de partida real "
            "(usando riot_public como proxy — precision limitada).",
            "La conexion al servidor de partida real es desconocida; "
            "esto puede afectar el launcher pero la partida en curso es incierta.",
        ],
    )


def _rule5_riot_server_worse_than_baseline(
    probes: list[ProbeResult],
    baselines: dict[str, HistoricalBaseline],
) -> _RuleResult | None:
    """Regla 5: Riot game server >2x baseline (TECHNICAL_SPEC §5.5).

    El ejemplo central del PRD: "tu ruta es el doble de lenta que tu
    historico". Compara la latencia actual del provider de Riot relevante
    (game server si existe, si no publico) contra baseline.avg_ms.

    Dispara si actual > 2 * baseline.avg_ms.
    Solo aplica si hay baseline historico (sample_count > 0).
    """
    riot_server = _get_probe(probes, "riot_game_server")
    riot_public = _get_probe(probes, "riot_public")

    # Seleccionar el provider relevante (mismo criterio que rule 4)
    if riot_server is not None and riot_server.stats is not None:
        provider = "riot_game_server"
        current_ms = riot_server.stats.avg_ms
    elif riot_public is not None and riot_public.stats is not None:
        provider = "riot_public"
        current_ms = riot_public.stats.avg_ms
    else:
        return None

    baseline = baselines.get(provider)
    if baseline is None or baseline.sample_count == 0:
        return None

    # No disparar si la latencia es normal (dentro del baseline)
    if current_ms <= baseline.avg_ms:
        return None

    threshold = baseline.avg_ms * 2.0
    if current_ms <= threshold:
        return None

    ratio = current_ms / baseline.avg_ms if baseline.avg_ms > 0 else 0.0
    # Transparencia: indicar si es game server real o proxy riot_public
    proxy_note = ""
    if provider == "riot_public":
        proxy_note = (
            " (NOTA: usando riot_public como proxy — "
            "no se detecto game server real; precision limitada)"
        )
    return _RuleResult(
        responsible_component="riot",
        verdict="not_recommended_ranked",
        explanation=[
            f"Tu latencia actual a Riot ({current_ms:.0f}ms) es "
            f"aproximadamente {ratio:.1f}x mayor que tu promedio historico "
            f"de {baseline.avg_ms:.0f}ms.{proxy_note}",
            "La ruta se ha degradado significativamente respecto a tu"
            " comportamiento normal.",
        ],
    )


# ── Reglas 6-7: restricciones de veredicto ─────────────────────────────


def _constraint6_packet_loss(
    probes: list[ProbeResult],
    *,
    packet_loss_critical_pct: float,
) -> tuple[str, list[str]] | None:
    """Restriccion 6: packet loss alto → nunca safe_to_play (§5.6).

    Si CUALQUIER probe tiene packet_loss >= critical,
    el veredicto nunca puede ser safe_to_play.
    """
    if not probes:
        return None

    max_loss = _maxPacket_loss(*probes)
    if max_loss >= packet_loss_critical_pct:
        return (
            f"Packet loss critico detectado ({max_loss:.1f}% "
            f">= {packet_loss_critical_pct}%).",
            "No se recomienda jugar con perdida de paquetes critica.",
        )
    return None


def _constraint7_jitter(
    probes: list[ProbeResult],
    *,
    jitter_critical_ms: float,
) -> tuple[str, list[str]] | None:
    """Restriccion 7: jitter alto sostenido → maximo playable (§5.7).

    Si CUALQUIER probe tiene jitter >= critical,
    el veredicto nunca puede ser safe_to_play ni not_recommended_ranked.
    Maximo 'playable'.
    """
    if not probes:
        return None

    max_jitter = _max_jitter(*probes)
    if max_jitter >= jitter_critical_ms:
        return (
            f"Jitter alto sostenido detectado ({max_jitter:.1f}ms "
            f">= {jitter_critical_ms}ms).",
            "La conexion es inestable — jugar ranked no es seguro.",
        )
    return None


# ── Veredictos por defecto ─────────────────────────────────────────────

_VERDICT_SAFE = "safe_to_play"
_VERDICT_PLAYABLE = "playable"
_VERDICT_NOT_RECOMMENDED = "not_recommended_ranked"
_VERDICT_SERIOUS = "serious_issue"

_VERDICT_SEVERITY: dict[str, int] = {
    _VERDICT_SAFE: 0,
    _VERDICT_PLAYABLE: 1,
    _VERDICT_NOT_RECOMMENDED: 2,
    _VERDICT_SERIOUS: 3,
}


def _worse_verdict(a: str, b: str) -> str:
    """Devuelve el veredicto mas severo entre dos."""
    return a if _VERDICT_SEVERITY.get(a, 0) >= _VERDICT_SEVERITY.get(b, 0) else b


# ── Orquestador ────────────────────────────────────────────────────────


def evaluate_recommendation(
    probes: list[ProbeResult],
    *,
    active_game_server: bool | None = None,  # True=game server
    # False/None=usando riot_public como proxy
    baselines: dict[str, HistoricalBaseline] | None = None,
    packet_loss_warning_pct: float = 1.0,
    packet_loss_critical_pct: float = 3.0,
    jitter_warning_ms: float = 20.0,
    jitter_critical_ms: float = 40.0,
) -> Recommendation:
    """Evalua las 7 reglas y genera un Recommendation.

    Fase 1 (reglas 1-5): primera regla que matchea define
    responsible_component y veredicto inicial.
    Fase 2 (reglas 6-7): solo pueden degradar el veredicto.

    Si `active_game_server` es False/None (no se detecto game server real),
    la recomendacion añade una nota de transparencia indicando que
    se usa riot_public como proxy (ENGINEERING_PRINCIPLES.md §1.3).
    """
    bl = baselines or {}
    # ── Fase 1: reglas 1-5 en orden de prioridad ──
    phase1_rules = [
        lambda: _rule1_gateway_local(
            probes,
            packet_loss_critical_pct=packet_loss_critical_pct,
            packet_loss_warning_pct=packet_loss_warning_pct,
            jitter_critical_ms=jitter_critical_ms,
            jitter_warning_ms=jitter_warning_ms,
        ),
        lambda: _rule2_isp_degraded(probes),
        lambda: _rule3_cloudflare_degraded(probes),
        lambda: _rule4_riot_degraded(probes),
        lambda: _rule5_riot_server_worse_than_baseline(probes, bl),
    ]

    result: _RuleResult | None = None
    for rule_fn in phase1_rules:
        result = rule_fn()
        if result is not None:
            break

    # ── Valores iniciales (default: todo bien) ──
    if result is None:
        verdict = _VERDICT_SAFE
        explanation: list[str] = [
            "Todos los diagnosticos son normales.",
            "Es seguro jugar ranked.",
        ]
        responsible = "unknown"
    else:
        verdict = result.verdict
        explanation = list(result.explanation)
        responsible = result.responsible_component

    # ── Fase 2: restricciones 6-7 (siempre se aplican) ──
    c6 = _constraint6_packet_loss(
        probes, packet_loss_critical_pct=packet_loss_critical_pct
    )
    if c6 is not None:
        explanation.append(c6[0])
        verdict = _worse_verdict(verdict, _VERDICT_NOT_RECOMMENDED)

    c7 = _constraint7_jitter(probes, jitter_critical_ms=jitter_critical_ms)
    if c7 is not None:
        explanation.append(c7[0])
        verdict = _worse_verdict(verdict, _VERDICT_PLAYABLE)

    # ── Transparencia: si no hay game server real, avisar que usamos proxy
    if not active_game_server:
        explanation.append(
            "NOTA: No se detecto servidor de partida real "
            "(UDP no expone raddr en Windows). "
            "El diagnostico Riot usa la infraestructura publica "
            "(riot_public: auth.riotgames.com, lol.secure.dyn.riotcdn.net) "
            "como proxy de salud de conexion — "
            "es una aproximacion, no la IP exacta del game server."
        )

    # ── Headline segun veredicto ──
    headlines = {
        _VERDICT_SAFE: " conexion estable",
        _VERDICT_PLAYABLE: " conexion jugable con precaucion",
        _VERDICT_NOT_RECOMMENDED: " no se recomienda jugar ranked",
        _VERDICT_SERIOUS: " problema serio de conexion detectado",
    }

    return Recommendation(
        verdict=verdict,
        headline=headlines[verdict],
        explanation=explanation,
        responsible_component=responsible,
        score=0,  # placeholder — el score real viene del analysis/score.py
    )
