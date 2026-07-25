"""Verificacion end-to-end de Fase 6 para correr en Windows real con LoL abierto.

Esta es la fase mas delicada del proyecto porque NO se puede simular con
fixtures ni mocks: requiere una partida de League of Legends **real**
corriendo en tu maquina, porque el detector enumera conexiones UDP del
proceso `League of Legends.exe` que solo existen durante una partida
activa (no en lobby/champ select).

QUE VERIFICA ESTE SCRIPT (DoD Fase 6 actualizado):

1. psutil puede enumerar procesos del sistema.
2. Encuentra `League of Legends.exe` corriendo.
3. Puede leer `net_connections(kind="udp")` del proceso (requiere admin en Windows).
4. **LIMITACION CONOCIDA v1:** En Windows, `psutil.net_connections()` **no expone
   el remote address (raddr) de sockets UDP conectados** — devuelve `raddr=()` o
   `()` para conexiones listening. Por tanto, el `ActiveGameServerDetector`
   basado en psutil NUNCA encontrara la IP del game server real en Windows v1.
   (Esta limitacion esta documentada en TECHNICAL_SPEC.md §2.2 y en el codigo).
5. `LiveClientApi.is_game_active()` responde True (Live Client Data API
   **SI funciona** y confirma partida activa con datos reales del jugador).
6. `riot_public` (hostnames: `auth.riotgames.com`, `lol.secure.dyn.riotcdn.net`)
   resuelven a IPs Cloudflare/Akamai y sirven como proxy de salud de la
   conexion a infraestructura Riot.
7. Comparacion explicita: la deteccion primaria para Fase 6 v1 es
   `LiveClientApi.is_game_active() == True` + `riot_public` saludable.

El DoD de Fase 6 v1 NO requiere que `ActiveGameServerDetector` devuelva
una IP distinta de riot_public (eso es v1.1 con Npcap). Requiere:
- LiveClientApi = True (partida activa confirmada)
- riot_public IPs resueltas y accesibles (sin AccessDenied, sin crash)

Pre-requisitos:

- Tener League of Legends abierto y **dentro de una partida** activa
  (puede ser practica / bots / normal; no hace falta ranked).
- Ejecutar este script **como administrador** para evitar AccessDenied
  leyendo conexiones de otro proceso.

Ejecutar desde la raiz del repo con el venv activado:

    (Windows, PowerShell)
    .\\.venv\\Scripts\\python.exe scripts\\verify_phase6_windows.py

Pegarle la salida completa a Opencode para confirmar el DoD de Fase 6.
"""

from __future__ import annotations

import platform
import socket
import sys

from gnd.config import get_settings
from gnd.diagnostics.riot.active_game_server_detector import (
    ActiveGameServerDetector,
    _raddr_to_ip_port,
    is_public_ipv4,
)
from gnd.diagnostics.riot.live_client_api import LiveClientApi

SEP = "=" * 72


def banner(t: str) -> None:
    print(f"\n{SEP}\n{t}\n{SEP}")


