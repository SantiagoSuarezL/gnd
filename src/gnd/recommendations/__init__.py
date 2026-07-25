"""Modulo de recomendaciones — motor de reglas del dominio.

TECHNICAL_SPEC.md §5. Cada regla es una funcion pura testeable de forma
aislada (ENGINEERING_PRINCIPLES.md §2.S).
"""

from gnd.recommendations.engine import evaluate_recommendation

__all__ = ["evaluate_recommendation"]
