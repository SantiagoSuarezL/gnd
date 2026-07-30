"""Tests del formatter de notificaciones (Fase 12b.2).

El formatter ``build_run_notification`` es funcion pura:
in (DiagnosticRun) -> out (DesktopNotification | None). Tests cubren:
- Verdicts validos mapean a etiquetas humanas legibles.
- Formato del title: "GND — {etiqueta}".
- Formato del message: "{headline} (Score: {score}/100)".
- Filtrado notify_only_on_issues: suprime solo safe_to_play; los
  demas verdicts notifican igual.
- Sin configuracion de filtrado: notifica siempre.
- Invariante del modelo: headline siempre no vacio, score 0-100
  siempre presente en el message.
- DesktopNotification valida title/message no vacios — si el caller
  intentara crear una notif vacia el modelo lo rechaza.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.notification import DesktopNotification
from gnd.models.recommendation import Recommendation
from gnd.notifications.run_formatter import build_run_notification

# ── Factory helpers ────────────────────────────────────────────────────


def _rec(
    *,
    verdict: str = "safe_to_play",
    headline: str = "Todo OK",
    score: int = 92,
) -> Recommendation:
    return Recommendation(
        verdict=verdict,
        headline=headline,
        explanation=["Sin anomalías", "Score normal"],
        responsible_component="unknown",
        score=score,
    )


def _run(
    *,
    recommendation: Recommendation | None = None,
    started: datetime | None = None,
    finished: datetime | None = None,
) -> DiagnosticRun:
    now = datetime.now()
    return DiagnosticRun(
        run_id="run-test",
        started_at=started or now,
        finished_at=finished or (now + timedelta(seconds=5)),
        probes=[],
        traceroutes=[],
        active_game_server=None,
        recommendation=recommendation or _rec(),
    )


# ── Mapeo verdict -> etiqueta ─────────────────────────────────────────


class TestVerdictLabels:
    def test_safe_to_play_mapea_a_lista_para_jugar(self) -> None:
        n = build_run_notification(_run(recommendation=_rec(verdict="safe_to_play")))
        assert n is not None
        assert "Listo para jugar" in n.title

    def test_playable_mapea_a_jugable(self) -> None:
        n = build_run_notification(_run(recommendation=_rec(verdict="playable")))
        assert n is not None
        assert "Jugable" in n.title

    def test_not_recommended_ranked_mapea_a_no_recomendado(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(verdict="not_recommended_ranked"))
        )
        assert n is not None
        assert "No recomendado para ranked" in n.title

    def test_serious_issue_mapea_a_problema_serio(self) -> None:
        n = build_run_notification(_run(recommendation=_rec(verdict="serious_issue")))
        assert n is not None
        assert "Problema serio" in n.title


# ── Formato del title y message ───────────────────────────────────────


class TestFormatoNotificacion:
    def test_title_comienza_con_prefijo_GND(self) -> None:
        n = build_run_notification(_run())
        assert n is not None
        assert n.title.startswith("GND — ")

    def test_message_contiene_headline(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(headline="Pérdidas de 5% en Cloudflare"))
        )
        assert n is not None
        assert "Pérdidas de 5% en Cloudflare" in n.message

    def test_message_contiene_score_formateado(self) -> None:
        n = build_run_notification(_run(recommendation=_rec(score=73)))
        assert n is not None
        assert "Score: 73/100" in n.message

    def test_message_combina_headline_y_score(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(headline="Latencia alta al gateway", score=42))
        )
        assert n is not None
        assert n.message == "Latencia alta al gateway (Score: 42/100)"

    def test_title_no_muestra_clave_interna_del_motor(self) -> None:
        """La toast no debe exponer 'safe_to_play' string crudo — label humano."""
        n = build_run_notification(_run(recommendation=_rec(verdict="safe_to_play")))
        assert n is not None
        assert "safe_to_play" not in n.title

    def test_score_cero_aparece_en_message(self) -> None:
        n = build_run_notification(_run(recommendation=_rec(score=0)))
        assert n is not None
        assert "Score: 0/100" in n.message

    def test_score_maximo_100_aparece_en_message(self) -> None:
        n = build_run_notification(_run(recommendation=_rec(score=100)))
        assert n is not None
        assert "Score: 100/100" in n.message


# ── Filtrado notify_only_on_issues ────────────────────────────────────


class TestFiltradoNotifyOnlyOnIssues:
    def test_safe_to_play_con_only_issues_true_devuelve_none(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(verdict="safe_to_play")),
            notify_only_on_issues=True,
        )
        assert n is None

    def test_playable_con_only_issues_true_devuelve_notif(self) -> None:
        """playable no es EXCELENTE — es un issue leve, notifica."""
        n = build_run_notification(
            _run(recommendation=_rec(verdict="playable")),
            notify_only_on_issues=True,
        )
        assert n is not None

    def test_not_recommended_ranked_con_only_issues_true_devuelve_notif(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(verdict="not_recommended_ranked")),
            notify_only_on_issues=True,
        )
        assert n is not None

    def test_serious_issue_con_only_issues_true_devuelve_notif(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(verdict="serious_issue")),
            notify_only_on_issues=True,
        )
        assert n is not None

    def test_safe_to_play_con_only_issues_False_devuelve_notif(self) -> None:
        """Default: notifica siempre, sin filtrar EXCELENTE."""
        n = build_run_notification(
            _run(recommendation=_rec(verdict="safe_to_play")),
            notify_only_on_issues=False,
        )
        assert n is not None

    def test_serious_issue_con_only_issues_False_devuelve_notif(self) -> None:
        n = build_run_notification(
            _run(recommendation=_rec(verdict="serious_issue")),
            notify_only_on_issues=False,
        )
        assert n is not None

    def test_only_issues_default_es_False_en_signature(self) -> None:
        """Si el caller no pasa flag, default False (notifica siempre)."""
        # Sin pasar kwarg explícito — usa default.
        n = build_run_notification(_run(recommendation=_rec(verdict="safe_to_play")))
        assert n is not None


# ── Value object DesktopNotification ──────────────────────────────────


class TestDesktopNotificationValueObject:
    def test_title_vacio_raise_valueerror(self) -> None:
        with pytest.raises(ValueError, match="title"):
            DesktopNotification(title="", message="algo")

    def test_message_vacio_raise_valueerror(self) -> None:
        with pytest.raises(ValueError, match="message"):
            DesktopNotification(title="algo", message="")

    def test_ambos_vacios_raise_valueerror(self) -> None:
        with pytest.raises(ValueError):
            DesktopNotification(title="", message="")

    def test_dataclass_frozen_es_inmutable(self) -> None:
        from dataclasses import FrozenInstanceError

        n = DesktopNotification(title="t", message="m")
        with pytest.raises(FrozenInstanceError):
            n.title = "otro"  # type: ignore[misc]

    def test_dos_con_mismo_contenido_son_iguales(self) -> None:
        a = DesktopNotification(title="t", message="m")
        b = DesktopNotification(title="t", message="m")
        assert a == b
