"""Configuración del reporte periódico (Fase 12b.3).

Define el período (semanal / mensual) y los parámetros de composición
del reporte. Es un Value Object inmutable (Protocolo 5) consumido por
``reports/scheduler.py`` y ``reports/composer.py``.

Se separa de ``GndSettings.reports`` (config dinámica Pydantic, puede
cambiar en runtime futuro) porque el scheduler lo recibe como VO y
opera contra un snapshot frozen — el scheduler no se reconfigura en
vuelo. Si el usuario togglea ``enabled`` en config.toml, debe
reiniciar la UI (mismo molde que las demás features opt-in).

``ReportPeriod`` es Enum corto (no str) para que el VO quede
comparable y hashable, y para que el mapper ``period_to_timedelta``
viva en ``reports/`` (no en ``models/`` — protocolo 1: models/ sin
imports de datetime-only sería OK, pero mantener todo el
model-side puro y el mapping del período a ``timedelta`` lo hace
``reports/`` para no acoplar el VO a la librería de tiempo).
"""

from dataclasses import dataclass
from enum import Enum, auto

__all__ = ["ReportConfig", "ReportPeriod"]


class ReportPeriod(Enum):
    """Cadencia de generación del reporte automático.

    WEEKLY: cada 7 días desde el arranque del scheduler.
    MONTHLY: cada 30 días (mes calendario aproximado — YAGNI manejar
        meses de 28/31 días y bisiestos para v1; 30 días fijo es un
        proxy aceptable para un reporte de diagnóstico hogareño).
    """

    WEEKLY = auto()
    MONTHLY = auto()


@dataclass(frozen=True)
class ReportConfig:
    """Snapshot inmutable de la configuración del scheduler de reportes.

    Invariantes:
    - ``top_runs`` >= 0 (0 = listar runs sin renderizar ninguno completo;
      sólo agregado + lista compacta).
    - ``period`` es miembro de ``ReportPeriod``.
    """

    period: ReportPeriod
    top_runs: int = 3
    reports_dir: str = "%APPDATA%/GND/reports"
    notify_on_generated: bool = True
    notify_only_on_clean_period: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.period, ReportPeriod):
            raise ValueError(
                f"period debe ser ReportPeriod, no {type(self.period).__name__}"
            )
        if self.top_runs < 0:
            raise ValueError(f"top_runs debe ser >= 0, fue {self.top_runs}")
        if not self.reports_dir:
            raise ValueError("reports_dir no puede ser vacío")
