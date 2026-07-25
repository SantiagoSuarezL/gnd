"""Cliente opcional de la Live Client Data API de Riot.

Complemento secundario de `active_game_server_detector`. No reemplaza
al camino primario (psutil): solo confirma si hay partida activa
(expuesta por el cliente del juego solo durante una partida en curso)
y puede usarse para:
- Decidir *cuando* disparar el escaneo de conexiones (evita polling
  inutil cuando no hay partida).
- Validar manualmente cross-check contra la deteccion por psutil.

TECHNICAL_SPEC.md §2.2 nota:
- URL: https://127.0.0.1:2999/liveclientdata/activeplayer
- Certificado self-signed de Riot -> requiere `verify=False` (o cargar el
  cert own de Riot; por simplicidad usamos `verify=False` y aceptamos
  el riesgo de MITM solo en localhost, donde el unico atacante posible
  es un proceso local ya comprometido, escenario fuera de scope).
- Solo responde DURANTE una partida activa (no en lobby/champ select).

Diseno:
- `HttpClient(Protocol)` inyectable para tests sin `urllib`/`requests` real.
- Toda falla de red / cert / JSON malformado -> `None` con log, nunca
  excepcion a la UI (EP §1.2).
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

# Endpoint por defecto. Riot usa 127.0.0.1:2999 unicamente, no se
# documenta oficialmente pero es estable desde hace anios.
DEFAULT_LIVE_CLIENT_URL = "https://127.0.0.1:2999/liveclientdata/activeplayer"


class HttpClient(Protocol):
    """Abstraccion de un cliente HTTP GET para tests sin requests real.

    Devuelve (status_code, body_str). Lanza excepciones de red/cert que
    el caller captura y convierte a None (no reqes persistente).
    """

    def get(self, url: str, *, verify: bool, timeout_s: float) -> tuple[int, str]: ...


class LiveClientApi:
    """Cliente de la Live Client Data API de Riot (localhost:2999).

    Uso:

        api = LiveClientApi()  # usa urllib nativo
        active = api.is_game_active()
        if active:
            # disparar deteccion de game server (costosa) ahora
            ...

    O para confirmacion cruzada:

        data = api.fetch_active_player()
        if data is None:
            # o no hay partida, o fallo la API — usar el primario (psutil)
    """

    def __init__(
        self,
        *,
        url: str = DEFAULT_LIVE_CLIENT_URL,
        timeout_s: float = 1.5,
        http_client: HttpClient | None = None,
    ) -> None:
        self._url = url
        self._timeout_s = timeout_s
        if http_client is None:
            http_client = _UrllibClient()
        self._client: HttpClient = http_client

    def is_game_active(self) -> bool:
        """True si la Live Client Data API responde 200 con JSON.

        Rapido (timeout 1.5s por defecto) — suficiente para decidir
        si vale la pena disparar el escaneo de conexiones UDP.
        """
        body = self.fetch_active_player()
        return body is not None

    def fetch_active_player(self) -> dict | None:
        """Devuelve el JSON de /activeplayer o None si no hay partida /

        falla la API. Nunca lanza excepciones (EP §1.2).
        """
        try:
            status, body = self._client.get(
                self._url,
                verify=False,  # cert self-signed de Riot
                timeout_s=self._timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Live Client Data API no disponible (%s): %r. "
                "Probablemente no hay partida activa.",
                self._url,
                exc,
            )
            return None

        if status != 200:
            logger.debug(
                "Live Client Data API respondio %d (esperado 200) — "
                "sin partida activa o endpoint caido.",
                status,
            )
            return None

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.warning(
                "Live Client Data API: respuesta 200 pero JSON malformado: %s",
                body[:200],
            )
            return None

        if not isinstance(data, dict):
            logger.warning(
                "Live Client Data API: JSON no es objeto (fue %s)",
                type(data).__name__,
            )
            return None
        return data


class _UrllibClient:
    """Implementacion por defecto de HttpClient usando stdlib urllib.

    Sin dependencias externas (no usamos `requests`): solo urllib +
    ssl. `verify=False` require un contexto SSL sin verificacion porque
    el cert de Riot en 127.0.0.1:2999 es self-signed.
    """

    def get(self, url: str, *, verify: bool, timeout_s: float) -> tuple[int, str]:
        import ssl
        import urllib.request

        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url)  # noqa: S310 — URL por defecto fija
        with urllib.request.urlopen(
            req, timeout=timeout_s, context=ctx
        ) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            return (resp.status, body)
