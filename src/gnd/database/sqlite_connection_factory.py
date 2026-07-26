"""Implementacion real de ``DatabaseConnectionFactory`` sobre SQLite file.

Crea una ``sqlite3.Connection`` fresca al path configurado en cada
call a ``create_connection()``. ``ensure_schema`` se corre por
conexion nueva (idempotente via CREATE TABLE IF NOT EXISTS) para que
cualquier hilo que pida una conexion la encuentre ya migrada.

Regla de Oro 9.1: NO se cachea la conexion. Cada hilo pide la suya.
``check_same_thread`` no se toca (default True) — sqlite3 prohibira
cross-thread use correctamente si alguien la comparte accidentalmente.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from gnd.database.schema import ensure_schema

logger = logging.getLogger(__name__)


class SqliteConnectionFactory:
    """Factory que abre ``sqlite3.connect(path)`` por call.

    Patrones de uso:
    - Composition root: ``factory = SqliteConnectionFactory(db_path)``
    - Worker thread: ``conn = factory.create_connection(); ...``
    """

    def __init__(self, db_path: str) -> None:
        """Configura el path. Expande vars y crea el dir padre una vez.

        ``db_path`` puede contener ``%APPDATA%`` u otras vars de entorno
        (TECHNICAL_SPEC.md §6). La factory resuelve el path al instanciarse
        (no por call) porque crear el directorio padre debe ser idempotente
        y no queremos log de warning en cada ``create_connection()``.
        """
        expanded = os.path.expandvars(db_path)
        p = Path(expanded)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "No se pudo crear el directorio padre de la DB %s: %r. "
                "Se intentara abrir igual (fallara en save_run con mensaje claro).",
                p,
                exc,
            )
        self._db_path = str(p)

    @property
    def db_path(self) -> str:
        """Path absoluto expandido (para diagnostico/tests)."""
        return self._db_path

    def create_connection(self) -> sqlite3.Connection:
        """Abre una conexion nueva + ensure_schema. Caller es el dueno.

        ``check_same_thread`` queda en default True (sqlite3 lo reprime si
        alguien la comparte entre hilos —抗震保护 para futuros bugs del
        mismo tipo). ``ensure_schema`` corre por conexion nueva porque es
        ``CREATE TABLE IF NOT EXISTS`` (idempotente).
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        return conn
