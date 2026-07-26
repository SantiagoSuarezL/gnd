"""Implementacion real de `Protocol TracerouteRunner` (ARCHITECTURE.md \u00a72).

Ejecuta el `tracert` nativo de Windows via `subprocess` y parsea el output con
`network/tracert_parser`. La logica de deteccion del `culprit_hop_index`
vive en `detect_culprit_hop` (TECHNICAL_SPEC.md \u00a72.3).

El runner respeta la regla de EP \u00a71.2 (ningun resultado de red debe ser excepcion):
- `subprocess.TimeoutExpired` -> TracerouteResult con hops parciales
  tomados hasta el timeout.
- `OSError` (tracert no existe, permisos) -> TracerouteResult con hops=().
- Output ilegible / sin hops -> TracerouteResult con hops=().
El caller decide que hacer con un TracerouteResult vacio (motivo: sin ruta).

Reglas clave de deteccion del culprit (TECHNICAL_SPEC.md \u00a72.3):
- Recorrer hops en orden.
- Marcarculprit_hop_index en el primer hop donde rtt_ms sube MAS DE
  threshold_ms (default 40ms) respecto al ULTIMO hop que respondio (no el
  inmediatamente anterior si este no respondio).
- Y ese incremento se MANTIENE en hops subsiguientes: basta con que al menos
  un hop subsiguiente responda con un rtt >= (salto + threshold - delta) donde
  delta es un margen pequenno de tolerancia (por defecto 5ms) para absorber
  fluctuaciones. Esto descarta picos de un solo hop (escenario: router que
  desprioriza ICMP pero no afecta trafico real).
- Hops que no respondieron (responded=False) NO son error ni penalizan: se
  saltan en la comparacion (no aportan rtt, no se consideran culpables).
"""

from __future__ import annotations

import logging
import platform
import re
import socket
import subprocess
from typing import Protocol

from gnd.models.traceroute import TracerouteHop, TracerouteResult
from gnd.network import tracert_parser

logger = logging.getLogger(__name__)


# --- Regex para detectar si el target ya es una IPv4 ---
_IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$"
)


def _looks_like_ipv4(target: str) -> bool:
    return bool(_IPV4_PATTERN.match(target))


# --- Deteccion del culprit hop (logica pura, testeable sin red) ---


def detect_culprit_hop(
    hops: list[TracerouteHop],
    jump_threshold_ms: float = 40.0,
    sustain_tolerance_ms: float = 5.0,
) -> int | None:
    """Detecta el indice (0-based) del hop culpable del salto de latencia.

    Algoritmo (TECHNICAL_SPEC.md \u00a72.3):

    1. Recorrer hops en orden, tracking el rtt del ultimo hop que respondio
       (``last_responded_rtt``).
    2. Cuando un hop respondio con ``rtt_ms``, compararlo con ``last_responded_rtt``:
       si la diferencia supera ``jump_threshold_ms``, marcarlo como candidato
       a culpable.
    3. Validar que el incremento se sostiene en hops subsiguientes: algun hop
       despues del candidato tiene que responder con rtt
       ``>= candidato.rtt - sustain_tolerance_ms`` (es decir, esta cerca del
       nuevo nivel). Si todos los hops subsiguientes solo bajan al nivel
       anterior, el "salto" fue un pico puntual y NO se marca como culpable.
    4. El primer candidato que cumpla (1) + (3) es el ``culprit_hop_index``.

    Hops que no respondieron (``responded=False``) se saltan en la comparacion:
    no aportan rtt, no se consideran culpables. Si todos los hops no responden,
    devuelve None.

    Args:
        hops: lista de hops de un TracerouteResult (en orden, 0-indexados).
        jump_threshold_ms: umbral minimo de salto (default 40ms).
        sustain_tolerance_ms: margen de tolerancia para considerar que un salto
            se mantiene (default 5ms).

    Returns:
        Indice 0-based dentro de ``hops`` del primer hop culpable, o None si no
        se detecto ninguno.
    """
    if not hops:
        return None

    last_responded_rtt: float | None = None

    for i, hop in enumerate(hops):
        if not hop.responded or hop.rtt_ms is None:
            # Hops no respondidos: salimos sin marcar culpable aqui. Continuamos.
            continue

        if last_responded_rtt is None:
            # Primer hop que responde; no hay previo para comparar.
            last_responded_rtt = hop.rtt_ms
            continue

        delta = hop.rtt_ms - last_responded_rtt
        if delta > jump_threshold_ms:
            # Candidato a culpable: validar sosten en hops subsiguientes.
            if _sustained_jump(hops, candidate_idx=i, tolerance=sustain_tolerance_ms):
                return i
        last_responded_rtt = hop.rtt_ms

    return None


