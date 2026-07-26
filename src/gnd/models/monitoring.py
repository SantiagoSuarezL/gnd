"""Modelos de dominio para monitoreo continuo de ruta (estilo WinMTR).

TECHNICAL_SPEC.md §2.4 — IMPLEMENTATION_PLAN.md Fase 8.

Una sesión de monitoreo ejecuta N traceroutes contra el MISMO target a
intervalos regulares y acumula estadisticas por HOP (no solo el destino
final). La agregacion se hace por ``hop_number`` (posicion TTL en la
ruta), no por IP — porque los IPs pueden cambiar entre muestras de una
misma ruta por ECMP / load balancing en routers intermedios, mientras que
la posicion TTL es estable para el mismo target. Este es el mismo
criterio que usa WinMTR.

Inmutabilidad (EP §1.6): todos los modelos son ``@dataclass(frozen=True)``.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class HopStats:
    """Estadisticas agregadas de un unico hop a lo largo de N muestras.

    DoD Fase 8: una sesion de N segundos produce estadisticas agregadas
    por hop (avg/worst/best/loss/jitter) coherentes con las muestras
    individuales.

    Campos:
        hop_number: posicion en la ruta (1-indexed, igual que TracerouteHop).
        ip: IP del hop mas frecuente (moda); None si nunca respondio.
        hostname: hostname del hop mas frecuente; None si no aplica.
        best_ms: menor rtt observado cuando respondio (None si ninguna).
        worst_ms: mayor rtt observado cuando respondio (None si ninguna).
        avg_ms: promedio de rtts de muestras que respondieron (None si 0).
        jitter_ms: desviacion estandar de los rtts que respondieron;
            0.0 si hubo una sola muestra (no hay variabilidad medible).
        loss_pct: porcentaje de muestras donde el hop NO respondio
            (timeout o silencio). Rango [0, 100].
        samples: total de muestras observadas para este hop (>=1).
        success_count: muestras donde respondio (rtt_ms not None).
    """

    hop_number: int
    ip: str | None
    hostname: str | None
    best_ms: float | None
    worst_ms: float | None
    avg_ms: float | None
    jitter_ms: float
    loss_pct: float
    samples: int
    success_count: int

    def __post_init__(self) -> None:
        if self.hop_number < 1:
            raise ValueError(f"hop_number debe ser >= 1, fue {self.hop_number}")
        if self.samples < 1:
            raise ValueError(f"samples debe ser >= 1, fue {self.samples}")
        if not (0.0 <= self.loss_pct <= 100.0):
            raise ValueError(f"loss_pct debe estar en [0, 100], fue {self.loss_pct}")
        if self.jitter_ms < 0.0:
            raise ValueError(f"jitter_ms debe ser >= 0, fue {self.jitter_ms}")
        if not (0 <= self.success_count <= self.samples):
            raise ValueError(
                f"success_count fuera de rango [0, samples={self.samples}]: "
                f"success_count={self.success_count}"
            )
        # Invariantes de best/worst/avg:
        # - si success_count == 0, los tres deben ser None.
        # - si success_count >= 1, los tres deben estar seteados y cumplir
        #   best <= avg <= worst.
        if self.success_count == 0:
            if (
                self.best_ms is not None
                or self.worst_ms is not None
                or self.avg_ms is not None
            ):
                raise ValueError(
                    "si success_count == 0, best/worst/avg deben ser None, "
                    f"fueron best={self.best_ms} worst={self.worst_ms} "
                    f"avg={self.avg_ms}"
                )
        else:
            if self.best_ms is None or self.worst_ms is None or self.avg_ms is None:
                raise ValueError(
                    "si success_count >= 1, best/worst/avg deben tener valor: "
                    f"best={self.best_ms} worst={self.worst_ms} avg={self.avg_ms}"
                )
            if not (self.best_ms <= self.avg_ms <= self.worst_ms):
                raise ValueError(
                    "debe cumplirse best<=avg<=worst: "
                    f"best={self.best_ms} avg={self.avg_ms} "
                    f"worst={self.worst_ms}"
                )
            if self.best_ms < 0.0 or self.avg_ms < 0.0 or self.worst_ms < 0.0:
                raise ValueError("rtt values deben ser >= 0")


@dataclass(frozen=True)
class MonitoringSample:
    """Una sola muestra de un hop en una sesion de monitoreo.

    ``rtt_ms=None`` indica que el hop no respondio (timeout / silencio).
    Esto NO es un error — se cuenta como loss para ese hop en la
    agregacion, igual que ``TracerouteHop(responded=False)``.

    La sesion conserva las muestras individuales para permitir
    reconstruir el comportamiento de la ruta en el tiempo
    (TECHNICAL_SPEC.md §2.4: "persistir cada corrida como una sesion
    de monitoreo vinculada a un run_id").
    """

    sample_index: int
    hop_number: int
    rtt_ms: float | None

    def __post_init__(self) -> None:
        if self.sample_index < 0:
            raise ValueError(f"sample_index debe ser >= 0, fue {self.sample_index}")
        if self.hop_number < 1:
            raise ValueError(f"hop_number debe ser >= 1, fue {self.hop_number}")
        if self.rtt_ms is not None and self.rtt_ms < 0.0:
            raise ValueError(f"rtt_ms debe ser >= 0, fue {self.rtt_ms}")


@dataclass(frozen=True)
class MonitoringSession:
    """Resultado completo de una sesion de monitoreo de ruta.

    Agrupa los ``len(samples)`` muestras individuales tomadas en la sesion
    y los ``hop_stats`` agregados por hop. Se vincula a un ``run_id`` que
    identifica la corrida de diagnostico que la origino (TECHNICAL_SPEC.md
    §2.4: "persistir cada corrida como una sesion de monitoreo vinculada
    a un run_id").

    Campos:
        run_id: identificador de la corrida de diagnostico padre.
        target_ip: target sondeado (hostname o IP segun como lo llamo).
        target_provider: provider del target (mismo namespace que
            ``TracerouteResult.target_provider`` y ``ProbeResult.provider``).
        started_at: timestamp de la primera muestra.
        finished_at: timestamp de la ultima muestra (>= started_at).
        interval_s: intervalo nominal entre muestras (configurable).
        samples: muestras individuales (1 por hop por toma). Vacio = sesion
            abortada antes de la primera toma.
        hop_stats: estadisticas agregadas por hop_number. Vacio si samples
            vacio. Ordenado por hop_number ascendente.
    """

    run_id: str
    target_ip: str
    target_provider: str
    started_at: datetime
    finished_at: datetime
    interval_s: float
    samples: list[MonitoringSample]
    hop_stats: list[HopStats]

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id no puede ser vacio")
        if not self.target_ip:
            raise ValueError("target_ip no puede ser vacio")
        if not self.target_provider:
            raise ValueError("target_provider no puede ser vacio")
        if self.interval_s < 0.0:
            raise ValueError(f"interval_s debe ser >= 0, fue {self.interval_s}")
        if self.finished_at < self.started_at:
            raise ValueError(
                "finished_at no puede ser anterior a started_at "
                f"(start={self.started_at} finish={self.finished_at})"
            )
        # Si hay samples, debe haber hop_stats (las stats se derivan de las
        # muestras; no puede haber muestras sin stats). El reverso NO se
        # exige: al persistir en DB solo se guardan stats agregadas, las
        # muestras crudas se descartan. Una MonitoringSession reconstruida
        # de DB puede tener samples=[] y hop_stats no vacio (snapshot).
        if self.samples and not self.hop_stats:
            raise ValueError(
                "si hay samples, hop_stats no puede ser vacio; "
                f"samples={len(self.samples)} hop_stats=0"
            )
        # hop_stats ordenado por hop_number ascendente y unico (si no vacio).
        if self.hop_stats:
            numbers = [h.hop_number for h in self.hop_stats]
            if numbers != sorted(numbers):
                raise ValueError(
                    f"hop_stats debe estar ordenado por hop_number: {numbers}"
                )
            if len(set(numbers)) != len(numbers):
                raise ValueError(f"hop_stats con hop_number duplicado: {numbers}")
