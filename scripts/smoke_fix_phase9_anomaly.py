"""Smoke test del fix Fase 9 — reproduce bug reportado.

Escenario:
  Google actual 18.8ms vs baseline 13.3ms (anomalia)
  Quad9  actual 17.8ms vs baseline 12.6ms (anomalia)
  Todo lo demas OK.

Antes del fix: verdict safe_to_play, explanation "Todos los diagnosticos
son normales" — ignorando las 2 anomalias reales de Historical Comparison.
Despues del fix: constraint 8 dispara, degrada a 'playable' y menciona
explicitamente ambas anomalias.
"""

from datetime import datetime

from gnd.models.historical_baseline import HistoricalBaseline
from gnd.models.latency_stats import LatencyStats
from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.recommendations.engine import evaluate_recommendation


def probe(
    provider: str, avg: float, base_loss: float = 0.0, base_jitter: float = 2.0
) -> ProbeResult:
    return ProbeResult(
        target_name=f"t-{provider}",
        target_ip="1.2.3.4",
        provider=provider,
        outcome=ProbeOutcomeKind.SUCCESS,
        stats=LatencyStats(
            avg_ms=avg,
            min_ms=max(0, avg - 5),
            max_ms=avg + 5,
            jitter_ms=base_jitter,
            packet_loss_pct=base_loss,
            samples=10,
        ),
        timestamp=datetime.now(),
    )


def main() -> None:
    probes = [
        probe("local", 5.0),
        probe("google", 18.8),  # baseline 13.3 -> anomalia
        probe("cloudflare", 12.0),  # OK (coincide con baseline)
        probe("quad9", 17.8),  # baseline 12.6 -> anomalia
        probe("riot_public", 20.0),  # OK (coincide con baseline)
    ]
    baselines = {
        "local": HistoricalBaseline("local", 30, 5.0, 1.0, 30),
        "google": HistoricalBaseline("google", 30, 13.3, 0.5, 30),
        "cloudflare": HistoricalBaseline("cloudflare", 30, 12.0, 1.0, 30),
        "quad9": HistoricalBaseline("quad9", 30, 12.6, 0.5, 30),
        "riot_public": HistoricalBaseline("riot_public", 30, 20.0, 2.0, 30),
    }

    rec = evaluate_recommendation(probes, active_game_server=False, baselines=baselines)
    print("verdict:", rec.verdict)
    print("responsible:", rec.responsible_component)
    print("score (placeholder):", rec.score)
    print("--- explanation ---")
    for line in rec.explanation:
        print(" -", line)

    # Aserciones del fix
    assert (
        rec.verdict != "safe_to_play"
    ), "BUG no corregido: verdict sigue siendo safe_to_play con anomalias reales"
    assert any(
        "google" in line and "18.8" in line for line in rec.explanation
    ), "BUG: anomalia de Google (18.8ms) no aparece en explanation"
    assert any(
        "quad9" in line and "17.8" in line for line in rec.explanation
    ), "BUG: anomalia de Quad9 (17.8ms) no aparece en explanation"
    print("\n>>> FIX VERIFICADO: anomalias de Google/Quad9 ya no se ignoran.")


if __name__ == "__main__":
    main()
