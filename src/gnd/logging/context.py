"""Contexto de corrida para logs: inyecta `run_id` y `provider`.

`RunContextAdapter` (LoggerAdapter): el patron stdlib para anadir
campos a cada log emitido bajo un contexto. El orquestador
`RunFullDiagnostics.execute()` lo construye al inicio de cada corrida
con el `run_id` generado (o recibido) y lo usa en vez del logger crudo
para los eventos de la corrida. Los sub-componentes que ya tienen su
propio `logger = logging.getLogger(__name__)` siguen emitiendo logs
normales — el `run_id` se inyecta solo a los eventos que el adapter
explicitamente emite (run.start, run.finish, stage.start/finish, etc.).

Diseno (EP §5: incluye run_id, y provider "si aplica"):
- `run_id` y `provider` (opcional) viven en el adapter. El `provider`
  se puede overrides por log via `adapter.info(..., extra={"provider":...})`
  — util cuando el orquestador rota sobre providers en un loop.
- El `extra` que el caller pase (incluido `event`, etc.) se merguea
  encima del contexto fijo del adapter — el caller gana.
- `None` como run_id se trata como "no aplica" (sin campo en el JSON).
  El adapter sigue siendo util para emitir eventos `startup.*` del
  proceso entero antes de cualquier corrida (no queremos `"run_id":null`).

Alternativa CONSIDERADA y descartada (Regla 9.5: no agregar codigo
especulativo): `logging.Filter` + contextvars para inyectar `run_id`
a TODOS los loggers del proceso via thread-local. Se descarto porque:
(a) la UI corre una corrida a la vez (controller rechaza invocations
si hay diagnostico en curso, ver `ui/controller.py`), no hay
concurrencia de `execute()` que justifique contextvars; (b) Fase 12
(features avanzadas: WARP/speedtest/notifications/etc.) y Fase 13
(extensibilidad multi-juego: modulos distintos, no concurrencia)
no requieren multiples corridas paralelas. Si la necesidad aparece
en el futuro con tests reales que la justifiquen, se reintroduce en
ese momento — no como cadaver en el codigo hojeando vulture (Regla 9.5).
"""

from __future__ import annotations

import logging
from typing import Any


class RunContextAdapter(logging.LoggerAdapter):
    """`LoggerAdapter` que anade `run_id` y (opcional) `provider` a cada log.

    Uso:
        adapter = RunContextAdapter(logger, run_id="abc123")
        adapter.info("run.start", extra={"event": "run.start"})
        adapter.info("ping fail", extra={"provider": "google", "event": "..."})

    El `extra` del caller SIEMPRE gana sobre el contexto del adapter —
    eso permite overrides puntuales (un log que no corresponda al
    provider default, etc.) sin instanciar otro adapter.
    """

    def __init__(
        self,
        logger: logging.Logger,
        run_id: str | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(logger, {"run_id": run_id, "provider": provider})

    @property
    def run_id(self) -> str | None:
        return self.extra.get("run_id") if self.extra else None

    @run_id.setter
    def run_id(self, value: str | None) -> None:
        if self.extra is None:
            self.extra = {}
        self.extra["run_id"] = value

    @property
    def provider(self) -> str | None:
        return self.extra.get("provider") if self.extra else None

    @provider.setter
    def provider(self, value: str | None) -> None:
        if self.extra is None:
            self.extra = {}
        self.extra["provider"] = value

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        # LoggerAdapter.process se llama antes de emitir. `extra` del caller
        # viene en kwargs["extra"] (dict). Mezclamos ahi, el caller gana.
        extra = kwargs.setdefault("extra", {})
        ctx = self.extra or {}
        for key, value in ctx.items():
            if value is not None and key not in extra:
                extra[key] = value
        return msg, kwargs
