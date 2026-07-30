"""Entry point: `python -m gnd` — lanza la UI.

Wiring via composition_root (EP §2.D: unico punto donde se decide
que implementacion concreta usar). La UI no sabe ni decide nada.

Setup de logging (Fase 11): JsonFormatter + FileHandler JSONL diario
(`logs/gnd_YYYYMMDD.jsonl`) + StreamHandler stderr. La configuracion
(level, logs_dir, console_level) se lee de GndSettings (config.toml / env).
"""

from __future__ import annotations

import logging

from gnd.config import get_settings
from gnd.logging import build_default_handlers, configure_logging


def main() -> None:
    settings = get_settings()
    root_level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    console_level = getattr(
        logging, settings.logging.console_level.upper(), logging.WARNING
    )

    handlers = build_default_handlers(
        logs_dir=settings.logging.logs_dir,
        backup_count=settings.logging.retention_days,
    )
    # El FileHandler captura el nivel del root; el StreamHandler restringe.
    # build_default_handlers ya setea DEBUG al archivo y WARNING al stream;
    # aqui ajustamos el stream al nivel configurado (console_level).
    for h in handlers:
        # El isinstance check distingue FileHandler (que hereda de
        # StreamHandler) del StreamHandler puro (stderr). Nota:
        # TimedRotatingFileHandler (Fase 12a.1) hereda de FileHandler — el
        # check sigue distinguiendolo correctamente del StreamHandler puro.
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ):
            h.setLevel(console_level)
    configure_logging(handlers=handlers, level=root_level)

    # Import local: el import de UI debe fallar tarde (no en import-time
    # del paquete) si tkinter no esta disponible en un entorno headless.
    from gnd.composition_root import (
        build_notifier,
        build_report_pipeline,
        build_run_full_diagnostics,
        build_series_source,
        build_speed_test_comparison,
        build_speed_test_controller,
        build_warp_comparison,
        build_warp_controller,
    )
    from gnd.ui.main_window import MainWindow

    use_case, targets, params = build_run_full_diagnostics()
    series_source = build_series_source()
    # Fase 12b.2: notifier de escritorio (toasts post-run). Construccion
    # siempre (aunque plyer falte, el adapter se vuelve no-op con log);
    # la activacion real la controla ``settings.notifications.enabled``.
    notifier = build_notifier()
    # Fase 12b.3: pipeline de reportes periodicos (scheduler con
    # ``threading.Timer`` daemon). Construccion condicional solo si la
    # config lo habilita — el scheduler no arranca un hilo daemon si
    # ``settings.reports.enabled=False`` (YAGNI/Regla 9.5).
    report_scheduler = None
    if settings.reports.enabled:
        _report_reader, report_scheduler = build_report_pipeline()
    # Fase 12b.4: comparación WARP on/off. Construye el controller siempre
    # (cheap check de PATH); el use case solo si el usuario habilitó la
    # feature (opt-in via ``settings.warp_comparison.enabled=True``). El
    # RealWarpController se marca ``available=False`` si warp-cli no está
    # en PATH (Regla 12b.2.1), pero se construye siempre sin crashear.
    warp_controller = build_warp_controller()
    warp_comparison = None
    if settings.warp_comparison.enabled:
        warp_comparison = build_warp_comparison(
            diagnostics_use_case=use_case,
            warp_controller=warp_controller,
        )
    # Fase 12b.5: speed test bajo demanda. Construye el controller siempre
    # (cheap check de PATH); el use case solo si el usuario habilitó la
    # feature (opt-in via ``settings.speed_test.enabled=True``). El
    # RealSpeedTestController se marca ``available=False`` si speedtest no
    # está en PATH (Regla 12b.2.1), pero se construye siempre sin crashear.
    speed_test_controller = build_speed_test_controller()
    speed_test_comparison = None
    if settings.speed_test.enabled:
        speed_test_comparison = build_speed_test_comparison(
            diagnostics_use_case=use_case,
            speed_test_controller=speed_test_controller,
        )
    window = MainWindow(
        use_case=use_case,
        targets=targets,
        params=params,
        series_source=series_source,
        notifier=notifier,
        notify_settings=settings.notifications,
        report_scheduler=report_scheduler,
        warp_controller=warp_controller,
        warp_comparison=warp_comparison,
        warp_settings=settings.warp_comparison,
        speed_test_controller=speed_test_controller,
        speed_test_comparison=speed_test_comparison,
        speed_test_settings=settings.speed_test,
    )
    window.run()


if __name__ == "__main__":
    main()