def _sustained_jump(
    hops: list[TracerouteHop],
    candidate_idx: int,
    tolerance: float,
) -> bool:
    """Valida que el salto de latencia en ``candidate_idx`` se sostiene en hops
    subsiguientes.

    Criterio (TECHNICAL_SPEC.md \u00a72.3): al menos un hop subsiguiente debe
    responder con rtt >= candidate.rtt_ms - tolerance. Si TODOS los hops
    subsiguientes responden con rtt mucho menor (a nivel del salto anterior),
    se considera pico puntual y NO se considera sostenido.

    Hops subsiguientes que no responden no afectan la decision: se ignoran.
    """
    candidate = hops[candidate_idx]
    assert candidate.responded and candidate.rtt_ms is not None
    floor_ms = candidate.rtt_ms - tolerance

    for later in hops[candidate_idx + 1 :]:
        if not later.responded or later.rtt_ms is None:
            continue
        if later.rtt_ms >= floor_ms:
            return True
        # Si el hop subsiguiente esta muy por debajo del floor, este "salto"
        # no se sostuvo. Regresamos a False en cuanto encontramos un hop
        # claramente por debajo del nuevo nivel.
        return False
    # No hubo hops subsiguientes que respondan: el candidato es el final de la
    # ruta (o todos descartaron ICMP despues). Consideramos que se sostiene:
    # el salto es real (no pudo ser descartado por pico puntual).
    return True


# --- Wrappers de subprocess ---


class ProcessRunner(Protocol):
    """Contrato para ejecutar el binario `tracert`.

    Permite inyectar un mock en tests sin tocar `subprocess` real.
    Devuelve (stdout, stderr, returncode). Lanza `subprocess.TimeoutExpired`
    si expira (igual que el real).
    """

    def __call__(
        self, args: list[str], total_timeout_s: float
    ) -> tuple[str, str, int]: ...


class _DefaultProcessRunner:
    """Implementacion por defecto: wrap de subprocess.run."""

    def __call__(self, args: list[str], total_timeout_s: float) -> tuple[str, str, int]:
        proc = subprocess.run(  # noqa: S603 - args controlados internamente
            args,
            capture_output=True,
            text=True,
            timeout=total_timeout_s,
            check=False,
        )
        return (proc.stdout, proc.stderr, proc.returncode)


_default_process_runner: ProcessRunner = _DefaultProcessRunner()  # type: ignore[assignment]


# --- RealTracerouteRunner ---


