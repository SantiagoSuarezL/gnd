"""Verificación in-vivo del RealWarpController (Regla 12b.4.2, post-Fase 13 sesión 2).

Script SOLO LECTURA — verifica que el adapter real de WARP parsea
correctamente el estado actual de tu `warp-cli` (versión 2026.6.850.0) sin
mutar WARP (no prende/apaga/changed mode).

QUÉ PRUEBA:
1. `shutil.which("warp-cli")` encuentra el binario en tu PATH.
2. `RealWarpController.get_status()` parsea `warp-cli status --no-paginate`
   texto plano correctamente (regresión: el código viejo usaba
   `--output-format=json` que NO existe y crasheaba silenciosamente).
3. El adapter también parsea `warp-cli settings list` para extraer el
   `mode` (warp/proxy/doh) y `tunnel_protocol` (WireGuard=UDP/MASQUE).
4. Muestra el estado completo para que confirmes visualmente que matchea
   con lo que ves en la app de Cloudflare (ej. "Connected" + "WireGuard"
   si vos lo prendiste en modo UDP).

NO PRUEBA EL RESTORE (eso mutaría WARP — dejalo para el botón real en la
UI). Si este script muestra los campos correctos, el botón va a funcionar
igual (usa el mismo adapter). Si algo está mal, te muestra None para los
campos que no pudo parsear — eso dispara el fail-safe (Regla 12b.4.2).

Ejecutar:
    python scripts/verify_warp_controller_in_vivo.py
"""

from __future__ import annotations

import sys

from gnd.network.real_warp_controller import RealWarpController


def main() -> int:
    print("=" * 72)
    print("Verificación in-vivo RealWarpController (Regla 12b.4.2)")
    print("=" * 72)

    ctrl = RealWarpController()

    if not ctrl.available:
        print("\n[FALLÓ] warp-cli no fue encontrado en PATH.")
        print("       Verificá que esté instalado y disponible (re-iniciá la")
        print("       terminal si lo acabás de instalar).")
        return 1

    print("\n[OK] warp-cli encontrado.")

    print("\n--- get_status() ---")
    status = ctrl.get_status()

    print(f"  connected         = {status.connected}")
    print(f"  connection_status = {status.connection_status!r}")
    print(f"  registration      = {status.registration_status!r}")
    print(f"  warp_plus         = {status.warp_plus}")
    print(f"  mode              = {status.mode!r}   (ej: 'warp', 'proxy', 'doh')")
    print(
        f"  tunnel_protocol   = {status.tunnel_protocol!r}   "
        f"(ej: 'WireGuard'=UDP, 'MASQUE')"
    )

    print("\n--- Interpretación ---")
    if status.connection_status == "error":
        print("  [PROBLEMA] No se pudo parsear `status`. El adapter va a reportar")
        print("            unavailable — NO va a fallar, pero la comparación no")
        print("            va a correr. Pegame un screenshot del output de")
        print("            `warp-cli status --no-paginate` para debuggear.")
        return 2

    if status.mode is None or status.tunnel_protocol is None:
        print("  [FALL-SAFE ACTIVADO] No se detectó el mode o tunnel_protocol")
        print("       (mode=None o tunnel_protocol=None). Si vos corrés la")
        print("       comparación ahora, el restore va a aplicar fail-safe")
        print("       (NO restaurará a ciego — te avisará que prenda WARP a")
        print("       mano). Pegame el output de `warp-cli settings list`.")
        print("       Tu CLI quizás tiene un formato distinto y hay que tunear")
        print("       el regex.")
        return 3

    print("  [OK] Estado completo detectado.")
    print(f"       -> Vos lo prendiste en modo {status.mode.upper()} /")
    print(f"          protocolo {status.tunnel_protocol} (UDP = WireGuard).")
    print()
    print("  Si esto matchea con tu app de Cloudflare, el botón 'Run WARP")
    print("  Comparison' en GND va a funcionar correctamente y restaurará el")
    print("  estado a este mismo modo/protocolo al terminar.")
    print()
    print("  >>> Podés tocar el botón real ahora. <<<")
    return 0


if __name__ == "__main__":
    sys.exit(main())
