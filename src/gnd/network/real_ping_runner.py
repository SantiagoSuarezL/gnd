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
import re
import socket
import subprocess
from datetime import datetime
from typing import Protocol

from gnd.models.probe_result import ProbeOutcomeKind, ProbeResult
from gnd.network import ping_parser, tcp_syn_probe
from gnd.network._subprocess_helpers import subprocess_kwargs

logger = logging.getLogger(__name__)


# Regex para detectar si el target ya es una IPv4 (simple check).
_IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$"
)


def _looks_like_ipv4(target: str) -> bool:
    """True si `target` parece una IPv4 valida (no hostname)."""
    return bool(_IPV4_PATTERN.match(target))


def _looks_like_ipv6(target: str) -> bool:
    """Heur: True si `target` parece una IPv6 literal (contiene ':').

    No valida formato completo — solo heurística para evitar DNS sobre IP.
    """
    return ":" in target and "." not in target


class RealPingRunner:
    """PingRunner real via subprocess sobre `ping` nativo del OS.

    Detecta si esta en Windows (`ping -n -w`) o POSIX (`ping -c -W`).
    Resuelve hostnames a IPv4 antes de pinguear (DNS resolution inline).
    El valor ORIGINAL de `target_ip` (hostname o IP) se guarda en
    `ProbeResult.target_ip` — la IP resuelta solo se usa para el sondeo
    de red. Esto evita contaminar el baseline historico si el DNS de
    un CDN (Cloudflare/Akamai) rota entre corridas.

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
        *,
        family: str = "ipv4",
    ) -> ProbeResult:
        """Implementa `Protocol PingRunner.ping`.

        EP §2.L (Liskov): signature y contrato identicos al fake.

        `target_ip` puede ser un hostname o IP. Internamente se resuelve
        a la familia solicitada (AF_INET / AF_INET6) para el sondeo,
        pero `ProbeResult.target_ip` guarda el valor ORIGINAL del caller.
        Esto evita contaminar el baseline historico si el DNS de un CDN
        rota de IP entre corridas. La IP resuelta del momento queda en
        logs para debug.

        Fase 12a.4: `family='ipv4'|'ipv6'`. `family=None` se infiere de
        `target_ip` (`:` -> ipv6, si no ipv4) para usos ad-hoc.
        """
        # Inferir family si es None
        if family not in ("ipv4", "ipv6"):
            raise ValueError(f"family debe ser 'ipv4' o 'ipv6', no {family!r}")
        # Resolucion DNS inline (hostname -> IP de la familia pedida) solo
        # para el sondeo. `resolved_ip` se devuelve con la IP ya en su
        # forma final (v4 o v6).
        resolved_ip = self._resolve_target(target_ip, family=family)
        if resolved_ip is None:
            logger.warning(
                "DNS resolution failed target=%s family=%s -> UNREACHABLE",
                target_ip,
                family,
                extra={"provider": provider, "event": "ping.dns_failed"},
            )
            return self._no_icmp_result(
                target_ip,
                target_name,
                provider,
                count,
                ProbeOutcomeKind.UNREACHABLE,
                family=family,
            )

        # Ejecutar ping contra la IP resuelta.
        args = self._build_args(resolved_ip, count, timeout_ms, family=family)
        try:
            stdout, stderr, returncode = self._process_runner(args, timeout_ms)
        except subprocess.TimeoutExpired:
            logger.warning(
                "ping subprocess timeoutExpired target=%s (resolved=%s) args=%s",
                target_ip,
                resolved_ip,
                args,
                extra={"provider": provider, "event": "ping.timeout"},
            )
            return self._no_icmp_result(
                target_ip,
                target_name,
                provider,
                count,
                ProbeOutcomeKind.TIMEOUT,
                family=family,
            )
        except OSError as exc:
            logger.exception(
                "ping subprocess OSError target=%s (resolved=%s): %s",
                target_ip,
                resolved_ip,
                exc,
                extra={"provider": provider, "event": "ping.oserror"},
            )
            return self._no_icmp_result(
                target_ip,
                target_name,
                provider,
                count,
                ProbeOutcomeKind.UNREACHABLE,
                family=family,
            )

        parsed = ping_parser.parse(stdout + "\n" + stderr)
        return self._to_probe_result(
            target_ip,  # valor original del caller (hostname o IP)
            target_name,
            provider,
            count,
            parsed,
            returncode,
            family=family,
        )

    # --- helpers privados ---

    def _resolve_target(self, target: str, family: str = "ipv4") -> str | None:
        """Resuelve `target` (hostname o IP) a una IP de la familia pedida.

        - Si ya es IP (v4 o v6), lo devuelve tal cual.
        - Si es hostname, intenta `socket.getaddrinfo` con la familia.
        - Devuelve None si la resolucion falla (no lanza).
        """
        if family not in ("ipv4", "ipv6"):
            raise ValueError(f"family debe ser 'ipv4' o 'ipv6', no {family!r}")
        # Detectar si target ya es una IP literal (IPv4 o IPv6).
        # IPv6 tiene ':' — IPv4 tiene 4 octetos con puntos.
        if _looks_like_ipv4(target) or _looks_like_ipv6(target):
            return target
        sock_family = socket.AF_INET if family == "ipv4" else socket.AF_INET6
        try:
            infos = socket.getaddrinfo(target, None, sock_family)
            if not infos:
                return None
            return infos[0][4][0]  # sockaddr[0] = IP
        except socket.gaierror:
            return None

    def _build_args(
        self,
        target_ip: str,
        count: int,
        timeout_ms: int,
        family: str = "ipv4",
    ) -> list[str]:
        if platform.system() == "Windows":
            # Windows: ping -6 fuerza IPv6, ping -4 fuerza IPv4.
            # Default (sin flag) usa la familia de target_ip.
            args = ["ping"]
            if family == "ipv6":
                args.append("-6")
            elif family == "ipv4":
                args.append("-4")
            args.extend(["-n", str(count), "-w", str(int(timeout_ms)), target_ip])
            return args
        # POSIX: ping6 para IPv6, ping para IPv4.
        timeout_s = max(1, int(timeout_ms / 1000))
        if family == "ipv6":
            return ["ping6", "-c", str(count), "-W", str(timeout_s), target_ip]
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
        family: str = "ipv4",
    ) -> ProbeResult:
        # Caso feliz: al menos un reply.
        if parsed.received > 0 and parsed.rtt_ms:
            return self._success_result(
                target_ip, target_name, provider, count, parsed, family=family
            )

        # 100% packet loss: aplicar fallback TCP SYN.
        logger.info(
            "ICMP 100%% loss target=%s, intentando fallback TCP SYN :%d",
            target_ip,
            self._fallback_port,
            extra={"provider": provider, "event": "ping.fallback_tcp_syn"},
        )
        return self._fallback_result(
            target_ip, target_name, provider, count, parsed, returncode, family=family
        )

    def _success_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        parsed: ping_parser.ParsedPing,
        family: str = "ipv4",
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
                extra={"provider": provider, "event": "ping.no_rtts_parsed"},
            )
            return self._no_icmp_result(
                target_ip,
                target_name,
                provider,
                count,
                ProbeOutcomeKind.TIMEOUT,
                family=family,
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
            family=family,
        )

    def _fallback_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        parsed: ping_parser.ParsedPing,
        returncode: int,
        family: str = "ipv4",
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
                extra={"provider": provider, "event": "ping.filtered"},
            )
            return self._no_icmp_result(
                target_ip,
                target_name,
                provider,
                count,
                ProbeOutcomeKind.FILTERED,
                family=family,
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
            extra={
                "provider": provider,
                "event": "ping.fallback_outcome",
                "outcome": kind.name,
            },
        )
        return self._no_icmp_result(
            target_ip, target_name, provider, count, kind, family=family
        )

    def _no_icmp_result(
        self,
        target_ip: str,
        target_name: str,
        provider: str,
        count: int,
        kind: ProbeOutcomeKind,
        family: str = "ipv4",
    ) -> ProbeResult:
        return ProbeResult(
            target_name=target_name,
            target_ip=target_ip,
            provider=provider,
            outcome=kind,
            stats=None,
            timestamp=datetime.now(),
            family=family,
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
        # Calculamos timeout total del subprocess con margen generoso.
        # Windows: ping -n <count> -w <ms> usa ~1s intervalo entre pings.
        # Total estimado = (count - 1) * 1s + timeout_ms/1000 + margen.
        # Linux: ping -c <count> -W <s> usa intervalo 1s por defecto.
        is_windows = platform.system() == "Windows"
        if is_windows and len(args) >= 3 and args[0].lower() == "ping" and "-n" in args:
            try:
                count_idx = args.index("-n") + 1
                count = int(args[count_idx])
            except (ValueError, IndexError):
                count = 4  # fallback conservador
        else:
            # POSIX o caso por defecto
            count = 4

        interval_s = 1.0  # intervalo por defecto entre pings
        wait_per_ping_s = timeout_ms / 1000.0
        estimated_total = (count - 1) * interval_s + wait_per_ping_s + 3.0
        total_timeout_s = max(5.0, estimated_total)

        proc = subprocess.run(  # noqa: S603 - args controlados internamente
            args,
            capture_output=True,
            text=True,
            timeout=total_timeout_s,
            check=False,
            **subprocess_kwargs(),
        )
        return (proc.stdout, proc.stderr, proc.returncode)


_default_process_runner: ProcessRunner = _DefaultProcessRunner()  # type: ignore[assignment]
