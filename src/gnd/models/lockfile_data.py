"""Value Object ``LockfileData`` — parseo del lockfile del cliente de LoL.

Fase 14.0a. TECHNICAL_SPEC.md §2.2. El cliente de League
(``LeagueClientUx.exe``) escribe un archivo ``lockfile`` en el directorio
de instalación mientras está corriendo; se borra al cerrar. Formato: 5
campos separados por ``:``::

    LeagueClient:PID:PORT:PASSWORD:PROTOCOL

Ejemplo real::

    LeagueClient:4242:51234:abc123def456:remoting-auth-token

El adapter ``network/lockfile_discovery.py`` lee el archivo crudo y
construye este VO. El VO valida el formato (5 campos, puerto en rango,
protocolo reconocido) y expone los 3 campos relevantes para autenticar
contra la LCU API local: ``host`` (siempre ``127.0.0.1``), ``port`` y
``password`` (auth basic ``riot:PASSWORD``).

Modelo de dominio inmutable (Protocolo 5): no depende de networking ni
de filesystem — solo validación de string parseado. El adapter real
hace el IO; el VO vive en ``models/`` y puede round-trip en
``domain/fakes/`` sin tocar disco.
"""

from __future__ import annotations

from dataclasses import dataclass

# Protocolos válidos vistos en lockfiles reales de LoL. ``remoting-auth-token``
# es el default histórico; ``ssl`` aparece en instalaciones con TLS local.
# Cualquier otro valor se rechaza con ValueError — el caller debe decidir
# si ignorar (lockfile de un cliente nuevo/cambiado) o alertar.
_VALID_PROTOCOLS: frozenset[str] = frozenset({"remoting-auth-token", "ssl"})

# Cantidad esperada de campos separados por ':' en un lockfile válido.
# Documentado en la comunidad (Riot no publica spec oficial).
_LOCKFILE_FIELD_COUNT: int = 5


@dataclass(frozen=True)
class LockfileData:
    """Credenciales parseadas del lockfile del cliente de LoL.

    Atributos:
        process_name: primer campo (ej. ``"LeagueClient"``). Se valida
            no vacío — no se hardcodea ``"LeagueClient"`` porque Riot
            podría cambiar el nombre del proceso Ux en el futuro; el VO
            acepta cualquier string no vacío y el caller decide si
            ignorar según el nombre.
        pid: process id del cliente (campo 2). Entero positivo.
        port: puerto de la LCU API local (campo 3). Entero [1, 65535].
        password: token de auth (campo 4). No vacío. Se usa como
            password de Basic auth ``riot:PASSWORD``.
        protocol: protocolo del lockfile (campo 5). Debe ser uno de
            ``_VALID_PROTOCOLS`` — rechaza formatos desconocidos para
            que el caller no intente autenticar contra algo inesperado.

    El host es siempre ``127.0.0.1`` (la LCU escucha solo en localhost) —
    no se modela como campo porque sería siempre el mismo valor. El
    adapter lo hardcodea al construir la URL.

    Invariante: ningún campo puede ser degenerado (process_name vacío,
    pid<=0, port fuera de rango, password vacío, protocol desconocido).
    """

    process_name: str
    pid: int
    port: int
    password: str
    protocol: str

    def __post_init__(self) -> None:
        if not self.process_name:
            raise ValueError("process_name no puede ser vacío")
        if self.pid <= 0:
            raise ValueError(f"pid debe ser positivo, fue {self.pid}")
        if not (1 <= self.port <= 65535):
            raise ValueError(f"port debe estar en [1, 65535], fue {self.port}")
        if not self.password:
            raise ValueError("password no puede ser vacío")
        if self.protocol not in _VALID_PROTOCOLS:
            raise ValueError(
                f"protocol debe ser uno de {sorted(_VALID_PROTOCOLS)!r}, "
                f"fue {self.protocol!r}"
            )

    @classmethod
    def parse(cls, raw: str) -> LockfileData:
        """Parsea el contenido crudo del lockfile.

        Acepta el string tal cual sale del filesystem (sin trailing
        newline — el caller debe ``.strip()`` antes). Devuelve
        ``LockfileData`` o levanta ``ValueError`` con mensaje claro
        si el formato no es el esperado.

        Separador entre campos: ``:``. Cantidad exacta:
        ``_LOCKFILE_FIELD_COUNT`` (5). Cualquier otra cantidad rechaza.

        Los campos numéricos (pid, port) se parsean con ``int()`` —
        ``ValueError`` estándar de Python si no son números. El mensaje
        final identifica qué campo está mal para el log del caller.
        """
        parts = raw.split(":")
        if len(parts) != _LOCKFILE_FIELD_COUNT:
            raise ValueError(
                f"lockfile con {len(parts)} campos, se esperaban "
                f"{_LOCKFILE_FIELD_COUNT} — formato desconocido"
            )
        process_name, pid_raw, port_raw, password, protocol = parts
        try:
            pid = int(pid_raw)
        except ValueError as exc:
            raise ValueError(f"pid no es entero: {pid_raw!r}") from exc
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError(f"port no es entero: {port_raw!r}") from exc
        return cls(
            process_name=process_name,
            pid=pid,
            port=port,
            password=password,
            protocol=protocol,
        )
