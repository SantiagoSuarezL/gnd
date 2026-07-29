"""Configurer del root logger: handlers + JsonFormatter.

Funciones para montar el setup de logging desde el entry point
(`gnd.__main__`) sin manchar ese modulo con detalles de logging —
sigue siendo 5 lineas legibles. El `composition_root` tambien puede
llamarlo si quiere asegurar el setup de logging sin pasar por la UI.

Setup default (Fase 11 + 12a.1: archivo JSONL + stderr):
  - TimedRotatingFileHandler -> `logs/gnd_YYYYMMDD.jsonl` (un archivo por
    dia, rotacion automatica a medianoche). Acepta `logs_dir` (testable) o
    usa default %APPDATA%/GND/logs/. `backupCount` (default 30) controla la
    retencion — archivos mas viejos que `backupCount` se purgan al rotar.
  - StreamHandler -> stderr con MISMO JsonFormatter (decision del
    usuario: consola tambien va en JSON, no texto — un solo formato en
    todo el proceso, consistencia para consumo programatico).
  - Nivel del root logger: `level_global` (default INFO).
  - Nivel del StreamHandler: al menos `level_console` (default WARNING)
    para no saturear la consola con DEBUG/INFO pero SI Errors critica.
    El FileHandler captura TODO el nivel del root logger.

Rotacion + retencion (Fase 12a.1, salda la limitacion Fase 11):
  El nombre base del archivo se fija al momento de construir los handlers
  (se invoca una sola vez desde `__main__.main()` al arrancar la UI).
  `TimedRotatingFileHandler(when='midnight', backupCount=N)` rota a las
  00:00 — renombra el archivo base `gnd_YYYYMMDD.jsonl` agregando sufijo
  de fecha stdlib y abre uno nuevo con el mismo nombre base. Los archivos
  mas viejos que `backupCount` se eliminan en cada rotacion. Apto para
  procesos long-running (24/7) y sesiones interactivas por igual.

  El nombre base incluye la fecha del dia de arranque por legibilidad
  humana (al abrir el archivo en un editor se ve de qué dia es). Al rotar
  a medianoche, el sufijo `.YYYY-MM-DD` que stdlib añade identifica el dia
  rotado; el archivo activo siempre conserva el nombre base sin sufijo.

Idempotente: si `configure_logging` se llama dos veces, la segunda
remueve los handlers previos del root logger antes de instalar los
nuevos (evita duplicar lineas JSON en el archivo). No toca handlers
agregados por terceros con `propagate=True` a menos que se pase
`replace_all=True` (raro; por defecto respeta lo añadido explicitamente).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from gnd.logging.formatter import JsonFormatter

_DEFAULT_LOGS_DIR = "%APPDATA%/GND/logs"
_LOG_FILENAME_PREFIX = "gnd"
# Cantidad de archivos rotados a retener (Fase 12a.1). Default 30 dias —
# sobrado para uso interactivo (~KB por corrida, volumenes bajos). El
# `TimedRotatingFileHandler` stdlib purga archivos `.YYYY-MM-DD_HH-MM-SS`
# mas viejos que backupCount en cada rotacion. Configurable via
# `GndSettings.logging.retention_days`.
_DEFAULT_BACKUP_COUNT = 30


def build_default_handlers(
    logs_dir: str | Path | None = None,
    *,
    stream: object | None = None,
    now: datetime | None = None,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> list[logging.Handler]:
    """Construye el par de handlers estandar del proyecto.

    Fase 12a.1: usa `TimedRotatingFileHandler(when='midnight')` para
    rotar el JSONL a las 00:00 y purgar archivos viejos de forma
    automatica (saldando la limitacion v1 de Fase 11).

    Naming del archivo activo: el nombre base incluye el sufijo
    `YYYYMMDD` del dia de arranque (`gnd_YYYYMMDD.jsonl`) por legibilidad
    humana. Tras una rotacion a medianoche, el stdlib renombra el archivo
    cerrado agregando un sufijo `.YYYY-MM-DD_HH-MM-SS` y reabre uno nuevo
    CON EL MISMO NOMBRE BASE — el archivo activo no cambia de fecha en su
    nombre tras medianoche (limitacion stdlib). Para procesos long-running
    de varios dias, los dias cerrados se distinguen por el sufijo de
    rotacion y los eventos dentro del JSONL llevan su `ts` exacto; el
    consumidor particiona por `run.start` / `ts` si necesita dia-exacto.
    Uso interactivo (sesiones cortas, patron dominante) no se ve afectado:
    cada arranque abre el archivo del dia y los dias siguientes al
    rotarse quedan cerrados con su sufijo.

    Args:
      logs_dir: directorio destino. Si None usa `_DEFAULT_LOGS_DIR`
        (%APPDATA%/GND/logs en Windows; expande variables de entorno).
        Se crea el directorio si no existe (best-effort, log warning si falla).
      stream: stream para el StreamHandler (default sys.stderr). Se acepta
        como object para permitir pasar buffers fake en tests sin importar stderr.
      now: `datetime` inyectable para tests. Determina (1) el sufijo YYYYMMDD
        del nombre base y (2) el `rolloverAt` interno del handler (proxima
        medianoche posterior a `now`). En runtime real se invoca UNA vez
        desde `__main__.main()` con el momento de arranque del proceso.
      backup_count: cantidad de archivos rotados a retener (default 30).
        stdlib purga los mas viejos en cada rotacion.

    Returns:
      Lista de 2 handlers: [TimedRotatingFileHandler JSONL, StreamHandler
      stderr]. Ambos con `JsonFormatter` seteado.
    """
    formatter = JsonFormatter()
    handlers: list[logging.Handler] = []

    # --- TimedRotatingFileHandler JSONL diario (rotacion + retencion) ---
    resolved_dir = _resolve_logs_dir(logs_dir)
    timestamp = (now or datetime.now()).strftime("%Y%m%d")
    filename = f"{_LOG_FILENAME_PREFIX}_{timestamp}.jsonl"
    file_path = resolved_dir / filename
    file_handler = logging.handlers.TimedRotatingFileHandler(
        file_path,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # captura todo
    handlers.append(file_handler)

    # --- StreamHandler stderr (mismo formatter, nivel mas restrictivo) ---
    target_stream = stream if stream is not None else sys.stderr
    stream_handler = logging.StreamHandler(target_stream)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.WARNING)  # consola: warnings+errores
    handlers.append(stream_handler)

    return handlers


def configure_logging(
    handlers: Iterable[logging.Handler] | None = None,
    *,
    level: int = logging.INFO,
    replace_previous: bool = True,
) -> logging.Logger:
    """Configura el root logger con `JsonFormatter` y los handlers dados.

    Args:
      handlers: iterador de handlers a instalar en el root logger. Si None,
        se construyen los handlers por default (`build_default_handlers()`).
      level: nivel del root logger (default INFO). los handlers individuales
        ya filtraran por su propio `setLevel`.
      replace_previous: si True (default), limpia los handlers existentes del
        root logger antes de instalar los nuevos — evita duplicacion de lineas
        en llamadas sucesivas. Si False, anade a los existentes (poco comun).

    Returns:
      El root logger configurado (logging.getLogger()).
    """
    root = logging.getLogger()

    if replace_previous:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except OSError:
                pass  # best-effort close

    if handlers is None:
        chosen_handlers = build_default_handlers()
    else:
        chosen_handlers = list(handlers)
    for handler in chosen_handlers:
        root.addHandler(handler)

    root.setLevel(level)
    return root


def _resolve_logs_dir(logs_dir: str | Path | None) -> Path:
    """Resuelve el directorio de logs, expandiendo variables y creandolo.

    Best-effort: si no puede crear el directorio (permisos, etc.), logea
    en el logger de este modulo y devuelve el Path igual — el FileHandler
    fallara con un mensaje claro al abrir, lo cual prefieramos a silent
    fix-up que podria escribir donde no queremos.
    """
    if logs_dir is None:
        logs_dir = _DEFAULT_LOGS_DIR
    expanded = os.path.expandvars(str(logs_dir))
    path = Path(expanded)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "No se pudo crear el directorio de logs %s: %r. "
            "FileHandler fallara al abrir — prefieramos error explicito "
            "a escribir donde no se debe.",
            path,
            exc,
        )
    return path
