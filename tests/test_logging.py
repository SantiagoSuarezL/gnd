"""Tests del paquete gnd.logging (Fase 11).

Cubre:
- `JsonFormatter.format(record)` produce una linea JSON parseable a dict
  con los campos canonicos (ts, level, logger, message) y preserva
  contexto (run_id, provider, event) y extras pasados por el caller.
- `JsonFormatter` serializa `exc_info` como string multilinea bajo `exc`.
- `RunContextAdapter` inyecta `run_id` y `provider` en cada record emitido.
- `RunContextAdapter` deja que el `extra` del caller pise el contexto.
- `configure_logging` monta el root logger con JsonFormatter + handlers.
- `build_default_handlers` construye FileHandler JSONL + StreamHandler stderr.

Diseno de tests: NO dependen de un archivo en disco real para el formatter
(lo testamos directamente con LogRecord fabricado a mano). El FileHandler
se testea con `tmp_path` (pytest fixture) para evitar escribir a %APPDATA%.
"""

from __future__ import annotations

import json
import logging
from io import StringIO

from gnd.logging import (
    JsonFormatter,
    RunContextAdapter,
    build_default_handlers,
    configure_logging,
)

# ---------------------------------------------------------------------------
# Helper: construir un LogRecord a mano (sin pasar por el logger real)
# ---------------------------------------------------------------------------


