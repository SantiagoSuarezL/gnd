"""Formatter de ``DiagnosticRun`` a ``DesktopNotification`` (Fase 12b.2).

Funcion pura libre (``build_run_notification``) que toma un
``DiagnosticRun`` y devuelve un ``DesktopNotification`` con
``title``/``message`` formateados para toast nativa del OS, o ``None``
si la configuracion de filtrado (``notify_only_on_issues``) dice que
no corresponde notificar.

Misma filosofia que ``export/markdown_renderer.py`` (Fase 12b.1):
- Funcion pura, sin IO, sin deps externas.
- Solo importa de ``models/`` (Protocolo 1).
- In (``DiagnosticRun``) -> out (``DesktopNotification | None``).
- El caller (``MainWindow``) decide que hacer con el retorno:
  ``None`` => no-op; ``DesktopNotification`` => ``notifier.notify(...)``.

Decision: NO devolver una toast vacia para suprimir; devolver ``None``.
Una toast vacia es peor que no-toast (el OS la muestra igual con header
sin contenido). ``None`` es el signal explicito de "no notificar".
Aplica por simetria con la Regla 11.2 (omitir > nulo en JSON): el
formatter omite la notif > emite toast vacia.

Filtrado:
- ``notify_only_on_issues=False`` (default en config) — notifica SIEMPRE
  (todo verdict), porque el usuario pidio ser notificado, sin importar
  el resultado.
- ``notify_only_on_issues=True`` — suprime para ``verdict="safe_to_play"``
  (nomenclatura del motor para EXCELENTE). Los demas verdicts
  (``playable``, ``not_recommended_ranked``, ``serious_issue``) si
  notifican — son el "issue" que el usuario quiere ver.

Mapeo verdict -> etiqueta humana para titulo:
- ``safe_to_play``         -> "Listo para jugar"
- ``playable``             -> "Jugable"
- ``not_recommended_ranked`` -> "No recomendado para ranked"
- ``serious_issue``        -> "Problema serio"
"""

from __future__ import annotations

from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.notification import DesktopNotification

__all__ = ["build_run_notification"]


# Etiquetas humanas por verdict (mismo set de strings del Recommendation
# __post_init__). Mismo patron que ``_fmt_outcome`` / ``_fmt_dns_outcome``
# en markdown_renderer.py — un mapa explicito, legible y testeable.
_VERDICT_LABELS: dict[str, str] = {
    "safe_to_play": "Listo para jugar",
    "playable": "Jugable",
    "not_recommended_ranked": "No recomendado para ranked",
    "serious_issue": "Problema serio",
}


def _verdict_label(verdict: str) -> str:
    """Traduce el verdict interno (key) a etiqueta humana legible.

    Si el verdict no esta en el mapa (caso defensivo — todos los
    verdicts validos estan en el dict), cae al string crudo sin crashear
    (el verdict SIEMPRE viene validado por Recommendation.__post_init__).
    """
    return _VERDICT_LABELS.get(verdict, verdict)


def build_run_notification(
    run: DiagnosticRun,
    *,
    notify_only_on_issues: bool = False,
) -> DesktopNotification | None:
    """Construye la notificacion de escritorio para ``run``.

    Args:
        run: la corrida recien terminada.
        notify_only_on_issues: si True, devuelve None para runs con
            verdict ``safe_to_play`` (no es "issue"). Si False,
            devuelve siempre una ``DesktopNotification``.

    Returns:
        ``DesktopNotification`` con titulo + mensaje formateados, o
        ``None`` si la combinacion verdict/filtrado no amerita notif.

    Formato del title:
        ``"GND — {etiqueta_verdict}"`` (ej: ``"GND — Listo para jugar"``)
        Etiqueta humana para que el usuario no vea claves internas del
        motor ("safe_to_play") en la toast.

    Formato del message:
        ``"{headline} (Score: {score}/100)"`` — el headline siempre
        es no vacio (invariante de Recommendation), y el score esta en
        [0, 100] (invariante del modelo).
    """
    rec = run.recommendation
    verdict = rec.verdict

    # Filtrado: notify_only_on_issues=True suprime para verdict EXCELENTE
    # (safe_to_play en nomenclatura del motor). El resto quiebran el silencio.
    if notify_only_on_issues and verdict == "safe_to_play":
        return None

    title = f"GND — {_verdict_label(verdict)}"
    message = f"{rec.headline} (Score: {rec.score}/100)"
    return DesktopNotification(title=title, message=message)
