"""Implementacion real de `Protocol PingRunner` (ARCHITECTURE.md §2).

Ejecuta el `ping` nativo del OS via `subprocess` y parsea el output con
`network/ping_parser`. Si ICMP reporta 100% packet loss, aplica fallback
TCP SYN (`network/tcp_syn_probe`) para distinguir:

- FILTERED  (TECHNICAL_SPEC.md §7): ICMP bloqueado pero TCP 443 responde.
            Se excluye del score/baseline, no penaliza.
- UNREACHABLE: ICMP blocked + TCP unreachable (sin ruta) o general failure.
- TIMEOUT:  ICMP blocked + TCP timeout (host probablemente caido).

No lanza excepciones hacia el caller: toda condicion de red se devuelve
como ProbeResult con el outcome adecuado (EP §1.2).
"""

import logging
import platform
import subprocess
from datetime import datetime
from typing import Protocol

from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.network import ping_parser, tcp_syn_probe

logger = logging.getLogger(__name__)


class RealPingRunner:
    """PingRunner real via subprocess sobre `ping` nativo del OS.

    Detecta si esta en Windows (`ping -n -w`) o POSIX (`ping -c -W`).
    Si cached parser no logra parsear el output, degrada a TIMEOUT sin
    crashear (EP §1.2). Tras 100% ICMP loss ejecuta el fallback TCP SYN
    a puerto `fallback_port` (default 443).
    """

    def __init__(
        self,
        *,
        fallback_port: int = 443,
        tcp_syn_timeout_s: float = 1.0,
        process_runner: "ProcessRunner | None" = None,
    ) -> None:
        self._fallback_port = fallback_port
        self._tcp_syn_timeout_s = tcp_syn_timeout_s
        # Permite inyectar un runner para tests (sin tocar subprocess real).
        self._process_runner = process_runner or _default_process_runner

    def ping(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        timeout_ms: int,
    ) -> ProbeResult:
        """Implementa `Protocol PingRunner.ping`.

        EP §2.L (Liskov): signature y contrato identicos al fake.
        """
        args = self._build_args(target_ip, count, timeout_ms)
        try:
            stdout, stderr, returncode = self._process_runner(args, timeout_ms)
        except subprocess.TimeoutExpired:
            logger.warning(
                "ping subprocess timeoutExpired target=%s args=%s",
                target_ip,
                args,
            )
            return self._no_icmp_result(
                target_ip, target_name, provider, count, ProbeOutcomeKind.TIMEOUT
            )
        except OSError as exc:
            # ping binary no encontrado u otro error de SO.
            logger.exception("ping subprocess OSError target=%s: %s", target_ip, exc)
            return self._no_icmp_result(
                target_ip,
                target_name,
                provider,
                count,
                ProbeOutcomeKind.UNREACHABLE,
            )

        parsed = ping_parser.parse(stdout + "\n" + stderr)
        return self._to_probe_result(
            target_ip,
            target_name,
            provider,
            count,
            parsed,
            returncode,
        )

    # --- helpers privados ---

    def _build_args(self, target_ip: str, count: int, timeout_ms: int) -> list[str]:
        if platform.system() == "Windows":
            # Windows: timeout en ms.
            return [
                "ping",
                "-n",
                str(count),
                "-w",
                str(int(timeout_ms)),
                target_ip,
            ]
        # POSIX: timeout en segundos (floor de ms/1000, minimo 1).
        timeout_s = max(1, int(timeout_ms / 1000))
        return [
            "ping",
            "-c",
            str(count),
            "-W",
            str(timeout_s),
            target_ip,
        ]

    def _to_probe_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        parsed: ping_parser.ParsedPing,
        returncode: int,
    ) -> ProbeResult:
        # Caso feliz: al menos un reply.
        if parsed.received > 0 and parsed.rtt_ms:
            return self._success_result(target_ip, target_name, provider, count, parsed)

        # 100% packet loss: aplicar fallback TCP SYN.
        logger.info(
            "ICMP 100%% loss target=%s, intentando fallback TCP SYN :%d",
            target_ip,
            self._fallback_port,
        )
        return self._fallback_result(
            target_ip, target_name, provider, count, parsed, returncode
        )

    def _success_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        parsed: ping_parser.ParsedPing,
    ) -> ProbeResult:
        from gnd.models.latency_stats import LatencyStats

        stats_tuple = parsed.build_stats()
        if stats_tuple is None:
            # Solo posible si received > 0 pero no se parseo ningun RTT
            # (output malformado). Degradar a TIMEOUT.
            logger.warning(
                "received>0 pero sin RTTs parseados target=%s summary=%s",
                target_ip,
                parsed.summary_line,
            )
            return self._no_icmp_result(
                target_ip, target_name, provider, count, ProbeOutcomeKind.TIMEOUT
            )
        avg, mn, mx, jitter, samples = stats_tuple
        return ProbeResult(
            target_name=target_name,
            target_ip=target_ip,
            provider=provider,
            outcome=ProbeOutcomeKind.SUCCESS,
            stats=LatencyStats(
                avg_ms=avg,
                min_ms=mn,
                max_ms=mx,
                jitter_ms=jitter,
                packet_loss_pct=parsed.packet_loss_pct,
                samples=samples,
            ),
            timestamp=datetime.now(),
        )

    def _fallback_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        parsed: ping_parser.ParsedPing,
        returncode: int,
    ) -> ProbeResult:
        tcp_outcome = tcp_syn_probe.probe(
            target_ip,
            port=self._fallback_port,
            timeout_s=self._tcp_syn_timeout_s,
        )
        if tcp_syn_probe.is_host_alive(tcp_outcome):
            # Host vivo bloqueando ICMP -> FILTERED.
            logger.info(
                "FILTERED target=%s (TCP SYN: %s)",
                target_ip,
                tcp_outcome.detail,
            )
            return self._no_icmp_result(
                target_ip, target_name, provider, count, ProbeOutcomeKind.FILTERED
            )

        # TCP tambien fallo: distinguir UNREACHABLE vs TIMEOUT.
        if tcp_outcome.result is tcp_syn_probe.TcpSynResult.NETWORK_UNREACHABLE:
            kind = ProbeOutcomeKind.UNREACHABLE
        elif parsed.error_letter == "G":
            # Windows "General failure" sin respuesta TCP -> UNREACHABLE.
            kind = ProbeOutcomeKind.UNREACHABLE
        elif parsed.error_letter == "U":
            # "Destination host unreachable" ICMP explicito del gateway.
            kind = ProbeOutcomeKind.UNREACHABLE
        else:
            # Sin error explicito: timeout puro.
            kind = ProbeOutcomeKind.TIMEOUT
        logger.info(
            "%s target=%s (TCP SYN: %s, ICMP err_letter=%s, rc=%d)",
            kind.name,
            target_ip,
            tcp_outcome.detail,
            parsed.error_letter,
            returncode,
        )
        return self._no_icmp_result(target_ip, target_name, provider, count, kind)

    def _no_icmp_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        kind: ProbeOutcomeKind,
    ) -> ProbeResult:
        return ProbeResult(
            target_name=target_name,
            target_ip=target_ip,
            provider=provider,
            outcome=kind,
            stats=None,
            timestamp=datetime.now(),
        )


# --- Abstraccion del subprocess para tests ---
class ProcessRunner(Protocol):
    """Contrato para ejecutar el binario `ping`.

    Permite inyectar un mock en tests sin tocar `subprocess` real.
    Devuelve (stdout, stderr, returncode). Lanza `subprocess.TimeoutExpired`
    si expira (igual que el real).
    """

    def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]: ...


class _DefaultProcessRunner:
    """Implementacion por defecto: wrap de subprocess.run."""

    def __call__(self, args: list[str], timeout_ms: int) -> tuple[str, str, int]:
        # timeout en segundos; sumamos un margen sobre lo que pidio el ping.
        total_timeout_s = max(2.0, (timeout_ms / 1000.0) + 2.0)
        proc = subprocess.run(  # noqa: S603 - args controlados internamente
            args,
            capture_output=True,
            text=True,
            timeout=total_timeout_s,
            check=False,
        )
        return (proc.stdout, proc.stderr, proc.returncode)


_default_process_runner: ProcessRunner = _DefaultProcessRunner()  # type: ignore[assignment]
