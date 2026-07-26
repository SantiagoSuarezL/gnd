"""Puerto RouteMonitor — monitoreo continuo de ruta estilo WinMTR.

TECHNICAL_SPEC.md §2.4 + IMPLEMENTATION_PLAN.md Fase 8.

Implementacion real en monitoring/ (orquestra un `Protocol TracerouteRunner`
N veces y acumula estadisticas por hop). Implementacion fake en
domain/fakes/ para tests sin red.

El puerto del repositorio (`MonitoringRepository`) se separa de
`DiagnosticsRepository` (EP §2.I — Interface Segregation) porque las
sesiones de monitoreo tienen un ciclo de vida distinto a las corridas
de diagnostico completas: pueden ser persistidas y consultadas de forma
independiente. Un consumidor que solo hace monitoreo no necesita depender
de la capacidad de guardar DiagnosticRuns completos.
"""

from typing import Protocol, runtime_checkable

from gnd.models.monitoring import MonitoringSession


@runtime_checkable
class RouteMonitor(Protocol):
    """Ejecuta una sesion de monitoreo de ruta contra un target.

    Toma N muestras de traceroute a intervalos regulares contra el MISMO
    target y devuelve una `MonitoringSession` con las muestras individuales
    y las estadisticas agregadas por hop (avg/worst/best/loss/jitter).

    No lanza excepciones hacia el caller (EP §1.2): cualquier fallo
    individual del traceroute se resume como un sample con `rtt_ms=None`
    para esos hops; la sesion completa puede quedar con menos muestras de
    las planeadas, pero nunca como excepcion.
    """

    def monitor(
        self,
        *,
        target_ip: str,
        target_provider: str,
        run_id: str,
        interval_s: float,
        duration_s: float,
        max_hops: int,
        timeout_ms: int,
    ) -> MonitoringSession: ...


@runtime_checkable
class MonitoringRepository(Protocol):
    """Persiste y recupera sesiones de monitoreo de ruta.

    EP §2.I — interfaz segregada de `DiagnosticsRepository`. El monitoreo
    es un ciudadano de primera clase del pipeline Fase 8 y merece su
    propio puerto de persistencia.
    """

    def save_session(self, session: MonitoringSession) -> None: ...

    def get_sessions_by_run(
        self,
        run_id: str,
    ) -> list[MonitoringSession]: ...
