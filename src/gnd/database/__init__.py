"""Adaptador de persistencia SQLite para GND.

TECHNICAL_SPEC.md §3. Implementa DiagnosticsRepository sobre SQLite.
"""

from gnd.database.schema import SCHEMA_SQL, SCHEMA_VERSION, ensure_schema
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository

__all__ = [
    "ensure_schema",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "SqliteDiagnosticsRepository",
]
