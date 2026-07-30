"""Value object de una notificacion de escritorio (Fase 12b.2).

A diferencia de los otros modelos de dominio (ProbeResult, DiagnosticRun,
etc.) que nacen de observaciones de red, ``DesktopNotification`` es un
value object puro: el payload que el adaptador ``PlyerDesktopNotifier``
consume para emitir una toast del OS. No tiene logica ni invariantes
 Complejos — solo datos inmutables que la capa de presentation
(``notifications/run_formatter.py``) construye y el adapter consume.

Razon de ser un modelo (vs. un dict suelto): mantener el contrato explicito
y forzar invariantes (title/message no vacios) en el punto de construccion.
El adapter ``PlyerDesktopNotifier`` recibe un ``DesktopNotification`` y
sabe con certeza que los campos existen y son strings no vacios — sin
 typed checking en el boundary.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DesktopNotification:
    """Payload inmutable para una notificacion de escritorio.

    Atributos:
        title: titulo corto (header toast). Max ~60 chars visible en Win10.
        message: cuerpo corto del mensaje. Max ~120 chars visible.

    Invariante: ninguno de los dos puede ser vacio. Una notif sin
    contenido es un bug del caller (formatter), no un caso legítimo.
    """

    title: str
    message: str

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("title no puede ser vacío")
        if not self.message:
            raise ValueError("message no puede ser vacío")
