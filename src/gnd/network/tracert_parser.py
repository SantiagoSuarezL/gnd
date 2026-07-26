"""Parser del output de `tracert` nativo (Windows, EN y ES).

TECHNICAL_SPEC.md \u00a72.3: el output de `tracert` se parsea a un DTO interno
`ParsedTracert` con la lista de `ParsedHop`. La deteccion del `culprit_hop_index`
vive en `real_traceroute_runner` (este modulo es solo parseo, sin logica
de negocio).

Patrones soportados:

    Windows EN (default): `` 1     1 ms     1 ms     1 ms  192.168.20.1``
    Windows ES:            `` 1     1 ms     1 ms     1 ms  192.168.20.1``
    Hop sin respuesta EN:  `` 5     *        *        *     Request timed out.``
    Hop sin respuesta ES:  `` 5     *        *        *     Tiempo de espera
                           agotado para esta solicitud.``

Cuando `tracert` corre sin `-d`, los hops pueden traer hostname al lado de
la IP: `` 1     1 ms ...  router.local [192.168.20.1]``. El parser extrae
hostname y la IP dentro de corchetes (o la IP literal si no hay corchetes).

Este modulo es infraestructura pura: no conoce `Protocol TracerouteRunner`
ni modelos de dominio. Regla de Oro 2.2: parser soporta EN + ES aunque el
target sea Windows (el OS del dev puede tener cualquiera como idioma).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedHop:
    """Un hop individual parseado del output de `tracert`.

    Attributes:
        hop_number: numero de hop (1-indexed).
        ip: IPv4 del hop, o None si no respondio.
        hostname: hostname resuelto, o None (cuando tracert se corre con -d
            o el hop no respondio).
        rtt_ms: RTT promedio de las 3 muestras del hop, o None si el hop no
            respondio (todas las muestras fueron ``*``).
        responded: True si al menos una muestra del hop respondio. Hops que
            no responden NO son error (TECHNICAL_SPEC.md \u00a72.3).
    """

    hop_number: int
    ip: str | None
    hostname: str | None
    rtt_ms: float | None
    responded: bool

    def __post_init__(self) -> None:
        if self.hop_number < 1:
            raise ValueError(f"hop_number debe ser >= 1, fue {self.hop_number}")
        if self.responded and self.rtt_ms is None:
            raise ValueError(
                f"rtt_ms no puede ser None si responded=True (hop={self.hop_number})"
            )
        if self.rtt_ms is not None and self.rtt_ms < 0.0:
            raise ValueError(f"rtt_ms debe ser >= 0, fue {self.rtt_ms}")


@dataclass(frozen=True)
class ParsedTracert:
    """Resultado de parsear el output completo de `tracert`.

    `hops` esta en orden (hop_number ascendente). No incluye lineas que no
    son hops (cabecera, ``Trace complete.`` / ``Traza completa.``).
    """

    hops: tuple[ParsedHop, ...]
    target_ip: str | None
    target_hostname: str | None


# --- Patrones regex ---

# Cabecera en ingles:
#   "Tracing route to 8.8.8.8 over a maximum of 10 hops:"
# o con hostname:
#   "Tracing route to dns.google [8.8.8.8] over a maximum of 30 hops:"
_HEADER_EN = re.compile(
    r"Tracing route to\s+(?:(?P<host_en>[^\[\]\s]+)\s+\[(?P<ip_en>[^\]]+)\]"
    r"|(?P<ip_en_only>[^\s]+))"
    r"\s+over a maximum of\s+\d+\s+hops:",
    re.IGNORECASE,
)

# Cabecera en espanol:
#   "Traza a 8.8.8.8 sobre caminos de 10 saltos como maximo."
#   "Traza a la direccion auth.riotgames.com.cdn.cloudflare.net [104.16.119.50]"
#   "sobre un maximo de 12 saltos:"
# Nota: el mensaje puede tener "la direccion" entre "Traza a" y el target,
# o ser directo "Traza a <ip/hostname>". El target puede ser IP literal o
# "hostname [IP]". El target va hasta la palabra "sobre" (que aparece en
# ambos formatos).
_HEADER_ES = re.compile(
    r"Traza a(?:\s+la\s+direcci\u00f3n)?\s+(?P<body>[\s\S]+?)\s+sobre\b",
    re.IGNORECASE,
)

# Linea de hop en formato "-d" (sin hostname):
#   "  1     1 ms     1 ms     1 ms  192.168.20.1"
# Cada probe puede ser "<X> ms" o "<X>ms" o "<1 ms" (RTT muy bajo en Windows EN).
# En Espanol el formato es identico ("ms").
_HOP_LINE = re.compile(r"^\s*(?P<hop>\d+)\s+(?P<rest>.+)$")

# Probe individual: "<1 ms", "1 ms", "90ms" o "*"
_PROBE_MS = re.compile(r"(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)

# Fin: "Trace complete." o "Traza completa."
_TRACE_COMPLETE_EN = re.compile(r"Trace complete\.", re.IGNORECASE)
_TRACE_COMPLETE_ES = re.compile(r"Traza completa\.", re.IGNORECASE)

# Mensaje de "Request timed out." / "Tiempo de espera agotado para esta solicitud."
_TIMEOUT_MSG_EN = re.compile(r"Request timed out\.", re.IGNORECASE)
_TIMEOUT_MSG_ES = re.compile(
    r"Tiempo de espera agotado para esta solicitud\.", re.IGNORECASE
)


def parse(output: str) -> ParsedTracert:
    """Parsea el output completo de `tracert` (Windows, EN o ES).

    No lanza excepciones por input malformado: si no se reconocen hops,
    devuelve un ``ParsedTracert`` con ``hops=()`` (el caller decide que hacer
    con un `tracert` que no produjo datos). EP \u00a71.2: nunca propagar excepciones
    de red hacia arriba.

    El parser NO calcula `culprit_hop_index` \u2014 eso es logica de negocio que
    vive en `real_traceroute_runner.detect_culprit_hop` (separacion SRP).
    """
    # Cabecera: el header puede caer en una sola linea o continuar en la
    # siguiente (caso ES "Traza a la direccion X" / "sobre un maximo ...").
    # Procesamos el header sobre el output completo con regex multiline.
    target_ip: str | None = None
    target_hostname: str | None = None
    m = _HEADER_EN.search(output)
    if m:
        target_hostname = m.group("host_en")
        target_ip = m.group("ip_en") or m.group("ip_en_only")
    if target_ip is None:
        m = _HEADER_ES.search(output)
        if m:
            # Extraer IP/hostname del body capturado.
            ip, host = _extract_ip_hostname(m.group("body"))
            target_ip = ip
            target_hostname = host

    lines = output.splitlines()
    hops: list[ParsedHop] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Cabecera ya procesada arriba; ignoramos todas las lineas que matcheen
        # (en ES pueden ser 2 lineas distintas).
        if _HEADER_EN.search(stripped) or _HEADER_ES.search(stripped):
            continue
        # Si matchea el sufijo ES de la cabecera "sobre un maximo ...", ignorarlo.
        if re.search(r"\bsobre\s+(?:un|caminos de)\b", stripped, re.IGNORECASE):
            continue

        # Fin de traza (informativo, no aporta hops).
        if _TRACE_COMPLETE_EN.search(stripped) or _TRACE_COMPLETE_ES.search(stripped):
            continue

        # Linea de hop.
        hop = _parse_hop_line(stripped)
        if hop is not None:
            hops.append(hop)

    return ParsedTracert(
        hops=tuple(hops),
        target_ip=target_ip,
        target_hostname=target_hostname,
    )


def _parse_hop_line(line: str) -> ParsedHop | None:
    """Intenta parsear una linea como hop de `tracert`.

    Devuelve None si la linea no matchea el patron de hop (no es un hop).
    Si la linea tiene formato de hop pero alguna parte no se entiende,
    devuelve un hop con ``responded=False`` (conservador: no crashea).
    """
    m = _HOP_LINE.match(line)
    if m is None:
        return None

    hop_number = int(m.group("hop"))
    rest: str = m.group("rest")

    # Caso tipico: 3 probes luego un target.
    # " 1     1 ms     1 ms     1 ms  192.168.20.1"
    # " 5     *        *        *     Request timed out."
    probes_rtt: list[float] = []

    # Tokenizar el resto: cada token es o bien "<num> ms" / "<num>ms" / "*",
    # seguido del IP/hostname del hop.
    # Estrategia: buscar el primer (ip o hostname) sacando los tokens de probe.
    # Mas facil: buscar TODOS los probes con regex sobre el ``rest``.
    probe_matches = list(_PROBE_MS.finditer(rest))
    star_count = rest.count("*")

    if probe_matches:
        for pm in probe_matches:
            probes_rtt.append(float(pm.group(1)))

    if probes_rtt:
        # Al menos un probe respondio.
        # El target va despues del ultimo probe match en el ``rest``.
        last_end = probe_matches[-1].end()
        target_part = rest[last_end:].strip()
        ip, hostname = _extract_ip_hostname(target_part)
        avg_rtt = sum(probes_rtt) / len(probes_rtt)
        return ParsedHop(
            hop_number=hop_number,
            ip=ip,
            hostname=hostname,
            rtt_ms=avg_rtt,
            responded=True,
        )

    # Sin probes numericos: \u00bftodos son ``*``?
    # Si es una linea commenzando con "<n>     *        *        *     <timeout msg>"
    if star_count >= 1:
        # Verificamos que todos los probes sean ``*`` (no haya residuo parseado).
        # Tomamos el target como None (no respondio).
        return ParsedHop(
            hop_number=hop_number,
            ip=None,
            hostname=None,
            rtt_ms=None,
            responded=False,
        )
    # Linea con formato de hop pero sin probes reconocidos: asumimos no respondio
    # (no crash). Esto cubre formatos exoticos sin romper el parser.
    # Marcamos responded=False con todos los campos None.
    return ParsedHop(
        hop_number=hop_number,
        ip=None,
        hostname=None,
        rtt_ms=None,
        responded=False,
    )


def _extract_ip_hostname(target_part: str) -> tuple[str | None, str | None]:
    """Extrae IP y hostname de la parte final de la linea de hop.

    Formats posibles:
        "192.168.20.1"                          -> ("192.168.20.1", None)
        "router.local [192.168.20.1]"            -> ("192.168.20.1", "router.local")
        "dns.google [8.8.8.8]"                   -> ("8.8.8.8", "dns.google")
        ("auth.riotgames.com.cdn.cloudflare.net "
         "[104.16.119.50]") -> ("104.16.119.50",
         "auth.riotgames.com.cdn.cloudflare.net")
    """
    target_part = target_part.strip()
    if not target_part:
        return (None, None)

    # Caso con hostname: "algo [IP]"
    m = re.match(r"^(?P<host>[^\[\]]+)\s+\[(?P<ip>[^\]]+)\]", target_part)
    if m:
        return (m.group("ip").strip(), m.group("host").strip())

    # Solo IP (no hay corchetes).
    return (target_part, None)