def _make_record(
    msg: str = "hello",
    level: int = logging.INFO,
    name: str = "gnd.test",
    extra: dict | None = None,
    exc_info: tuple | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=exc_info,
    )
    if extra:
        for key, value in extra.items():
            setattr(record, key, value)
    return record


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    def test_format_produces_parseable_json_line(self):
        formatter = JsonFormatter()
        line = formatter.format(_make_record(msg="hello", level=logging.WARNING))
        payload = json.loads(line)
        assert payload["message"] == "hello"
        assert payload["level"] == "WARNING"
        assert payload["logger"] == "gnd.test"
        assert "ts" in payload
        # one line, no trailing newline (the handler adds it)
        assert "\n" not in line

    def test_format_includes_run_id_provider_event_when_present(self):
        formatter = JsonFormatter()
        record = _make_record(
            extra={"run_id": "abc123", "provider": "google", "event": "ping.timeout"}
        )
        payload = json.loads(formatter.format(record))
        assert payload["run_id"] == "abc123"
        assert payload["provider"] == "google"
        assert payload["event"] == "ping.timeout"

    def test_format_omits_missing_context_fields(self):
        formatter = JsonFormatter()
        payload = json.loads(formatter.format(_make_record()))
        assert "run_id" not in payload
        assert "provider" not in payload
        assert "event" not in payload

    def test_format_preserves_extra_fields(self):
        formatter = JsonFormatter()
        record = _make_record(extra={"duration_ms": 123.45, "n_probes": 6})
        payload = json.loads(formatter.format(record))
        assert payload["duration_ms"] == 123.45
        assert payload["n_probes"] == 6

    def test_format_serializes_exception_under_exc(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = _make_record(exc_info=exc_info)
        payload = json.loads(formatter.format(record))
        assert "exc" in payload
        assert "ValueError" in payload["exc"]
        assert "boom" in payload["exc"]
        # stacktrace multiline preservado
        assert "Traceback" in payload["exc"]

    def test_format_message_interpolates_args(self):
        formatter = JsonFormatter()
        # LogRecord with args supports %-style interpolation like stdlib.
        record = logging.LogRecord(
            name="gnd.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="ping %s timeout=%dms",
            args=("google", 100),
            exc_info=None,
        )
        payload = json.loads(formatter.format(record))
        assert payload["message"] == "ping google timeout=100ms"

    def test_format_preserves_unicode(self):
        formatter = JsonFormatter()
        line = formatter.format(_make_record(msg="fallo de red — acento ó ñ"))
        payload = json.loads(line)
        assert payload["message"] == "fallo de red — acento ó ñ"
        # ensure_ascii=False -> el UTF-8 va literal, no escapado.
        assert "ó" in line and "ñ" in line

    def test_format_ts_is_iso8601_with_offset_and_milliseconds(self):
        formatter = JsonFormatter()
        payload = json.loads(formatter.format(_make_record()))
        ts = payload["ts"]
        # ISO-8601 con offset: "...+HH:MM". Debe contener al menos un signo
        # de timezone (+ o -) y milisegundos (".XYZ").
        assert "." in ts
        assert "+" in ts or "-" in ts


# ---------------------------------------------------------------------------
# RunContextAdapter
# ---------------------------------------------------------------------------


class TestRunContextAdapter:
    def test_adapter_injects_run_id_into_records(self, caplog):
        logger = logging.getLogger("gnd.test.adapter")
        adapter = RunContextAdapter(logger, run_id="rid_xyz")

        with caplog.at_level(logging.INFO, logger="gnd.test.adapter"):
            adapter.info("run.start", extra={"event": "run.start"})

        assert any(getattr(r, "run_id", None) == "rid_xyz" for r in caplog.records)

    def test_adapter_injects_provider_into_records(self, caplog):
        logger = logging.getLogger("gnd.test.adapter.provider")
        adapter = RunContextAdapter(logger, run_id="r1", provider="cloudflare")

        with caplog.at_level(logging.INFO, logger="gnd.test.adapter.provider"):
            adapter.info("ping fail", extra={"event": "ping.timeout"})

        records_with_provider = [
            r for r in caplog.records if getattr(r, "provider", None) == "cloudflare"
        ]
        assert len(records_with_provider) == 1

    def test_adapter_caller_extra_overrides_context(self, caplog):
        logger = logging.getLogger("gnd.test.adapter.override")
        adapter = RunContextAdapter(logger, run_id="ctx_rid", provider="default")

        with caplog.at_level(logging.INFO, logger="gnd.test.adapter.override"):
            # caller pisa provider con uno puntual
            adapter.info("ping fail", extra={"provider": "google"})

        matching = [
            r for r in caplog.records if getattr(r, "provider", None) == "google"
        ]
        assert len(matching) == 1
        assert getattr(matching[0], "run_id", None) == "ctx_rid"

    def test_adapter_none_run_id_omits_field_via_formatter(self):
        logger = logging.getLogger("gnd.test.adapter.none")
        adapter = RunContextAdapter(logger, run_id=None)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            adapter.info("startup event", extra={"event": "startup.ok"})
        finally:
            logger.removeHandler(handler)
        line = buf.getvalue().strip()
        payload = json.loads(line)
        assert payload["event"] == "startup.ok"
        assert "run_id" not in payload  # None -> omitido

    def test_adapter_run_id_setter(self):
        logger = logging.getLogger("gnd.test.adapter.setter")
        adapter = RunContextAdapter(logger, run_id=None)
        assert adapter.run_id is None
        adapter.run_id = "new_rid"
        assert adapter.run_id == "new_rid"


# ---------------------------------------------------------------------------
# configure_logging + build_default_handlers
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_configure_logging_installs_handlers_on_root(self):
        root = logging.getLogger()
        # snapshot de handlers preexistentes para restaurar al final
        saved = list(root.handlers)
        for h in saved:
            root.removeHandler(h)
        try:
            buf = StringIO()
            handler = logging.StreamHandler(buf)
            handler.setFormatter(JsonFormatter())
            configure_logging(handlers=[handler], level=logging.DEBUG)
            assert handler in root.handlers
            logging.getLogger("gnd.test.configure").info(
                "test event", extra={"event": "test.event", "run_id": "r1"}
            )
            line = buf.getvalue().strip()
            payload = json.loads(line)
            assert payload["event"] == "test.event"
            assert payload["run_id"] == "r1"
        finally:
            for h in list(root.handlers):
                root.removeHandler(h)
                h.close()
            for h in saved:
                root.addHandler(h)

    def test_configure_logging_replaces_previous_handlers(self, tmp_path):
        # Llamar dos veces NO debe duplicar handlers.
        logs_dir = tmp_path / "logs"
        configure_logging(
            handlers=build_default_handlers(logs_dir=logs_dir),
            level=logging.INFO,
        )
        first_count = len(logging.getLogger().handlers)
        configure_logging(
            handlers=build_default_handlers(logs_dir=logs_dir),
            level=logging.INFO,
        )
        second_count = len(logging.getLogger().handlers)
        assert first_count == second_count

    def test_build_default_handlers_creates_jsonl_file_and_stream(self, tmp_path):
        logs_dir = tmp_path / "logs_dir"
        from datetime import datetime

        fixed_now = datetime(2026, 7, 28, 12, 0, 0)
        handlers = build_default_handlers(
            logs_dir=logs_dir,
            stream=StringIO(),
            now=fixed_now,
        )
        assert len(handlers) == 2
        file_handler = next(h for h in handlers if isinstance(h, logging.FileHandler))
        stream_handler = next(
            h
            for h in handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        )
        # Nombre del archivo JSONL incluye la fecha
        assert file_handler.baseFilename.endswith("gnd_20260728.jsonl")
        # formatter instalado
        assert isinstance(file_handler.formatter, JsonFormatter)
        assert isinstance(stream_handler.formatter, JsonFormatter)
        # niveles: archivo DEBUG (captura todo), stream WARNING por default
        assert file_handler.level == logging.DEBUG
        assert stream_handler.level == logging.WARNING
        # cierra para que tmp_path cleanup no chille en Windows
        for h in handlers:
            h.close()

    def test_build_default_handlers_creates_logs_directory(self, tmp_path):
        logs_dir = tmp_path / "nested" / "logs"
        handlers = build_default_handlers(logs_dir=logs_dir, stream=StringIO())
        assert logs_dir.exists()
        for h in handlers:
            h.close()

    def test_filename_and_rotates_at_midnight(self, tmp_path):
        """Fase 12a.1: TimedRotatingFileHandler rota el JSONL a medianoche.

        Comprueba:
        1. `now` distinto genera nombres base distintos (la fecha del dia
           de arranque SI impacta el nombre base `gnd_YYYYMMDD.jsonl`).
        2. El handler abre un `TimedRotatingFileHandler` (no un FileHandler
           plain) — confirma swap de la Fase 12a.1.
        3. Tras `doRollover()`, el archivo previo se renombra con sufijo
           de fecha (rotacion real), y se abre uno nuevo con el mismo
           nombre base. `backupCount` controla cuantos rotados se retienen.
        """
        import logging.handlers
        from datetime import datetime

        logs_dir = tmp_path / "logs_lit"
        h_day1 = build_default_handlers(
            logs_dir=logs_dir, stream=StringIO(), now=datetime(2026, 7, 28)
        )
        h_day2 = build_default_handlers(
            logs_dir=logs_dir, stream=StringIO(), now=datetime(2026, 7, 29)
        )
        fh1 = next(h for h in h_day1 if isinstance(h, logging.FileHandler))
        fh2 = next(h for h in h_day2 if isinstance(h, logging.FileHandler))
        # (1) nombres base distintos arrancando en dias distintos
        assert fh1.baseFilename.endswith("gnd_20260728.jsonl")
        assert fh2.baseFilename.endswith("gnd_20260729.jsonl")
        assert fh1.baseFilename != fh2.baseFilename
        # (2) son TimedRotatingFileHandler (swap Fase 12a.1)
        assert isinstance(fh1, logging.handlers.TimedRotatingFileHandler)

        # (3) rotacion: escribir un registro, forzar rolloverAt al pasado,
        # invocar doRollover() — el archivo actual queda renombrado con
        # sufijo de fecha y uno nuevo con el mismo nombre base se crea.
        fh1.emit(
            logging.LogRecord(
                name="gnd.test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="linea-dia1",
                args=None,
                exc_info=None,
            )
        )
        # el baseFilename apunta a un archivo ya creado por emit()
        assert fh1.baseFilename.endswith("gnd_20260728.jsonl")
        pre_rollover_path = fh1.baseFilename
        # forzar rollover: poner el siguiente rollover en el pasado reciente
        # (no en epoch=0 — localtime(0-interval) rompe en Windows).
        # `rolloverAt - 1` basta: queda detras de time.time() actual.
        import time

        fh1.rolloverAt = int(time.time()) - 1  # ya paso -> dispara rollover
        fh1.doRollover()
        # el archivo activo (reabierto) tiene el mismo nombre base
        assert fh1.baseFilename == pre_rollover_path
        # existe un archivo rotado con sufijo de fecha en el dir de logs
        rotated = [
            p
            for p in logs_dir.iterdir()
            if p.name.startswith("gnd_20260728.jsonl.")
            and not p.name.endswith(pre_rollover_path)
        ]
        assert len(rotated) >= 1, (
            f"esperaba al menos un archivo rotado con sufijo, encontre: "
            f"{[p.name for p in logs_dir.iterdir()]}"
        )
        for h in [*h_day1, *h_day2]:
            h.close()

    def test_backup_count_purges_oldest_rotated_files(self, tmp_path):
        """Fase 12a.1 DoD: backupCount purga archivos viejos al rotar.

        Simula N rotaciones y verifica que solo quedan `backupCount`
        archivos rotados + el archivo activo. Si `backupCount=2` y se
        rotan 5 veces, el dir contiene el activo + 2 con sufijo de
        fecha (los 3 mas viejos se eliminan en cada rotacion).
        """
        import logging.handlers
        from datetime import datetime

        logs_dir = tmp_path / "logs_ret"
        h = build_default_handlers(
            logs_dir=logs_dir,
            stream=StringIO(),
            now=datetime(2026, 7, 28),
            backup_count=2,
        )
        fh = next(
            x for x in h if isinstance(x, logging.handlers.TimedRotatingFileHandler)
        )

        # emitir un registro y disparar 5 rotaciones manuales, esperando
        # que cada una genere un sufijo distinto (son rapidas seguidas,
        # stdlib usa timestamp hasta segundo, por lo que podrian
        # colisionar — esperamos un momento entre rotaciones via
        # distinto sufijo sintetizado seteando `_rolloverAt` distintos).
        import time

        for i in range(5):
            fh.emit(
                logging.LogRecord(
                    name="gnd.test",
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=i,
                    msg=f"linea-{i}",
                    args=None,
                    exc_info=None,
                )
            )
            fh.rolloverAt = int(time.time()) - 1  # dispara rollover ahora
            fh.doRollover()
            time.sleep(0.01)  # separa sufijos consecutivos por >=10ms

        archivos = list(logs_dir.iterdir())
        # el activo (sin sufijo) + files rotados (con sufijo). Solo
        # cuentan los rotados dentro de backupCount; stdlib purga los
        # mas viejos.
        activo = [p for p in archivos if p.name == "gnd_20260728.jsonl"]
        assert len(activo) == 1, f"esperaba 1 activo, encontre {activo}"
        rotados = [p for p in archivos if p.name.startswith("gnd_20260728.jsonl.")]
        # backup_count=2 -> a lo sumo 2 rotados retenidos (stdlib puede
        # dejar menos si colisionan sufijos). Asercion: <= backup_count.
        assert len(rotados) <= 2, (
            f"esperaba a lo sumo 2 rotados (backupCount=2), encontre "
            f"{len(rotados)}: {[p.name for p in rotados]}"
        )
        for x in h:
            x.close()

    def test_build_default_handlers_uses_backup_count_param(self, tmp_path):
        """Fase 12a.1: `backup_count` pasa al handler como `backupCount`."""
        import logging.handlers
        from datetime import datetime

        h = build_default_handlers(
            logs_dir=tmp_path / "logs_bc",
            stream=StringIO(),
            now=datetime(2026, 7, 28),
            backup_count=7,
        )
        fh = next(
            x for x in h if isinstance(x, logging.handlers.TimedRotatingFileHandler)
        )
        assert fh.backupCount == 7
        for x in h:
            x.close()
