"""Veredicto del motor de recomendación.

TECHNICAL_SPEC.md §1 y §5. ENGINEERING_PRINCIPLES.md §1.3: ningún veredicto
se emite sin explanation no vacío — un veredicto sin razonamiento explícito
es un bug de producto (principio "never guess, always explain why").
"""

from dataclasses import dataclass

# Componente responsable del problema — Taxonomía cerrada del spec (§1).
RESPONSIBLE_COMPONENTS = frozenset(
    {
        "local",
        "isp",
        "international_transit",
        "riot",
        "cloudflare",
        "google",
        "unknown",
    }
)


@dataclass(frozen=True)
class Recommendation:
    verdict: str  # safe_to_play | playable | not_recommended_ranked | serious_issue
    headline: str
    explanation: list[str]
    responsible_component: str
    score: int  # 0-100

    def __post_init__(self) -> None:
        if self.verdict not in (
            "safe_to_play",
            "playable",
            "not_recommended_ranked",
            "serious_issue",
        ):
            raise ValueError(f"verdict inválido: {self.verdict!r}")
        if not self.headline:
            raise ValueError("headline no puede ser vacío")
        if not self.explanation:
            # EP §1.3: veredicto sin explanation es bug.
            raise ValueError("explanation no puede ser vacío (EP §1.3)")
        if self.responsible_component not in RESPONSIBLE_COMPONENTS:
            raise ValueError(
                f"responsible_component inválido: {self.responsible_component!r}"
            )
        if not (0 <= self.score <= 100):
            raise ValueError(f"score debe estar en [0, 100], fue {self.score}")
