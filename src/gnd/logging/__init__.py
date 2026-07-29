"""Logging estructurado JSON para GND (Fase 11, IMPLEMENTATION_PLAN.md §11).

Implementacion con stdlib `logging` unicamente (EP §5: no se introduce
dependencia externa de logging para este tamano de proyecto). Cada
registro se emite como una linea JSON parseable (JSONL) — un objeto por
linea, sin array envolvente — para que herramientas como `jq` o un
aggregator de logs puedan consumirlo en streaming.

API publica:
- `JsonFormatter`: `logging.Formatter` que serializa `LogRecord` a JSON.
- `RunContextAdapter`: `LoggerAdapter` que inyecta `run_id` (y opcional
  `provider`) en cada registro emitido durante una corrida de diagnostico.
- `configure_logging(handlers)`: monta el root logger con `JsonFormatter`
  y handlers indicados (FileHandler JSONL + StreamHandler stderr por defecto).
- `build_default_handlers(logs_dir, stream)`: construye el par de handlers
  estandar del proyecto (archivo JSONL rotado por dia + stderr).

Convencion de campos (EP §5):
  ts            ISO-8601 UTC con offset, milisegundos
  level         "INFO" / "WARNING" / ... (string upper)
  logger        nombre del logger (campo "name" de LogRecord)
  component     modulo calificado (name del logger, alias legible)
  run_id        identificador de la corrida (vacio si no aplica, ej. startup)
  message       mensaje principal (siempre presente)
  provider      proveedor afectado (solo si aplica, ej. "google")
  event         etiqueta corta del evento (ej. "run.start", "run.finish")
  extra         dict arbitrary de campos adicionales (merge con lo de arriba)
  exc           stacktrace serializado solo si hay excepcion (exc_info=True)
"""

from __future__ import annotations

from gnd.logging.configurer import build_default_handlers, configure_logging
from gnd.logging.context import RunContextAdapter
from gnd.logging.formatter import JsonFormatter

__all__ = [
    "JsonFormatter",
    "RunContextAdapter",
    "build_default_handlers",
    "configure_logging",
]
