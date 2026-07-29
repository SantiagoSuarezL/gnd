"""Modelos inmutables de la capa de visualización (Fase 10).

ARCHITECTURE.md §3: ``visualization/`` "Generación de gráficos a partir de
datos ya calculados."  Estos modelos son DTOs que las queries SQL producen
y los charts renderizan — no contienen lógica de negocio ni dependen de
matplotlib (para que los tests de queries no requieran backend gráfico).

Regla (EP §1.5): todo modelo es ``@dataclass(frozen=True)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SeriesPoint:
    """Un punto de una serie temporal: ``y`` en el instante ``x``.

    ``group`` permite múltiples series en un mismo gráfico (ej. provider).
    Si el gráfico es single-series, todas las points comparten el mismo
    ``group`` (string vacío por defecto).

    ``metadata`` es un dict opcional para anotar info extra por punto
    (ej. ``{"n_samples": 5}`` en el chart de mejores horas para que el
    renderer muestre la confianza). Default: dict vacío.
    """

    x: datetime
    y: float
    group: str = ""
    metadata: dict[str, float | int | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.x, datetime):
            raise TypeError("x debe ser datetime")
        if self.y < 0.0:
            raise ValueError(f"y debe ser >= 0, fue {self.y}")


@dataclass(frozen=True)
class ChartDataSet:
    """Datos listos para renderizar en un gráfico.

    ``title``: título del gráfico (display).
    ``y_label``: etiqueta del eje Y (display).
    ``points``: lista ordenada cronológicamente de ``SeriesPoint``.
        Vacío = sin datos (la UI muestra empty state, no dibuja el chart).
    ``x_label``: etiqueta del eje X (display). Default "Fecha".

    Invariante: los tests de queries verifican el orden cronológico aquí
    (no en el renderer) — si algo queda desordenado, es bug de la query,
    no del chart.
    """

    title: str
    y_label: str
    points: tuple[SeriesPoint, ...] = field(default_factory=tuple)
    x_label: str = "Fecha"

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("title no puede ser vacío")
        if not self.y_label:
            raise ValueError("y_label no puede ser vacío")
        # Verificación barata de orden cronológico (no full sort check).
        for a, b in zip(self.points, self.points[1:], strict=False):
            if b.x < a.x:
                raise ValueError(
                    "points debe estar ordenada cronológicamente "
                    f"({b.x} antes de {a.x})"
                )

    @property
    def is_empty(self) -> bool:
        """True si no hay puntos (la UI debe mostrar empty state)."""
        return len(self.points) == 0

    @property
    def groups(self) -> tuple[str, ...]:
        """Devuelve los grupos únicos preservando el orden de aparición."""
        seen: list[str] = []
        for p in self.points:
            if p.group not in seen:
                seen.append(p.group)
        return tuple(seen)

    @classmethod
    def empty(cls, title: str, y_label: str, x_label: str = "Fecha") -> ChartDataSet:
        """Construye un dataset vacío (para errores/empty state explícitos)."""
        return cls(title=title, y_label=y_label, points=(), x_label=x_label)
