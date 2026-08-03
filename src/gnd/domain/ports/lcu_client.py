"""Puerto ``LcuClient`` — consulta la LCU API local del cliente de LoL.

Fase 14.0a. TECHNICAL_SPEC.md §2.2. Una vez que ``LockfileReader`` da
``port`` + ``password``, este puerto hace GET a
``https://127.0.0.1:<port>/lol-gameflow/v1/session`` con Basic auth
``riot:PASSWORD`` (cert self-signed → ``verify=False`` en el adapter
real). Devuelve un ``GameflowSession`` VO mínimo.

Interface Segregation (EP §2.I): el puerto expone SOLO el endpoint que
GND usa (``get_gameflow_session``). NO expone ``request(method, path,
body)`` genérico — eso filtraria responsibilities al dominio y haría
el Protocol inseguro (cualquier caller podría tocar endpoints del
LCU que mután estado: dodge queue, leave champ-select). Con un método
puntual, el dominio solo permite lectura de la session.

EP §1.2: el adapter NUNCA lanza al caller. Si el LCU no responde
(cliente congelado, timeout, auth rechazada, JSON inesperado), el
adapter devuelve ``None`` con log estructurado
(``event="lcu.session.skip"`` + ``reason=...``). El caller decide el
fallback (en 14.0d: caer al ``ConnectionInspector`` histórico).

Implementaciones:
- ``network/lcu_client_http.py`` (sub-fase 14.0c): adapter real con
  ``urllib.request`` de stdlib (sin ``requests`` como dep nueva).
- ``domain/fakes/fake_lcu_client.py`` (14.0a): programable para tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gnd.models.gameflow_session import GameflowSession
from gnd.models.lockfile_data import LockfileData


@runtime_checkable
class LcuClient(Protocol):
    """Cliente de la LCU API local de LoL — solo lectura de session.

    Contrato:
    - No lanza excepciones (EP §1.2). Errores de IO, timeout, auth,
      JSON inesperado → ``None`` con log estructurado en el adapter.
    - Una instancia por lockfile — recibe ``LockfileData`` en el
      método para construir la URL + auth. No se persisten creds en
      el puerto (ephermeral, el port cambia al reiniciar LoL).
    """

    def get_gameflow_session(self, lockfile: LockfileData) -> GameflowSession | None:
        """Devuelve ``GameflowSession`` o ``None`` si no se pudo obtener.

        Razones típicas para ``None``:
        - Timeout del cliente (LeagueClientUx congelado).
        - Auth rechazada (password cambió entre el read del lockfile y
          el request — el cliente reinició entre medio).
        - JSON inesperado (campo ``phase`` ausente o vacío).
        - Status HTTP no-2xx (404 si el endpoint no existe en la
          version del cliente; 503 si el LCU esta arrancando).
        """
        ...
