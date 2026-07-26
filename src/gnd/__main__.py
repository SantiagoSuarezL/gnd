"""Entry point: `python -m gnd` — lanza la UI.

Wiring via composition_root (EP §2.D: unico punto donde se decide
que implementacion concreta usar). La UI no sabe ni decide nada.
"""

from __future__ import annotations

import logging


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Import local: el import de UI debe fallar tarde (no en import-time
    # del paquete) si tkinter no esta disponible en un entorno headless.
    from gnd.composition_root import build_run_full_diagnostics
    from gnd.ui.main_window import MainWindow

    use_case, targets, params = build_run_full_diagnostics()
    window = MainWindow(use_case=use_case, targets=targets, params=params)
    window.run()


if __name__ == "__main__":
    main()
