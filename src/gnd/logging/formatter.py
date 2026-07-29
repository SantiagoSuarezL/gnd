"""JsonFormatter: serializa `LogRecord` a una linea JSON (JSONL).

Diseno:
- Cada `record.msg` ya es el "mensaje humano". El formatter no lo
  envuelve ni lo traduce.
- Campos de contexto (`run_id`, `provider`, `event`) se toman de
  `record.__dict__` — el `RunContextAdapter` y los `logger.<level>(...
  extra={...})` los ponen ahi. Ausente = no se incluye en el JSON (no
  poner `null` — keep it tight, EP §5: "campos relevantes").
- `exc_info` se serializa como string multi-linea bajo la key `exc`.
  No se splittea en lineas JSON separadas (rompe la one-line-per-record
  y dificulta el consumo con `jq`).
- El timestamp se emite en ISO-8601 con offset y milisegundos —
  `datetime.isoformat()` cumple. EP §5 pide "timestamp"; este es el
  formato estandar, no usamos epoch ni RFC 2822.

No usa `json.dumps(default=...)` con un fallback a `str` — si un campo
no es serializable, se serializa explicitamente a string solo donde se
sabe que puede pasar (args, exc). Esto evita transformarse
silenciosamente objetos exoticos en strings imprevistos.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

# Campos del LogRecord que NO queremos volcar al JSON final — son metadata
# interna de logging o duplicados de campos ya canonicos arriba.
_RECORD_RESERVED: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """`logging.Formatter` que emite cada registro como una linea JSON.

    Uso tipico (ver `configurer.configure_logging`):
        formatter = JsonFormatter()
        handler.setFormatter(formatter)

    El formatter es stateless — se puede compartir entre handlers.

    Orden de merge de campos (los ultimos pisan a los anteriores):
      1. Campos canonicos fijos: ts, level, logger, message.
      2. Campos de contexto: run_id, provider, event (si presentes en
         el record, normalmente puestos por `RunContextAdapter`).
      3. Campos extra que el caller paso via `logger.info(msg, extra={...})`.
         Cualquier key del record que no este reservada ni ya usada se
         vuelca al JSON.

    Invariante de salida: una sola linea JSON por registro, sin trailing
    newline dentro del JSON (la newline la anade el handler al emitir).
    """

    def format(self, record: logging.LogRecord) -> str:
        # Asegura que record.message este resuelto (interpolacion de args).
        # `Formatter.format` lo hace, pero tambien arma asctime/exc_text
        # que no necesitamos. Duplicar la resolution es mas simple que
        # reimplementar la logica de excepcion a mano.
        record.message = record.getMessage()

        payload: dict[str, Any] = {
            "ts": _iso_utc(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        if record.exc_info:
            payload["exc"] = self._format_exception(record)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # Contexto de corrida (RunContextAdapter / extra) — solo si presentes.
        run_id = getattr(record, "run_id", None)
        if run_id:
            payload["run_id"] = run_id
        provider = getattr(record, "provider", None)
        if provider:
            payload["provider"] = provider
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event

        # Extras del caller (todo lo que no sea interno de logging ni ya volcado).
        for key, value in record.__dict__.items():
            if key in _RECORD_RESERVED or key in payload:
                continue
            if key.startswith("_"):
                continue
            payload[key] = value

        # `ensure_ascii=False` preserva acentos y UTF-8 nativo de la salida.
        # `separators=(",", ":")` quita whitespace redundante -> lineas mas chicas.
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _format_exception(record: logging.LogRecord) -> str:
        # Si Formatter ya lo computo, reusar; sino forzar a partir de exc_info.
        # `formatException` lo invoca `Formatter.format` normalmente; si
        # llegamos aca sin pasar por format() (no es el caso en este path,
        # pero por robustez), lo invocamos explicitamente.
        if record.exc_text:
            return record.exc_text
        if record.exc_info:
            return logging.Formatter().formatException(record.exc_info)
        return ""


def _iso_utc(record: logging.LogRecord) -> str:
    """Convierte `record.created` (epoch float) a ISO-8601 con offset.

    `record.created` es tiempo de wall-clock del evento (cuando se
    emitio el log), no cuando se formatea. Usamos timezone local (no UTC
    hardcodeado) — el offset va en el string ISO, asi el consumidor
    puede convertir a cualquier zona horaria. EP §5 pide "timestamp";
    este es el formato mas informativo.
    """
    dt = datetime.fromtimestamp(record.created, tz=UTC).astimezone()
    # `timespec="milliseconds"` trunca a 3 digitos — nanosegundos no aportan.
    return dt.isoformat(timespec="milliseconds")