class RealTracerouteRunner:
    """TracerouteRunner real via subprocess sobre `tracert` nativo de Windows.

    Detecta si esta en Windows (`tracert -d -h -w`) o POSIX (`traceroute`).
    Resuelve hostnames a IPv4 antes de ejecutar (DNS resolution inline) pero
    guarda el valor ORIGINAL del caller en el contexto del run.

    Args de construccion:
        jump_threshold_ms: umbral para deteccion del culpable (TECHNICAL_SPEC.md
            \u00a72.3); default 40 o el de settings si None.
        sustain_tolerance_ms: margen para considerar sostenido un salto; default 5.
        process_runner: inyecta un runner para tests (sin tocar subprocess real).
    """

    def __init__(
        self,
        *,
        jump_threshold_ms: float | None = None,
        sustain_tolerance_ms: float = 5.0,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        if jump_threshold_ms is None:
            # Default del settings (config/) si disponible; si no, 40ms.
            try:
                from gnd.config import get_settings

                jump_threshold_ms = float(
                    get_settings().thresholds.hop_jump_threshold_ms
                )
            except Exception:  # noqa: BLE001 - config optional en tests de network
                jump_threshold_ms = 40.0
        self._jump_threshold_ms = jump_threshold_ms
        self._sustain_tolerance_ms = sustain_tolerance_ms
        # Permite inyectar un runner para tests (sin tocar subprocess real).
        self._process_runner = process_runner or _default_process_runner

    def traceroute(
        self,
        target_ip: str,
        target_provider: str,
        max_hops: int,
        timeout_ms: int,
    ) -> TracerouteResult:
        """Implementa `Protocol TracerouteRunner.traceroute`.

        EP \u00a72.L (Liskov): signature y contrato identicos al fake.

        ``target_ip`` puede ser un hostname o IPv4. Internamente se resuelve
        a IPv4 para el sondeo. El tracert se ejecuta con ``-d`` (sin DNS
        reverse de hops) para acelerar el output. Los hops individuales no
        traen hostname (mask ``-d``), pero el ``target_ip`` del hop final es
        la IP resuelta (no el hostname del caller).

        No lanza excepciones hacia el caller (EP \u00a71.2): toda condicion de
        red se devuelve como TracerouteResult posiblemente vacio.
        """
        # Resolucion DNS inline (hostname -> IPv4) solo para el sondeo.
        resolved_ip = self._resolve_target(target_ip)
        if resolved_ip is None:
            logger.warning(
                "DNS resolution failed target=%s -> TracerouteResult vacio",
                target_ip,
            )
            return self._empty_result(target_provider)

        args = self._build_args(resolved_ip, max_hops, timeout_ms)
        # Timeout total estimado: max_hops * (3 probes * timeout_ms/1000
        # + 1.5s overhead) + margen generoso. Windows tracert default-up-to
        # 30 hops puede tomar ~45s.
        estimated_total = max_hops * (3 * max(timeout_ms / 1000.0, 1.0) + 1.5) + 10.0
        try:
            stdout, _stderr, _returncode = self._process_runner(
                args, total_timeout_s=estimated_total
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "tracert subprocess timeoutExpired target=%s (resolved=%s) args=%s",
                target_ip,
                resolved_ip,
                args,
            )
            # Tracert escribe hops incrementalmente; en timeout podemos tener
            # output parcial. El parser lo maneja: retornamos lo que se haya parseado.
            stdout = ""
        except OSError as exc:
            logger.exception(
                "tracert subprocess OSError target=%s (resolved=%s): %s",
                target_ip,
                resolved_ip,
                exc,
            )
            return self._empty_result(target_provider)

        parsed = tracert_parser.parse(stdout)
        if not parsed.hops:
            logger.warning(
                "tracert output sin hops reconocidos target=%s (resolved=%s)",
                target_ip,
                resolved_ip,
            )
            return self._empty_result(target_provider)

        return self._to_traceroute_result(parsed, target_provider)

    def _resolve_target(self, target: str) -> str | None:
        """Resuelve `target` (hostname o IPv4) a una IPv4.

        - Si ya es IPv4 (regex simple), lo devuelve tal cual.
        - Si es hostname, intenta `socket.getaddrinfo` con AF_INET.
        - Devuelve None si la resolucion falla (no lanza).
        """
        if _looks_like_ipv4(target):
            return target
        try:
            infos = socket.getaddrinfo(target, None, socket.AF_INET)
            if not infos:
                return None
            return infos[0][4][0]
        except socket.gaierror:
            return None

    def _build_args(self, target_ip: str, max_hops: int, timeout_ms: int) -> list[str]:
        if platform.system() == "Windows":
            # Windows: -d = no resolver hostname de hops; -h = max hops;
            # -w = timeout (ms).
            return [
                "tracert",
                "-d",
                "-h",
                str(max_hops),
                "-w",
                str(int(timeout_ms)),
                target_ip,
            ]
        # POSIX: `traceroute` (sin -d en algunas variantes; -m max_hops; -w wait_s).
        timeout_s = max(1, int(timeout_ms / 1000))
        return [
            "traceroute",
            "-n",  # no resolver hostname (equivalente -d de Windows)
            "-m",
            str(max_hops),
            "-w",
            str(timeout_s),
            target_ip,
        ]

    def _to_traceroute_result(
        self,
        parsed: tracert_parser.ParsedTracert,
        target_provider: str,
    ) -> TracerouteResult:
        hops_models = [
            TracerouteHop(
                hop_number=ph.hop_number,
                ip=ph.ip,
                hostname=ph.hostname,
                rtt_ms=ph.rtt_ms,
                responded=ph.responded,
            )
            for ph in parsed.hops
        ]
        culprit_idx = detect_culprit_hop(
            hops_models,
            jump_threshold_ms=self._jump_threshold_ms,
            sustain_tolerance_ms=self._sustain_tolerance_ms,
        )
        return TracerouteResult(
            target_provider=target_provider,
            hops=hops_models,
            culprit_hop_index=culprit_idx,
        )

    def _empty_result(self, target_provider: str) -> TracerouteResult:
        """TracerouteResult vacio: hops no vacio (invariante del modelo exige
        al menos 1 hop). Usamos un hop placeholder que indique "sin datos".
        """
        placeholder = TracerouteHop(
            hop_number=1,
            ip=None,
            hostname=None,
            rtt_ms=None,
            responded=False,
        )
        return TracerouteResult(
            target_provider=target_provider,
            hops=[placeholder],
            culprit_hop_index=None,
        )
