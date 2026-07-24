"""Tests de Recommendation — invariantes y explicación obligatoria."""

import pytest

from gnd.models.recommendation import Recommendation


def test_recommendation_valida() -> None:
    r = Recommendation(
        verdict="safe_to_play",
        headline="Todo bien",
        explanation=["Latencia normal", "Sin pérdida"],
        responsible_component="unknown",
        score=90,
    )
    assert r.verdict == "safe_to_play"


def test_verdict_invalido_falla() -> None:
    with pytest.raises(ValueError, match="verdict inválido"):
        Recommendation(
            verdict="todo_bien",
            headline="X",
            explanation=["a"],
            responsible_component="unknown",
            score=50,
        )


def test_explanation_vacio_falla() -> None:
    with pytest.raises(ValueError, match="explanation no puede ser vacío"):
        Recommendation(
            verdict="safe_to_play",
            headline="X",
            explanation=[],
            responsible_component="unknown",
            score=50,
        )


def test_responsible_component_invalido_falla() -> None:
    with pytest.raises(ValueError, match="responsible_component inválido"):
        Recommendation(
            verdict="safe_to_play",
            headline="X",
            explanation=["a"],
            responsible_component="alien",
            score=50,
        )


def test_score_fuera_de_rango_falla() -> None:
    with pytest.raises(ValueError, match="score debe estar en \\[0, 100\\]"):
        Recommendation(
            verdict="safe_to_play",
            headline="X",
            explanation=["a"],
            responsible_component="unknown",
            score=-1,
        )
    with pytest.raises(ValueError, match="score debe estar en \\[0, 100\\]"):
        Recommendation(
            verdict="safe_to_play",
            headline="X",
            explanation=["a"],
            responsible_component="unknown",
            score=101,
        )


def test_headline_vacio_falla() -> None:
    with pytest.raises(ValueError, match="headline no puede ser vacío"):
        Recommendation(
            verdict="safe_to_play",
            headline="",
            explanation=["a"],
            responsible_component="unknown",
            score=50,
        )
