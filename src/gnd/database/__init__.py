"""Adaptador de persistencia SQLite para GND.

TECHNICAL_SPEC.md §3. Implementa DiagnosticsRepository sobre SQLite.
Fase 8: añade SqliteMonitoringRepository para sesiones de monitoreo
(Tablas monitoring_sessions + monitoring_hops, SCHEMA_VERSION=2).
Fase 9: añade SqliteConnectionFactory + DatabaseConnectionFactory Protocol
(Regla de Oro 9.1: cada hilo pide su propia conn, no se comparte).
Fase 12b.3: añade SqliteRunHistoryReader (lectura de DiagnosticRun
completos por rango — inverso de SqliteDiagnosticsRepository.save_run).
"""

from gnd.database.schema import SCHEMA_SQL, SCHEMA_VERSION, ensure_schema
from gnd.database.sqlite_connection_factory import SqliteConnectionFactory
from gnd.database.sqlite_diagnostics_repository import SqliteDiagnosticsRepository
from gnd.database.sqlite_monitoring_repository import SqliteMonitoringRepository
from gnd.database.sqlite_run_history_reader import SqliteRunHistoryReader
from gnd.domain.ports.database import DatabaseConnectionFactory

__all__ = [
    "DatabaseConnectionFactory",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "SqliteConnectionFactory",
    "SqliteDiagnosticsRepository",
    "SqliteMonitoringRepository",
    "SqliteRunHistoryReader",
    "ensure_schema",
]
