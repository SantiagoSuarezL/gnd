"""Value Object ``GameEndpoint`` — endpoint público de un juego/publisher.

Fase 13. ARCHITECTURE.md §7: ``GameDiagnosticsModule.public_endpoints()``
devuelve ``list[GameEndpoint]`` (no ``list[str]``). El modulo de juego es
dueño de declarar, para cada endpoint público:
  - ``host``: IP literal o hostname (ej. ``auth.riotgames.com``) —
    ``RealPingRunner`` resuelve DNS inline si es hostname.
  - ``provider``: clave estable que se persiste en la BD y usa la capa
    ``analysis/`` como key de baseline. Ej. ``"riot_public"`` para LoL.
    Cada juego declara su propio provider de infra pública — así la
    extensibilidad no toca ``analysis/`` (DoD Fase 13).
  - ``family``: ``"ipv4"`` | ``"ipv6"`` — propagado a ``PingRunner``/
    ``TracerouteRunner`` para construir flags -4/-6 (Windows) o ping6
    (POSIX). Permite que un módulo declare solo v4, solo v6, o ambos.

Inmutable (Protocolo 5), campos no vacíos validados en ``__post_init__``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameEndpoint:
    """Un endpoint público a sondear para un juego.

    Ej.::

        GameEndpoint(host="auth.riotgames.com", provider="riot_public",
                     family="ipv4")
        GameEndpoint(host="2606:4700:4700::1111", provider="riot_public",
                     family="ipv6")
    """

    host: str
    provider: str
    family: str = "ipv4"

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host no puede ser vacío")
        if not self.provider:
            raise ValueError("provider no puede ser vacío")
        if self.family not in ("ipv4", "ipv6"):
            raise ValueError(f"family debe ser 'ipv4' o 'ipv6', fue {self.family!r}")
