"""Scheduler de reportes periódicos con ``threading.Timer`` (Fase 12b.3).

IMPLEMENTATION_PLAN.md Fase 12b.3: reusa el renderer de Export (12b.1)
para el contenido; scheduler con ``threading.Timer`` integrado al
controller existente (YAGNI APScheduler/Celery — lib nueva injustificada
para un reporte de diagnóstico hogareño).

Arquitectura (mismo molde que RouteMonitor Fase 8, Protocolo 17):
- ``Clock`` y ``Sleeper`` inyectables — tests no esperan tiempo real.
- ``ReportWriter`` inyectable — el scheduler no abre archivos en tests;
  el writer real abre el path y escribe el str retornado por el
  ``compose_period_report``.
- Hilo daemon — ``stop()`` cancela el Timer pendiente sin blockar el
  shutdown de la UI (sk. ``daemon=True``, no absorbimos el join).

El scheduler nunca lanza corridas de diagnóstico — solo lee el
histórico persistido (``RunHistoryReader``) y lo compone con
``compose_period_report``. Esto desacopla totalmente el feature
"reportes automáticos" del feature "correr diagnóstico": si el usuario
tuvo 0 runs en el período, el scheduler loguea ``report.skip`` y no
genera archivo. No hay acoplamiento con ``RunFullDiagnostics`` —
ningún import de application layer acá (presentation pura sobre
``RunHistoryReader`` + modelos).

Eventos estructurados (Regla 11.3):
- ``report.start`` — al iniciar un tick del scheduler.
- ``report.finish`` — al escribir el archivo + notificar exitosamente.
- ``report.error`` — excepción no esperada en el tick (log + continúa).
- ``report.skip`` — sin runs en el período (no genera archivo, no notif).
- ``report.scheduler_start`` / ``report.scheduler_stop`` — lifecycle.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from gnd.domain.ports.notifier import DesktopNotifier
from gnd.domain.ports.run_history_reader import RunHistoryReader
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.notification import DesktopNotification
from gnd.models.report_config import ReportConfig, ReportPeriod
from gnd.reports.composer import compose_period_report, period_to_label

logger = logging.getLogger(__name__)

__all__ = ["ReportsScheduler", "ReportWriter", "Clock", "Sleeper"]


# ── DI helpers: extraen I/O de OS del scheduler (Protocolo 17) ────────


class Clock(Protocol):
    """Callable que devuelve el timestamp actual. Inyectable en tests."""

    def __call__(self) -> datetime: ...


class Sleeper(Protocol):
    """Callable que duerme ``seconds`` segundos. Inyectable en tests."""

    def __call__(self, seconds: float) -> None: ...


class _DefaultClock:
    def __call__(self) -> datetime:
        return datetime.now()


class _DefaultSleeper:
    """Sleeper por defecto: time.sleep con guard de >0 (YAGNI latencia 0)."""

    def __call__(self, seconds: float) -> None:
        if seconds > 0.0:
            import time

            time.sleep(seconds)


_default_clock: Clock = _DefaultClock()  # type: ignore[assignment]
_default_sleeper: Sleeper = _DefaultSleeper()  # type: ignore[assignment]


# ── ReportWriter — inyectable para no abrir archivos en tests ──────────


@runtime_checkable
class ReportWriter(Protocol):
    """Escribe el str Markdown del reporte a un path.

    Inyectable para tests: el fake acumula los (path, content) para
    asserts sin tocar disco.
    """

    def write(self, path: str, content: str) -> None: ...


class _DefaultReportWriter:
    """Writer real: crea el directorio padre si no existe y escribe el str."""

    def write(self, path: str, content: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


_default_writer: ReportWriter = _DefaultReportWriter()  # type: ignore[assignment]


# ── Helpers puros ──────────────────────────────────────────────────────


def _period_to_timedelta(period: ReportPeriod) -> timedelta:
    """Convierte un ReportPeriod a timedelta (duración del período).

    Monthly = 30 días fijos (YAGNI manejar meses de 28/31 — para un
    reporte de diagnóstico hogareño es un proxy aceptable).
    """
    if period is ReportPeriod.WEEKLY:
        return timedelta(days=7)
    return timedelta(days=30)


def _build_report_path(reports_dir: str, period: ReportPeriod, now: datetime) -> str:
    """Construye el path absoluto del archivo de reporte.

    Nombre: ``report_{semanal|mensual}_{YYYYMMDD_HHMMSS}.md``. El
    timestamp de generación evita colisiones entre ticks consecutivos.
    %APPDATA% y vars de entorno se expanden (mismo patrón que
    composition_root._resolve_db_path).
    """
    expanded = os.path.expandvars(reports_dir)
    label, _days = period_to_label(period)
    fname = f"report_{label}_{now.strftime('%Y%m%d_%H%M%S')}.md"
    return str(Path(expanded) / fname)


def _build_period_notification_title(period: ReportPeriod) -> str:
    """Título humano para la toast post-reporte."""
    label, _days = period_to_label(period)
    return f"GND — Reporte {label} generado"


def _build_period_notification_message(
    runs: list[DiagnosticRun], period_start: datetime, period_end: datetime
) -> str:
    """Cuerpo de la toast: {count} corridas, score promedio {avg}/100."""
    avg_score = sum(r.recommendation.score for r in runs) / len(runs) if runs else 0.0
    return (
        f"{len(runs)} corridas en el período "
        f"{period_start:%Y-%m-%d}→{period_end:%Y-%m-%d}. "
        f"Score promedio: {avg_score:.0f}/100."
    )


# ── Scheduler ──────────────────────────────────────────────────────────


class ReportsScheduler:
    """Scheduler periódico que genera reportes Markdown del histórico.

    Lifecycle:
        - ``start()``: agenda el primer tick con ``threading.Timer(daemon=True)``.
        - cada tick ejecuta ``_tick_once``, rearma el Timer siguiente y vuelve.
        - ``stop()``: cancela el Timer pendiente. Idempotente.

    El scheduler NO consume DiagnosticRun en runtime — lee del histórico
    persistido (``RunHistoryReader``) para componer cada reporte. Esto
    permite reportes semanales/mensuales aunque la UI estuviera cerrada
    en el momento de las corridas (los runs se persistieron antes).

    Args (DI):
        config: snapshot inmutable ``ReportConfig`` (período, top_runs,
            reports_dir, flags de notif).
        reader: puerto de lectura de runs en un rango.
        notifier: adapter ``DesktopNotifier`` (12b.2). Si la notif está
            deshabilitada en config, no se invoca.
        clock: callable ``() -> datetime`` (default ``datetime.now``).
        sleeper: callable ``(seconds: float) -> None`` (default ``time.sleep``).
        writer: adapter ``ReportWriter`` (default abre path + escribe str).
    """

    def __init__(
        self,
        *,
        config: ReportConfig,
        reader: RunHistoryReader,
        notifier: DesktopNotifier | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        writer: ReportWriter | None = None,
    ) -> None:
        self._config = config
        self._reader = reader
        self._notifier = notifier
        self._clock: Clock = clock or _default_clock
        self._sleeper: Sleeper = sleeper or _default_sleeper
        self._writer: ReportWriter = writer or _default_writer
        self._timer: threading.Timer | None = None
        self._started = False
        # Último reporte generado (timestamp + path) — expuesto via
        # ``last_report`` para que la UI lo muestre en la status bar.
        self._last_report_at: datetime | None = None
        self._last_report_path: str | None = None
        self._lock = threading.Lock()

    # --- Lifecycle ---

    def start(self) -> None:
        """Arranca el scheduler: agenda el primer tick.

        Idempotente: si ya está iniciado, no reagenda (caller debe
        ``stop()`` primero si quiere reconfigurar).
        """
        with self._lock:
            if self._started:
                return
            self._started = True
            logger.info(
                "Scheduler de reportes arrancado",
                extra={"event": "report.scheduler_start"},
            )
            self._schedule_next_tick()

    def stop(self) -> None:
        """Cancela el tick pendiente. Idempotente.

        El thread daemon se cancela sin join — el proceso de la UI puede
        terminar sin blockarse. El timer noRemovege estado de runs
        persistidos (ya están en DB).
        """
        with self._lock:
            if not self._started:
                return
            self._started = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            logger.info(
                "Scheduler de reportes detenido",
                extra={"event": "report.scheduler_stop"},
            )

    @property
    def last_report_at(self) -> datetime | None:
        return self._last_report_at

    @property
    def last_report_path(self) -> str | None:
        return self._last_report_path

    # --- Internos ---

    def _period_seconds(self) -> float:
        return _period_to_timedelta(self._config.period).total_seconds()

    def _schedule_next_tick(self) -> None:
        """Agenda el siguiente tick con ``threading.Timer``.

        El período en segundos proviene de ``_period_to_timedelta(period)``.
        El callback ejecuta ``_tick_once`` en el hilo del Timer (daemon),
        y al final rearma el siguiente tick — el scheduler es periódico.
        """
        if not self._started:
            return
        seconds = self._period_seconds()
        # ``threading.Timer`` es un Thread subclass — no usa self._sleeper
        # porque el sleeper es para bloquear dentro de un callback, no
        # para esperar el scheduling del callback mismo. El Sleeper queda
        # inyectado por simetría de DI y para fases futuras (ej. backoff).
        self._timer = threading.Timer(seconds, self._tick_once)
        self._timer.daemon = True
        self._timer.start()

    def _tick_once(self) -> None:
        """Ejecuta un tick: lee histórico, compone, escribe, notifica.

        Captura toda excepción y rearma el siguiente tick al final —
        EP §1.2: el scheduler nunca crashea la UI ni se autodestruye
        por un error transitorio (DB corrupta, disco lleno, etc.).
        """
        try:
            logger.info(
                "Iniciando generación de reporte",
                extra={"event": "report.start"},
            )
            now = self._clock()
            period_delta = _period_to_timedelta(self._config.period)
            period_start = now - period_delta
            period_end = now

            runs = self._reader.get_runs_in_period(period_start, period_end)
            if not runs:
                logger.info(
                    "Sin runs en el período — reporte omitido",
                    extra={
                        "event": "report.skip",
                        "reason": "no_runs",
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                )
                return

            report_str = compose_period_report(
                runs,
                self._config,
                period_start=period_start,
                period_end=period_end,
            )
            if report_str is None:
                # compose nunca devuelve None si runs no es vacío — pero
                # defense-in-depth (Regla 11.4 аналог).
                logger.warning(
                    "compose_period_report devolvió None con runs no vacíos",
                    extra={"event": "report.skip", "reason": "compose_none"},
                )
                return

            path = _build_report_path(
                self._config.reports_dir, self._config.period, now
            )
            self._writer.write(path, report_str)
            with self._lock:
                self._last_report_at = now
                self._last_report_path = path

            logger.info(
                "Reporte generado",
                extra={
                    "event": "report.finish",
                    "path": path,
                    "runs_in_period": len(runs),
                },
            )

            self._maybe_notify(runs, period_start, period_end)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Error generando reporte — scheduler continúa",
                extra={
                    "event": "report.error",
                    "error": str(exc),
                    "exc_class": type(exc).__name__,
                },
            )
        finally:
            # Reagenda el siguiente tick al terminar (periódico en stdlib —
            # sin asyncio ni lib externa, YAGNI APScheduler).
            if self._started:
                self._schedule_next_tick()

    def _maybe_notify(
        self,
        runs: list[DiagnosticRun],
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        """Emite toast post-reporte si config lo permite (Fase 12b.2 reuso).

        ``notify_only_on_clean_period=True`` suprime si todos los runs
        fueron safe_to_play — Regla 12b.2.2: omitir > toast degenerada.
        """
        if not self._config.notify_on_generated:
            return
        if self._notifier is None:
            return

        if self._config.notify_only_on_clean_period:
            all_safe = all(r.recommendation.verdict == "safe_to_play" for r in runs)
            if all_safe:
                logger.info(
                    "Notif de reporte suprimida (período limpio)",
                    extra={"event": "notification.skip", "reason": "clean_period"},
                )
                return

        title = _build_period_notification_title(self._config.period)
        message = _build_period_notification_message(runs, period_start, period_end)
        notif = DesktopNotification(title=title, message=message)
        try:
            self._notifier.notify(notif)
        except Exception as exc:  # noqa: BLE001
            # Notif es presentation pura — defense-in-depth adapter buggy.
            logger.warning(
                "Notificador falló generando reporte — reporte ya está en disco",
                extra={
                    "event": "notification.error",
                    "error": str(exc),
                    "exc_class": type(exc).__name__,
                },
            )

    # --- Hook para tests: tick síncrono ---

    def tick_now(self) -> None:
        """Ejecuta un tick sincrónicamente (para tests / UI manual).

        No rearma el Timer — pensado para forzar un reporte bajo
        demanda en tests o en una futura extensión UI (botón "generar
        ahora"). En producción no se invoca; el ciclo real es via Timer.
        """
        self._tick_once()
