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
    from gnd.composition_root import build_run_full_diagnostics, build_series_source
    from gnd.ui.main_window import MainWindow

    use_case, targets, params = build_run_full_diagnostics()
    series_source = build_series_source()
    window = MainWindow(
        use_case=use_case,
        targets=targets,
        params=params,
        series_source=series_source,
    )
    window.run()


if __name__ == "__main__":
    main()
