"""Paquete reports — composición y scheduling de reportes periódicos.

Fase 12b.3 (PRD §7 nice-to-have + IMPLEMENTATION_PLAN.md 12b.3). Reusa
el renderer de Markdown de Export (Fase 12b.1) para los top-K runs
destacados del período; lo nuevo es el agregado del período (header +
estadísticas + lista compacta + top-K).

Topología:
- ``composer.compose_period_report`` (función pura) — arma el Markdown.
- ``scheduler.ReportsScheduler`` (clase) — agenda generación periódica
  con ``threading.Timer`` (hilo daemon). Inyecta ``Clock`` + ``Sleeper``
  + ``ReportWriter`` (Protocolo 17) para tests sin I/O de OS.

Patrones respetados:
- Protocolo 1 (separación models/domain): ``reports/`` importa de
  ``models/`` y de ``export/`` (presentation). El scheduler también
  importa ``RunHistoryReader`` (puerto) y ``DesktopNotifier`` (puerto)
  para DI, no implementaciones concretas — el wiring concretas en
  ``composition_root``.
- Regla 11.3 (eventos estructurados): namespace ``report`` con
  ``report.start`` / ``report.finish`` / ``report.error`` /
  ``report.skip`` / ``report.scheduler_start`` / ``report.scheduler_stop``.
- Regla 12b.2.2 (omite > payload degenerada): composer devuelve ``None``
  si el período no tuvo runs; el scheduler hace no-op con log
  ``report.skip`` y no genera archivo `.md` vacío.
"""

from gnd.reports.composer import compose_period_report
from gnd.reports.scheduler import (
    Clock,
    ReportsScheduler,
    ReportWriter,
    Sleeper,
)

__all__ = [
    "Clock",
    "ReportWriter",
    "ReportsScheduler",
    "Sleeper",
    "compose_period_report",
]
