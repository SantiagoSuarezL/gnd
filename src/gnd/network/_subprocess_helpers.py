"""Helper para invocar subprocesses sin ventana de consola en Windows.

Protocolo Crítico (post-Fase 14.0a, launcher VBS): cuando GND se lanza
via `pythonw.exe` (wrapper VBS del acceso directo, sin terminal padre),
cada `subprocess.run` que invoca un binario de consola (ping, tracert,
netsh, warp-cli, ookla-speedtest) abre SU PROPIA ventana de cmd que
parpadea en pantalla. El flag Windows `CREATE_NO_WINDOW` (0x08000000)
evita que se cree esa ventana hija — el subprocess corre invisible y
la UI de tkinter queda como la única surface visible.

El flag es un no-op en POSIX (subprocess.run ignora `creationflags`
desconocidos en Unix via `Popen.__init__` que filtra kwargs a
`_get_handles` solo bajo Windows), por eso el helper solo lo aplica
cuando `platform.system() == "Windows"` — no necesita branching en
cada adapter.

Tests: los tests de estos adapters mockean `subprocess.run` con
`monkeypatch.setattr("subprocess.run", ...)` o usan `FakeProcessRunner`
inyectado via DI. El helper no afecta esos paths porque solo toca el
path real (`_DefaultProcessRunner` / `_run` directo) — los tests que
mockean `subprocess.run` reemplazan la función antes de que se llame,
sin pasar por el helper. Ver `test_real_warp_controller.py`,
`test_real_speed_test_controller.py`,
`test_real_network_interface_inspector.py`,
`test_real_ping_runner.py`, `test_real_traceroute_runner.py`.
"""

from __future__ import annotations

import platform


def subprocess_kwargs(extra: dict | None = None) -> dict:
    """Devuelve kwargs para ``subprocess.run``/``Popen`` que ocultan
    la ventana de consola en Windows. En POSIX no hace nada (no rompe
    cross-platform).

    Uso típico::

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **subprocess_kwargs(),
        )

    Si el caller ya tiene un dict de kwargs, puede combinarse::

        kwargs = {"capture_output": True, "text": True, "timeout": 10}
        result = subprocess.run(cmd, **kwargs, **subprocess_kwargs())

    Parametros opcionales:
        extra: dict con overrides (ej. ``{"creationflags": 0}`` para
            forzar ventana visible en debug). Las claves en `extra`
            prevalecen sobre las del helper.
    """
    merged: dict = {}
    if platform.system() == "Windows":
        # CREATE_NO_WINDOW = 0x08000000. Sin este flag, cada subprocess
        # spawn hereda una nueva consola cuando el proceso padre es
        # windowless (pythonw.exe). Documentado en Microsoft Learn:
        # https://learn.microsoft.com/windows/win32/procthread/process-creation-flags
        merged["creationflags"] = 0x08000000
    if extra:
        merged.update(extra)
    return merged


__all__ = ["subprocess_kwargs"]
