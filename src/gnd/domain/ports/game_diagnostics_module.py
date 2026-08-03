"""Puerto GameDiagnosticsModule — extensibilidad multi-juego (Fase 13).

ARCHITECTURE.md §7 e IMPLEMENTATION_PLAN.md Fase 13. Cada juego implementa
esta interfaz para proveer al orquestador (`RunFullDiagnostics`):
  - los endpoints públicos a sondear (infraestructura del publisher),
  - los nombres de proceso a escanear para detectar partida activa,
  - la detección del servidor de partida activo.

El DoD (Definition of Done) de la Fase 13 es: agregar un juego nuevo es,
en líneas de código, mayormente contenido dentro de
`diagnostics/games/<nuevo_juego>.py`. Es decir, NO debe requerir tocar
`analysis/`, `recommendations/`, ni `database/`.

Interface Segregation (ENGINEERING_PRINCIPLES.md §2.I): separado de
`ConnectionInspector`. Un módulo de juego *puede* delegar la detección
del servidor activo a un `ConnectionInspector` (escaneo UDP genérico,
como hace LoL), pero el módulo es quien conoce los `process_names` del
juego y los endpoints públicos del publisher — el `ConnectionInspector`
es agnóstico al juego y solo enumera conexiones de proceso.

Inyectamos `public_endpoints()` como `list[str]` (hostnames o IPs) y no
`list[Target]` como dice el spec literal de ARCHITECTURE.md §7 porque el
orquestador ya construye `PingRunner.ping(target_ip=..., ...)` con
strings y `RealPingRunner` resuelve DNS inline. Introducir un VO
`Target` extra sería YAGNI hoy (Regla 9.5): ningún caller lo pide y el
orquestador ya normaliza hostnames vs IPs (ver `_looks_like_ip_literal`
en `run_full_diagnostics.py`). Si una fase futura necesita metadata por
endpoint (puerto, protocolo, familia), ahí sí promuevo a VO.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gnd.models.active_game_server import ActiveGameServerInfo
from gnd.models.game_endpoint import GameEndpoint


@runtime_checkable
class GameDiagnosticsModule(Protocol):
    """Contrato de un módulo de diagnóstico por juego.

    El orquestador (`RunFullDiagnostics`) llama a estos métodos:
      1. ``public_endpoints()`` -> ``list[GameEndpoint]``. Cada endpoint
         lleva host + provider + family. El provider es la clave estable
         que ``analysis/`` usa como key de baseline (no puede ser
         hardcodeado por el orquestador: cada juego declara su propio
         provider de infra pública — así la extensibilidad no toca
         ``analysis/`` ni ``database/``).
      2. ``process_names()`` -> nombres de proceso del cliente del juego
         a escanear (para detección de partida activa). Ej.
         ``{"League of Legends.exe"}``.
      3. ``detect_active_server()`` -> ``ActiveGameServerInfo | None``.
         Si el juego no soporta detección de partida activa (ej. un
         juego sin servidor dedicado dinámico), devuelve ``None``
         siempre (feature opt-out por juego).
      4. ``game_server_provider()`` -> ``str``, provider usado para el
         probe al servidor de partida activo detectado (ej.
         ``"riot_game_server"`` para LoL). El orquestador asigna ese
         provider al ``ProbeResult`` del ping-al-server, y ``analysis/``
         lo usa como key de baseline — separado del provider
         ``public_endpoints`` para distinguir infraestructura pública del
         servidor de partida real (mismo split que ``_PROVIDER_RIOT_PUBLIC``
         vs ``_PROVIDER_RIOT_GAME_SERVER`` hoy).

    Contrato (EP §1.2): ``detect_active_server`` NUNCA lanza excepción
    a la UI — toda falla (AccessDenied, sin proceso, sin conexión UDP
    pública) se traduce a ``None`` con log. El orquestador envuelve en
    try/extra por belt-and-suspenders, pero el módulo debe cumplir el
    contrato.
    """

    def public_endpoints(self) -> list[GameEndpoint]:
        """Endpoints públicos (host + provider + family) del juego/publisher.

        Una lista vacía significa "no hay endpoints públicos a sondear
        para este juego" (solo gateway + internet health cubren el run).
        """
        ...

    def process_names(self) -> set[str]:
        """Nombres de proceso del cliente del juego (para escaneo UDP).

        Un set vacío implica "detección de partida activa deshabilitada
        para este juego" — el orquestador salta la etapa de detección.
        """
        ...

    def detect_active_server(self) -> ActiveGameServerInfo | None:
        """Detecta el servidor de partida activo real del juego.

        Devuelve ``None`` si no hay partida activa, si el proceso no
        está corriendo, si no se pudo enumerar (AccessDenied), o si el
        juego no soporta detección de partida activa. Nunca lanza
        (EP §1.2).
        """
        ...

    def game_server_provider(self) -> str:
        """Provider del probe al servidor de partida activo detectado.

        El orquestador asigna este provider al ``ProbeResult`` del ping
        al server detectado, y ``analysis/`` lo usa como key de baseline
        — separado del provider de ``public_endpoints`` para distinguir
        la infraestructura pública del publisher del servidor de partida
        real (ej. ``"riot_public"`` vs ``"riot_game_server"`` hoy).
        Un valor vacío inválido: el orquestador debe poder usarlo como
        ``provider`` de ``ProbeResult`` (no vacío, cadena estable).
        """
        ...
