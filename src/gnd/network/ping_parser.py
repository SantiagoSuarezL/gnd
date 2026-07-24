"""Parser del output de `ping` nativo (Windows y Linux/macOS).

TECHNICAL_SPEC.md §2.1: parsear avg/min/max/jitter y packet loss desde el
output textual de `ping`. El `jitter` (mdev en Linux, no reportado en
Windows) se calcula como la desviacion estandar de los RTTs individuales
cuando no viene explicito.

Este modulo es infraestructura pura: no conoce el `Protocol PingRunner` ni
los modelos de dominio. Devuelve DTOs internos (`ParsedPing`) que
`RealPingRunner` traduce a `ProbeResult` (ver EP §2.S).
"""

import re
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedPing:
    """Resultado de parsear el output de `ping`.

    Attributes:
        rtt_ms: lista de RTTs individuales en ms (puede ser parcial).
        packet_loss_pct: porcentaje de paquetes perdidos [0, 100].
        transmitted: paquetes enviados.
        received: paquetes recibidos.
        error_letter: 'U' (host unreachable), 'G' (general failure),
            None si no aplica. Se usa para distinguir UNREACHABLE de
            TIMEOUT puro.
        summary_line: linea final de estadisticas (para diagnostico).
    """

    rtt_ms: tuple[float, ...]
    packet_loss_pct: float
    transmitted: int
    received: int
    error_letter: str | None
    summary_line: str

    @property
    def all_lost(self) -> bool:
        return self.received == 0

    def build_stats(self) -> tuple[float, float, float, float, int] | None:
        """Devuelve (avg, min, max, jitter, samples) o None si no hay RTTs."""
        if not self.rtt_ms:
            return None
        rtts = self.rtt_ms
        avg = statistics.fmean(rtts)
        # min/max explicitos para garantizar invariantes del modelo LatencyStats
        mn = min(rtts)
        mx = max(rtts)
        jitter = statistics.pstdev(rtts) if len(rtts) > 1 else 0.0
        samples = len(rtts)
        return (avg, mn, mx, jitter, samples)


# --- Patrones regex ---
# Linux: "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=14.2 ms"
_LINUX_REPLY = re.compile(r"time=([0-9.]+)\s*ms", re.IGNORECASE)
# Windows: "Reply from 8.8.8.8: bytes=32 time=12ms TTL=117"
_WINDOWS_REPLY = re.compile(
    r"Reply from .*:\s+bytes=\d+\s+time=([0-9.]+)\s*ms\s+TTL=\d+", re.IGNORECASE
)
_WINDOWS_REPLY_ZERO = re.compile(
    r"Reply from .*:\s+bytes=\d+\s+time<([0-9.]+)\s*ms\s+TTL=\d+", re.IGNORECASE
)

# --- Estadisticas Linux ---
_LINUX_STATS = re.compile(
    r"(\d+)\s+packets transmitted,\s+(\d+)\s+received"
    r"(?:,\s+\+(\d+)\s+errors)?"
    r",\s+([0-9.]+)%\s+packet loss"
)
_LINUX_RTT_SUMMARY = re.compile(
    r"rtt\s+min/avg/max/mdev\s*=\s*" r"([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms"
)

# --- Estadisticas Windows ---
_WIN_STATS = re.compile(
    r"Packets:\s+Sent\s*=\s*(\d+),\s+Received\s*=\s*(\d+),\s+Lost\s*=\s*(\d+)"
    r"\s+\(([0-9.]+)%\s+loss\)",
    re.IGNORECASE,
)
_WIN_RTT = re.compile(
    r"Minimum\s*=\s*([0-9]+)ms,\s+Maximum\s*=\s*([0-9]+)ms,\s+Average\s*=\s*([0-9]+)ms",
    re.IGNORECASE,
)

# --- Errores ---
_WIN_HOST_UNREACH = re.compile(r"Destination host unreachable", re.IGNORECASE)
_WIN_GENERAL_FAILURE = re.compile(r"transmit failed\.\s*General failure", re.IGNORECASE)
_LINUX_HOST_UNREACH = re.compile(r"Destination Host Unreachable", re.IGNORECASE)
_LINUX_NET_UNREACH = re.compile(r"Network is unreachable", re.IGNORECASE)
_WIN_TTL_EXPIRED = re.compile(r"TTL expired in transit", re.IGNORECASE)


def parse(output: str) -> ParsedPing:
    """Parsea el output completo de `ping` y devuelve un ParsedPing.

    Detecta automaticamente el formato (Windows vs Linux) y extrae:
    - RTTs individuales de cada reply.
    - packet_loss_pct, transmitted, received.
    - error_letter: None | 'U' (host unreachable) | 'G' (general failure).
      Se usa en RealPingRunner para distinguir UNREACHABLE de TIMEOUT puro
      cuando received==0 (TECHNICAL_SPEC.md §7).

    No lanza excepciones por input malformado: devuelve un ParsedPing con
    received=0 / all_lost=True para que el caller decida el outcome.
    """
    lines = output.splitlines()
    rtts: list[float] = []
    error_letter: str | None = None
    transmitted = 0
    received = 0
    loss_pct = 100.0
    summary_line = ""

    for line in lineiters_no_blank(lines):
        low = line.strip()

        # RTTs individuales: probar ambos formatos
        m = _WINDOWS_REPLY.search(low)
        if m:
            rtts.append(float(m.group(1)))
            continue
        m = _WINDOWS_REPLY_ZERO.search(low)
        if m:
            rtts.append(float(m.group(1)))
            continue
        m = _LINUX_REPLY.search(low)
        if m:
            rtts.append(float(m.group(1)))
            continue

        # Estadisticas: Windows primero (mas especifico)
        m = _WIN_STATS.search(low)
        if m:
            transmitted = int(m.group(1))
            received = int(m.group(2))
            loss_pct = float(m.group(4))
            summary_line = low
            continue

        m = _LINUX_STATS.search(low)
        if m:
            transmitted = int(m.group(1))
            received = int(m.group(2))
            loss_pct = float(m.group(4))
            summary_line = low
            continue

        # Errores explicitos (marcan UNREACHABLE vs TIMEOUT puro)
        if _WIN_HOST_UNREACH.search(low) or _LINUX_HOST_UNREACH.search(low):
            error_letter = "U"
            continue
        if _WIN_GENERAL_FAILURE.search(low) or _LINUX_NET_UNREACH.search(low):
            error_letter = "G"
            continue
        if _WIN_TTL_EXPIRED.search(low):
            error_letter = "U"
            continue

        # RTT summary Windows: complementa avg/min/max si hubo replies
        m = _WIN_RTT.search(low)
        if m:
            summary_line = low
            continue
        m = _LINUX_RTT_SUMMARY.search(low)
        if m:
            summary_line = low
            continue

    # Si el bloque de stats no se encontro pero hubo replies, inferir
    if transmitted == 0 and rtts:
        transmitted = len(rtts)
        received = len(rtts)
        loss_pct = 0.0

    # Siempre que received==0 y no se encontro error_letter, error_letter queda None
    # (eso significa "timeout puro" -> el caller debera usar fallback TCP).
    return ParsedPing(
        rtt_ms=tuple(rtts),
        packet_loss_pct=loss_pct,
        transmitted=transmitted,
        received=received,
        error_letter=error_letter,
        summary_line=summary_line,
    )


def lineiters_no_blank(lines: list[str]) -> list[str]:
    """Filtra lineas vacias (helper)."""
    return [ln for ln in lines if ln.strip()]