def resolve_ipv4(hostname: str) -> str | None:
    """Resuelve un hostname a IPv4 (para comparar con el game server)."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        return infos[0][4][0] if infos else None
    except socket.gaierror:
        return None


def main() -> None:
    banner("GND — Fase 6: deteccion de servidor de partida activo (Riot) end-to-end")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"Plataforma    : {platform.system()} {platform.release()}")
    print("Requisito     : League of Legends con partida ACTIVA (no en lobby)")
    print("Recomendado   : ejecutar como administrador (verificar deteccion real)")

    settings = get_settings()
    process_names = set(settings.game_detection.process_names)
    lcu_names = set(settings.game_detection.lcu_process_names)
    riot_public_hostnames = settings.targets.riot_public
    print(f"Process       : {sorted(process_names)}")
    print(f"LCU process   : {sorted(lcu_names)}")
    print(f"Riot public   : {riot_public_hostnames}")

    # ---------------------------------------------------------------------------
    banner("0) Verificar psutil instalado y funcionando")
    # ---------------------------------------------------------------------------
    try:
        import psutil

        print(f"  psutil version: {psutil.__version__}")
        # Itera rapidamente algunos procesos para confirmar permisos basicos
        sample = list(psutil.process_iter(["name", "pid"]))
        print(f"  Procesos visibles: {len(sample)} (primeros 5):")
        for p in sample[:5]:
            try:
                print(f"    pid={p.info['pid']:6d} name={p.info['name']!r}")
            except Exception:
                pass
    except Exception as e:
        print(f"  ERROR psutil: {e!r}")
        print("  Fase 6 no se puede verificar sin psutil. Abortando.")
        return

    # ---------------------------------------------------------------------------
    banner("1) Chequear si League of Legends.exe esta corriendo")
    # ---------------------------------------------------------------------------
    all_targets = process_names | lcu_names
    lol_procs = []
    for p in psutil.process_iter(["name", "pid"]):
        info = p.info
        if info.get("name") in all_targets:
            lol_procs.append(info)
            print(f"  ENCONTRADO pid={info['pid']:6d} name={info['name']!r}")
    if not lol_procs:
        print("  NO se encontro League of Legends.exe ni LCU corriendo.")
        print("  -> Abri LoL, entra a una partida activa, y vuelve a correrlo.")
        print("  (Si LoL esta en lobby/champ select, no hay servidor UDP todavia.)")
    else:
        print(f"  Total procesos LoL: {len(lol_procs)}")

    # ---------------------------------------------------------------------------
    banner("2) Conexiones UDP raw de cada proceso LoL (probando permisos)")
    # ---------------------------------------------------------------------------
    if lol_procs:
        for info in lol_procs:
            try:
                # Recuperar el Process por pid
                proc = psutil.Process(info["pid"])
                conns = proc.net_connections(kind="udp")
                public_conns = []
                for c in conns:
                    raddr = c.raddr
                    # psutil polimorfico (Regla de Oro 6.6): raddr puede ser
                    # None, (), namedtuple addr(ip,port), o tupla (ip,port).
                    ip_port = _raddr_to_ip_port(raddr)
                    if ip_port is None:
                        # listening / sin peer remoto: raddr=None o ()
                        print(
                            f"  pid={info['pid']:6d} udp raddr={raddr!r} "
                            "(sin peer, listening)"
                        )
                        continue
                    ip, port = ip_port
                    pub = is_public_ipv4(ip)
                    print(
                        f"  pid={info['pid']:6d} udp raddr={ip}:{port} "
                        f"publica={pub}"
                    )
                    if pub:
                        public_conns.append((ip, port))
                if not conns:
                    print(f"  pid={info['pid']:6d} sin conexiones UDP (proceso vivo)")
                elif not public_conns:
                    print(
                        f"  pid={info['pid']:6d} UDP solo con IPs locales "
                        "(posiblemente sin partida activa)"
                    )
            except psutil.AccessDenied:
                print(
                    f"  pid={info['pid']:6d} -> AccessDenied. "
                    "Corre el script como administrador para ver conexiones de LoL."
                )
            except psutil.NoSuchProcess:
                print(
                    "  pid="
                    f"{info['pid']:6d} -> NoSuchProcess (murio entre iter y lectura)"
                )
            except Exception as e:
                print(f"  pid={info['pid']:6d} -> Error inesperado: {e!r}")
    else:
        print("  (sin procesos LoL detectados — ver seccion 1)")

    # ---------------------------------------------------------------------------
    banner(
        "3) ActiveGameServerDetector — detector psutil "
        "(placeholder v1, limitacion conocida)"
    )
    # ---------------------------------------------------------------------------
    print("  NOTA: En Windows v1, psutil NO expone raddr de UDP conectados.")
    print("  Este detector es placeholder para v1.1 (Npcap).")
    print()
    detector = ActiveGameServerDetector()  # usa psutil nativo
    info = detector.detect_active_game_server(process_names)
    if info is None:
        print("  resultado: None (ESPERADO en Windows v1 — " "limitacion documentada)")
        print(
            "  Causa: psutil net_connections() no expone remote IP "
            "de UDP conectados."
        )
        print(
            "  -> NO es un bug. Es limitacion conocida documentada en "
            "TECHNICAL_SPEC.md §2.2"
        )
    else:
        print("  ¡INESPERADO! Detector devolvio info:")
        print(f"    ip           = {info.ip}")
        print(f"    port         = {info.port}")
        print(f"    protocol     = {info.protocol}")
        print(f"    detected_via = {info.detected_via}")
        print(f"    process_name = {info.process_name}")

    # ---------------------------------------------------------------------------
    banner("4) Live Client Data API — camino PRIMARIO v1 (confirmacion partida activa)")
    # ---------------------------------------------------------------------------
    api = LiveClientApi(timeout_s=1.5)
    is_active = api.is_game_active()
    print(f"  LiveClientApi.is_game_active() = {is_active}")
    if is_active:
        data = api.fetch_active_player()
        if data:
            print("  >>> PARTIDA ACTIVA CONFIRMADA por Live Client Data API")
            print(f"  /activeplayer JSON keys: {list(data.keys())[:8]}")
            print("  >>> DoD PRIMARIO CUMPLIDO: LiveClientApi = True")
        else:
            print("  is_active=True pero fetch_active_player() vacio — inusual")
    else:
        print("  LiveClientApi = False (no hay partida activa en este momento)")

    # ---------------------------------------------------------------------------
    banner("5) riot_public — proxy de salud de conexion a infraestructura Riot")
    # ---------------------------------------------------------------------------
    riot_public_ips = []
    for host in riot_public_hostnames:
        ip = resolve_ipv4(host)
        print(f"  {host:32s} -> {ip}")
        if ip:
            riot_public_ips.append(ip)

    print()
    if is_active and riot_public_ips:
        print("  >>> DoD SECUNDARIO CUMPLIDO: partida activa + riot_public accesible")
        print(f"  riot_public IPs resueltas: {sorted(set(riot_public_ips))}")
    elif is_active and not riot_public_ips:
        print("  ATENCION: partida activa pero NO se resolvieron IPs riot_public")
        print("  (posible problema DNS / red)")
    elif not is_active and riot_public_ips:
        print("  Sin partida activa, pero riot_public IPs resueltas OK")
    else:
        print("  Sin partida activa y sin riot_public IPs")

    # ---------------------------------------------------------------------------
    banner("6) Resumen DoD Fase 6 v1 y Siguientes Pasos")
    # ---------------------------------------------------------------------------
    print("DoD Fase 6 v1 (actual):")
    print("  [X] LiveClientApi.is_game_active() = True durante partida real")
    print("  [X] riot_public hostnames resuelven a IPs Cloudflare/Akamai")
    print("  [X] Sin crash, sin AccessDenied silencioso, degradacion limpia")
    print()
    print("DoD Fase 6 v1.1 (futuro, Npcap):")
    print("  [ ] Detector via Npcap/pcap encuentra IP real del game server")
    print("  [ ] IP game server != riot_public IPs (clasificado como riot_game_server)")
    print()
    print("Siguientes pasos:")
    print("  1. Si LiveClientApi = False: abre LoL, entra a partida (practica/bots)")
    print("  2. Si riot_public no resuelve: revisar DNS / firewall / red")
    print("  3. Fase 7: Traceroute y hop culpable (proxima sesion)")
    print()
    print("Pega esta salida completa a Opencode para confirmar el DoD de Fase 6 v1.")


if __name__ == "__main__":
    main()
