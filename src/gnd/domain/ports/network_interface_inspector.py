"""Puerto NetworkInterfaceInspector — snapshot de la interfaz de red (Fase 12a.3).

PRD §7 should-have. Implementación real en network/
(`RealNetworkInterfaceInspector`: `psutil` + `netsh wlan show interfaces`
en Windows con check `platform.system()`, fallbacks limpios en
POSIX/macOS). Fake en domain/fakes/ para tests sin red/subprocess.

EP §1.2: el contrato del Protocol garantiza `inspect()` NUNCA lanza —
todo fallo del OS / netsh / parser de signal se traduce a un
`NetworkInterfaceSnapshot(type=OTHER, error=str(exc))` con el contexto
para logging. El caller (orquestador) no hace try/except del inspector.

Por qué el helper toma `default_route_hint`: para que el adaptador real
sepa qué interfaz es la default route sin tener que redetectar (el
`composition_root._resolve_gateway_ip` ya infiere la IP del gateway;
podemos extender para pasar el nombre de la interfaz). default `None`
dejando que el adaptador haga la detección por si mismo.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gnd.models.network_interface import NetworkInterfaceSnapshot


@runtime_checkable
class NetworkInterfaceInspector(Protocol):
    """Toma un snapshot inmutable de la interfaz de red activa.

    `default_route_iface_hint`: nombre OS de la interfaz default-route
    (ej. "Wi-Fi", "eth0"). Si None, el adaptador lo detecta por si mismo
    usando la ruta por defecto del OS. Hacerlo inyectable simplifica tests
    (no necesita mockear el OS para fijar el iface).
    """

    def inspect(
        self,
        *,
        default_route_iface_hint: str | None = None,
    ) -> NetworkInterfaceSnapshot: ...
