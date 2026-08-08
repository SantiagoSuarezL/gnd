# Game Network Diagnostics (GND)

Asistente de diagnóstico de red pre-partida y en-partida para League of Legends
(arquitectura extensible a otros juegos vía `GameDiagnosticsModule`). No es un
ping tool: interpreta el estado de la red como lo haría un ingeniero de redes
senior, y emite un veredicto explicado con recomendaciones accionables.

**Target:** Python 3.12+, Windows 10/11. La app corre windowless (launcher VBS)
o como script (`python -m gnd`). Las features de red avanzadas
(`warp-cli`, `ookla-speedtest`, `netsh`) son opt-in y degradan con log si los
binarios externos no están disponibles (EP §1.2).

---

## Estado del proyecto

**v1 funcional.** Fases 1-13 + 14.0a completadas. Suite de tests: **1007 unit +
17 integration**, `ruff` + `black` + `vulture` limpios (1 flake tkinter 12b.4.2
conocido, pasa aislado).

Features implementadas:
- **Core:** ping (IPv4/IPv6 opt-in), traceroute con hop culpable, monitoreo
  continuo estilo WinMTR, baseline histórico por `provider`, Network Score
  ponderado, motor de recomendación (7 reglas + 2 constraints), logging JSON
  estructurado (JSONL rotación diaria + retención).
- **UI:** tkinter dark mode, 6 pestañas (Diagnostics/Monitoring/History/Charts/
  Recommendations + WARP Compare + Speed Test), gráficos matplotlib embebidos,
  export Markdown.
- **Multi-juego (Fase 13):** `GameDiagnosticsModule` Protocol. Soportados:
  `league_of_legends` (default), `valorant`. Agregar un juego nuevo NO toca
  `analysis/`, `recommendations/` ni `database/` (blindado con tests estáticos).
- **Features opt-in (Fase 12b):** notificaciones de escritorio (plyer), reportes
  periódicos automáticos (semanal/mensual), comparación con/sin Cloudflare WARP,
  speed test bajo demanda (ookla-speedtest), export Markdown.
- **Empaquetado Windows (post-Fase 14.0a):** launcher `launch_gnd.vbs` + acceso
  directo `GND.lnk` en el escritorio. Subprocesses con `CREATE_NO_WINDOW`
  (sin ventanas cmd parpadeantes desde `pythonw.exe`).
- **Fase 14.0a (detección IP real LoL):** VOs + Protocols + Fakes para leer el
  lockfile del League Client y consultar la LCU API (`gameflowSession.serverIp`).
  Tier `exact_ip` implementado (funciona en todas las regiones). Tier
  `regional_edge` pausado (solo NA1/EUW1 resuelven Riot-direct; demás regiones
  son Cloudflare-anycast o NXDOMAIN — ver `lessons_learned.md` Regla 14.0a.1).
  Adapter real (`network/lockfile_discovery.py`) pendiente en sub-fase 14.0b.

---

## Cómo navegar esta documentación

Lee en este orden si es la primera vez que trabajas en el proyecto:

1. **[`PRD.md`](./PRD.md)** — qué se está construyendo y por qué. Problema,
   usuario, features, no-objetivos, métricas de éxito.
2. **[`ARCHITECTURE.md`](./ARCHITECTURE.md)** — cómo está estructurado el sistema.
   Capas, módulos, y el modelo de 3 capas de conectividad Riot (Client / LCU /
   Game Server), que es el elemento distintivo de este proyecto.
3. **[`TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md)** — contratos de datos exactos,
   protocolos de red, esquema de base de datos, motor de recomendación,
   thresholds de configuración.
4. **[`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md)** — plan de fases con
   Definition of Done por fase. Es la guía de ejecución fase por fase.
5. **[`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md)** — estándares de
   código no negociables (Clean Architecture, SOLID aplicado, DI, testing,
   checklist de revisión).

### Contexto mínimo por tipo de tarea

No es necesario cargar los 5 documentos completos para cada tarea:

| Tarea | Documentos a cargar |
|---|---|
| Diseñar/discutir un módulo nuevo | `ARCHITECTURE.md` + `ENGINEERING_PRINCIPLES.md` |
| Implementar una fase del plan | `IMPLEMENTATION_PLAN.md` (fase específica) + `TECHNICAL_SPEC.md` (secciones relevantes) |
| Revisar código existente | `ENGINEERING_PRINCIPLES.md` (checklist §7) |
| Discutir producto/alcance | `PRD.md` |
| Ajustar el motor de recomendación | `TECHNICAL_SPEC.md` §5 |

### Colaboradores y agentes: graphify

Este repo tiene **graphify** instalado (grafo de conocimiento del código en
`graphify-out/graph.json`, hook post-commit/post-checkout activo — se
reconstruye solo, no hace falta correrlo a mano). Antes de leer o grepear
archivos de código para entender cómo se conecta algo (qué llama a qué, qué
depende de qué, dónde vive un concepto), consultá primero el grafo en vez de
abrir archivos crudos:

- `graphify query "<pregunta en lenguaje natural>"` — subgrafo acotado a una
  pregunta.
- `graphify explain "<NombreDeClaseOFuncion>"` — todas las conexiones de un
  nodo puntual.
- `graphify path "<A>" "<B>"` — trazar cómo se conectan dos cosas.
- `GRAPH_REPORT.md` (en `graphify-out/`) — revisión de arquitectura general:
  god nodes, comunidades, conexiones sorprendentes.

> `graphify-out/` está en `.gitignore` (se regenera por máquina). Para
> colaboradores nuevos: el hook post-checkout lo construye solo la primera
> vez. Si querés forzarlo, corré `graphify install` (detalla la plataforma).
> Esto reemplaza grepear/leer archivo por archivo cuando la pregunta es sobre
> relaciones o estructura del código — no reemplaza leer el archivo cuando ya
> sabés cuál es y necesitás el contenido exacto (implementación, lógica de
> negocio).

---

## El elemento distintivo del proyecto

GND diferencia explícitamente entre:

- La **IP pública de infraestructura Riot** (login/patch, ej.
  `auth.riotgames.com` → `104.16.119.50` via Cloudflare) — dinámica por CDN, no
  representa el ping real de partida.
- La **IP del servidor de partida activo** — dinámica, asignada por matchmaking,
  detectada en tiempo real mediante enumeración de conexiones UDP del proceso
  del juego (ver `TECHNICAL_SPEC.md` §2.2).

Toda la arquitectura (base de datos, análisis histórico, motor de recomendación)
trata estos dos como `provider` separados (`riot_public` vs `riot_game_server`)
para no contaminar el baseline histórico ni las recomendaciones. La Fase 14.0a
extiende esto con un tier `exact_ip` (IP cruda del LCU) que funciona en todas
las regiones sin depender de mappings de hostnames regionales no documentados.

---

## Setup del entorno

> **Meta de esta sección:** que cualquiera que clone el repo en una PC nueva
> (Windows 10/11) pueda correr GND end-to-end sin tocar nada más que los
> comandos acá listados. Todas las features core funcionan out-of-the-box;
> las avanzadas (WARP, speed test, notificaciones, IPv6, etc.) son opt-in y
> degradan con log si les falta su binario externo — la app nunca crashea
> al arrancar por algo que no esté instalado (EP §1.2).

### Quickstart (clone → run)

```powershell
# Desde una PowerShell con Python 3.12+ en PATH:
git clone https://github.com/SantiagoSuarezL/gnd.git
cd gnd
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"      # runtime + dev deps en modo editable
python -m gnd                # abre la UI (tkinter dark mode)
```

Eso abre la ventana de GND lista para correr diagnósticos contra internet.
Sin `config.toml`, sin binarios externos, sin setup extra. Los datos
persistentes (`history.db`, `logs/*.jsonl`, `reports/*.md`) se crean solos
en `%APPDATA%\GND\` al primer run, sin intervención.

**Sanidad post-install** (valida linters + tests en un solo command):

```powershell
.\scripts\check.ps1          # ruff + vulture + black --check + pytest
```

Si `check.ps1` pasa verde, el repo está listo para desarrollo. Si solo
querés usar la app (no desarrollar), podés saltear `check.ps1`.

### Requisitos

| Requisito | Detalle | Cómo verificarlo |
|---|---|---|
| **Python 3.12+** | `pyproject.toml` fija `requires-python = ">=3.12"`. Python 3.13+ también funciona. | `python --version` (debe decir `3.12.x` o mayor) |
| **Windows 10/11** | Target primario. `netsh` (Wi-Fi snapshot), `ping -w`, `tracert` son built-in del OS. La app no crashea en Linux/macOS — solo degrada features Windows-only con log estructurado. | `winver` |
| **pip / venv** | Vienen con Python en Windows installer oficial. | `python -m pip --version` |
| **Acceso a internet** | Para pinguear `8.8.8.8`, `1.1.1.1`, `9.9.9.9`, `auth.riotgames.com`, `lol.secure.dyn.riotcdn.net`. Los targets son hostnames globales — no hay lock-in a una red específica. | `ping 8.8.8.8` |

**No requiere** (a pesar de lo que podría parecer):

- ❌ **No requiere admin** ni privilegios elevados (excepto para instalar
  globalmente Cloudflare WARP o Ookla CLI, ver ahead).
- ❌ **No requiere League of Legends instalado** para abrir la UI. La
  detección de partida activa solo se intenta si LoL está corriendo; si no,
  el orquestador salta esa etapa con log y el resto del diagnóstico funciona.
- ❌ **No requiere `warp-cli` ni `speedtest`** para abrir la app. Las dos
  features que los usan son opt-in via `config.toml`; si sus binarios no están
  en `PATH`, los botones de UI quedan deshabilitados y el caso de uso devuelve
  un resultado con `*_available=False` (Regla 12b.2.1 — import diferido).
- ❌ **No requiere crear `config.toml`**. La app funciona con defaults; el
  archivo es solo para habilitar features opt-in.
- ❌ **No requiere Redis, Docker, ni servicios externos.** La persistencia es
  SQLite embebido en `%APPDATA%\GND\history.db`.

### Setup básico (paso a paso)

```powershell
# 1) Clonar el repo
git clone https://github.com/SantiagoSuarezL/gnd.git
cd gnd

# 2) Crear el venv (NO requiere admin). NOTA: si tenés PowerShell Execution
#    Policy restrictiva y Activate.ps1 falla, abrí una PowerShell como admin
#    una sola vez y corré:
#        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#    (después de eso, Activate.ps1 funciona en sesiones no-admin).
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) Instalar dependencias (runtime + dev tools en una sola línea)
pip install -e ".[dev]"
```

`pip install -e ".[dev]"` instala en modo editable (cambios al código se
reflejan sin reinstalar) y baja:

**Runtime deps** (`pyproject.toml:dependencies`):
- `pydantic>=2.0`, `pydantic-settings>=2.0` — settings/config
- `psutil>=5.9,<8` — enumeración de conexiones del proceso del juego
- `matplotlib>=3.7,<4` — gráficos embebidos en tkinter
- `plyer>=2.1.0` — notificaciones de escritorio multiplataforma

**Dev deps** (`pyproject.toml:optional-dependencies.dev`):
- `pytest>=8.0` + `pytest-asyncio>=0.23` + `pytest-cov` — testing
- `ruff>=0.5` — linter único (reglas `E`, `F`, `I`, `UP`, `B`)
- `black>=24.0` — formatter (line-length=88)
- `vulture>=2.16` — detector de código muerto

### Configuración opcional: launcher VBS + acceso directo (Windows)

Para usar GND como app de escritorio sin terminal visible (recomendado para
uso diario):

```powershell
# Crea "GND.lnk" en el escritorio apuntando al launcher launch_gnd.vbs
# (idempotente — sobreescribe si ya existe). NO requiere admin.
.\scripts\install_shortcut.ps1
```

Después de eso, doble-click en `GND.lnk` (escritorio) abre la UI sin terminal.

El launcher `launch_gnd.vbs` (repo root) hace:
- Deriva el repo root relativo a sí mismo (sobrevive a movimientos del repo).
- Valida que `.venv\Scripts\pythonw.exe` exista (MsgBox claro si falta).
- Corre `pythonw.exe -m gnd` windowless (`WindowStyle=0`).

Si movés el repo a otra ruta, re-corré `install_shortcut.ps1` para
regenerar el `.lnk` con el nuevo path absoluto — el `.vbs` no necesita
cambios.

**Debug del launcher** (cuando no abre la UI):

```powershell
cscript //nologo launch_gnd.vbs 2> gnd_console_debug.log
Get-Content gnd_console_debug.log      # ver el output
```

`gnd_console_debug.log` está en `.gitignore` (archivo de debug temporal).
`pythonw.exe` no redirige output — para capturar stderr de Python, editá
temporalmente el `.vbs` para usar `python.exe` y el redirect arriba.

### Features opt-in (vía `config.toml`)

La app funciona sin `config.toml` (usa defaults de `GndSettings`). Para
habilitar features avanzadas, crear `config.toml` en el repo root (donde
corre `python -m gnd`):

La app funciona sin `config.toml` (usa defaults de `GndSettings`). Para
habilitar features avanzadas, crear `config.toml` en el repo root (donde corre
`python -m gnd`):

```toml
[notifications]
enabled = true
notify_only_on_issues = true  # solo notificar cuando verdict != EXCELENTE

[reports]
enabled = true
period = "weekly"             # "weekly" | "monthly"

[warp_comparison]
enabled = true                # requiere warp-cli en PATH

[speed_test]
enabled = true                # requiere el binario `speedtest` en PATH

[network]
inspect_interface = true      # Wi-Fi/Ethernet snapshot via netsh (Windows)

[dns]
enabled = true                # medir tiempo de resolución DNS como etapa extra

[game_detection]
active_game = "valorant"      # "league_of_legends" | "valorant"

[targets]
# IPv6 opt-in: si not None, se corren probes v6 además de los v4
cloudflare_ipv6 = "2606:4700:4700::1111"
google_dns_ipv6 = "2001:4860:4860::8888"
```

`config.toml` está en `.gitignore` (config personal, no se sube). Cada máquina
mantiene la suya. También se puede override via env vars con prefijo `GND_`
( ejemplo `GND_SPEED_TEST__ENABLED=true`).

### Dependencias externas opt-in

Estas features requieren binarios externos instalados (no son deps de Python).
Si no están en `PATH`, el botón de UI se deshabilita y el caso de uso devuelve
un resultado con `*_available=False` — la app NO crashea (Regla 12b.2.1: import
diferido + log `event="<feature>.skip"`).

| Feature | Binario en `PATH` | Cómo verificarlo |
|---|---|---|
| WARP Comparison | `warp-cli` | `warp-cli --version` |
| Speed Test | `speedtest` (Ookla CLI) | `speedtest --version` |
| Wi-Fi/Ethernet snapshot | `netsh` (Windows built-in) | `netsh /?` |
| IPv6 probes | SO con stack IPv6 | `ping -6 ::1` |
| Detección de partida activa (LoL) | `League of Legends.exe` corriendo + Live Client API en `127.0.0.1:2999` | Solo durante partida activa |
| Detección de partida activa (Valorant) | `VALORANT-Win64-Shipping.exe` corriendo | Solo durante partida activa |

#### Cómo instalar los binarios externos (Windows, fresh PC)

**`warp-cli` (Cloudflare WARP):**
```powershell
# Opción A — installer oficial MSI (requiere admin):
# Descargar de https://developers.cloudflare.com/warp/ y ejecutar el .msi

# Opción B — winget (sin admin interactiva):
winget install --id Cloudflare.CloudflareWARP

# Verificar:
warp-cli --version
```

**`speedtest` (Ookla Speedtest CLI):**
```powershell
# Opción A — Scoop (recomendado, sin admin):
scoop install speedtest

# Opción B — installer oficial de Ookla:
# Descargar de https://www.speedtest.net/apps/cli (zip con speedtest.exe)
# y agregar la carpeta a PATH manualmente.

# Opción C — winget (si Ookla está publicado):
winget install --id Ookla.Speedtest

# Verificar (notar que el binario se llama `speedtest`, no `ookla-speedtest`):
speedtest --version
```

> **Nota sobre el nombre del binario:** el adapter `RealSpeedTestController`
> busca el binario con `shutil.which("speedtest")`
> (`src/gnd/network/real_speed_test_controller.py:46`). El nombre que
> reporta Ookla como "Speedtest CLI" se instala como `speedtest` (o
> `speedtest.exe` en Windows). NO uses `ookla-speedtest` como nombre
> de PATH — eso no lo encuentra.

 Después de instalarlos, **cerrá y reabrí** la PowerShell (o re-activate el
venv) para que el `PATH` actualice — `wscript.exe` y `python.app.exe` no
heredan cambios de `PATH` de la sesión ya abierta.

### Cómo correr GND

| Modo | Command | Cuándo |
|---|---|---|
| **Dev (consola)** | `python -m gnd` | Desarrollo, ver stderr, captura de logs en tiempo real |
| **Launcher GUI** | Doble-click en `GND.lnk` (escritorio) | Uso diario como app de Windows, sin terminal visible |
| **Launcher debug** | `cscript //nologo launch_gnd.vbs 2> gnd_console_debug.log` | Debug del launcher VBS mismo (no de Python) |
| **Directo VBS** | `wscript launch_gnd.vbs` | Igual que el `.lnk` pero sin acceso directo |

### Cerrar GND / limpiar zombies

```powershell
# Limpiar procesos pythonw colgados (no mata el host de opencode):
Stop-Process -Name "pythonw" -Force
```

> **ADVERTENCIA:** NUNCA corras `Stop-Process -Name "wscript"`. `wscript.exe`
> es el host de procesos que también usa opencode (y otros launchers VBS de
> Windows). Matarlo termina tu sesión de opencode y cualquier otro script VBS
> que esté corriendo en el usuario. Para limpiar: mata `pythonw` (el hijo), no
> `wscript` (el host).

---

## Verificación local (CI local)

```powershell
.\scripts\check.ps1
```

Equivale a correr `ruff check .`, `vulture`, `black --check .` y `pytest` en
secuencia (vía `python -m <tool>` para robustez); detiene la ejecución al
primer error. Requiere el venv activado (`.\.venv\Scripts\Activate.ps1`).

### pytest

- **Default (CI):** `pytest` corre solo unit tests (`-m "not integration"` —
  seteado en `pyproject.toml:addopts`). No requiere red real.
- **Integration tests:** `pytest -m integration` corre tests contra red real
  (ping/traceroute a internet). No corren en CI offline.
- **Flake conocido:** tests UI que abren `tk.Tk()` real
  (`test_warp_comparison_section.py`, `test_speed_test_comparison_section.py`)
  pueden flakear ~10% bajo carga (suite completa) por un race de Tcl/Tk init
  en Python 3.12/Windows. **Pasan aislados.** Re-corre solo esos archivos si
  fallan. Documentado como `# FLAKYKNOWN (lesson 12b.4.2)` en sus docstrings.

---

## Features y flags de configuración

Tabla completa de features opt-in (todas `enabled=False` por default — YAGNI,
Regla 9.5). Ver `src/gnd/config/__init__.py` para el contrato exacto de cada
campo.

| Feature | Flag (config.toml) | Default | Descripción |
|---|---|---|---|
| Notificaciones de escritorio | `[notifications] enabled` | `false` | Toast nativo del OS post-run (plyer). `notify_only_on_issues=true` suprime verdict EXCELENTE |
| Reportes periódicos | `[reports] enabled` | `false` | Scheduler con `threading.Timer` genera reporte Markdown semanal/mensual |
| WARP Comparison | `[warp_comparison] enabled` | `false` | 2 runs (WARP off/on) + restore + deltas por `provider`. Requiere `warp-cli` |
| Speed Test | `[speed_test] enabled` | `false` | `speedtest` (Ookla CLI) bajo demanda, pestaña dedicada. Requiere `speedtest` en PATH |
| Wi-Fi/Ethernet snapshot | `[network] inspect_interface` | `false` | Detecta interfaz activa via `netsh wlan show interfaces` (Windows) |
| DNS timing | `[dns] enabled` | `false` | Medir tiempo de resolución DNS como etapa independiente del ping |
| IPv6 probes | `[targets] *_ipv6` | `None` (off) | Si not None, duplica specs de probes v6 además de v4 (opt-in) |
| Multi-juego | `[game_detection] active_game` | `"league_of_legends"` | `"league_of_legends"` \| `"valorant"`. Valor no reconocido crashea al arrancar (fail-fast) |
| Logging retención | `[logging] retention_days` | `30` | `TimedRotatingFileHandler` purga logs JSONL más viejos que N días en cada rotación |
| Console level | `[logging] console_level` | `"WARNING"` | Nivel del handler stderr (el archivo captura siempre el level del root) |

Features core (siempre activas, no tienen flag): ping, traceroute, monitoreo,
baseline histórico, Network Score, motor de recomendación, gráficos, export
Markdown bajo demanda (botón UI), logging JSON estructurado.

---

## Arquitectura (resumen)

Clean Architecture estricta. Detalle completo en
[`docs/ARCHITECTURE.md`](./ARCHITECTURE.md). Estructura del paquete:

```
src/gnd/
├── models/           # Entidades inmutables (dataclass frozen)
├── domain/           # Puertos (Protocol) + Fakes in-memory
│   ├── ports/        # PingRunner, TracerouteRunner, ConnectionInspector,
│   │                 # DiagnosticsRepository, RecommendationEngine,
│   │                 # GameDiagnosticsModule, WarpController, etc.
│   └── fakes/        # Implementaciones fake para tests sin red/DB
├── network/          # Adaptadores de red real (ping, tracert, netsh, warp,
│                     # speedtest, subprocess helpers con CREATE_NO_WINDOW)
├── application/      # Casos de uso (RunFullDiagnostics, WarpComparison,
│                     # SpeedTestComparison)
├── analysis/         # Baseline histórico + Network Score
├── recommendations/  # Motor de reglas (7 reglas + 2 constraints)
├── database/         # SQLite (schema v3 con family en probes/traceroutes)
├── visualization/    # 5 gráficos matplotlib (PRD §10)
├── export/           # Renderer Markdown de DiagnosticRun (función pura)
├── reports/          # Composer Markdown de período + scheduler periódico
├── notifications/    # Adapter plyer + formatter de notificaciones
├── logging/          # JsonFormatter + RunContextAdapter + configure_logging
├── diagnostics/games/ # Módulos por juego (league_of_legends, valorant)
├── config/           # GndSettings (Pydantic, carga config.toml / env)
├── ui/               # tkinter dark mode (MainWindow + 6 secciones)
└── __main__.py       # Entrada `python -m gnd` + wiring via composition_root
```

**Invariants clave** (Protocolos Críticos, ver `docs/ENGINEERING_PRINCIPLES.md`):

- Separación estricta `models/` vs `domain/` (ningún archivo importa `psutil`,
  `sqlite3`, `subprocess`, `socket`).
- Dependency Injection por constructor; wiring único en `composition_root.py`.
- `provider` es un string opaco en `analysis/`/`database/` — los módulos de juego
  lo declaran en un VO (`GameEndpoint(host, provider, family)`), las capas
  inferiores no saben qué juego es.
- EP §1.2: la app nunca propaga excepciones a la UI — todo falla con log
  estructurado y degradación funcional.

---

## Troubleshooting / FAQ (fresh PC)

**La UI no abre al hacer doble-click en `GND.lnk`.**
- Verificá que el venv esté created: `Test-Path .\.venv\Scripts\pythonw.exe` (debe dar `True`). Si falta, correr `python -m venv .venv && .\.venv\Scripts\pip install -e ".[dev]"`.
- Si el venv existe pero no abre, capturá stderr del launcher: `cscript //nologo launch_gnd.vbs 2> gnd_console_debug.log` y revisá el log.
- Si hay procesos `pythonw` colgados de corridas previas: `Stop-Process -Name "pythonw" -Force` y reintentá.

**`pip install -e ".[dev]"` falla con error de `ExternalExecutionPolicy` o `Activate.ps1 cannot be loaded`.**
- Política de ejecución de PowerShell restrictiva (default en algunos Windows). Una sola vez, como admin:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```
- Después de eso, Activate.ps1 funciona en sesiones no-admin.

**`python` o `pip` no se encuentran en PowerShell (aunque Python está instalado).**
- El installer oficial de Python tiene un checkbox "Add Python to PATH" que a veces se queda sin marcar. Reinstalá Python 3.12+ asegurándote de tildarlo, o agregá `%LOCALAPPDATA%\Programs\Python\Python312\` y `%LOCALAPPDATA%\Programs\Python\Python312\Scripts\` a `PATH` manualmente.

**El botón "Run WARP Comparison" quedó deshabilitado.**
- Falta `warp-cli` en `PATH`. Instalarlo (ver "Dependencias externas opt-in" arriba) y reabrir la PowerShell / re-lanzar GND.
- Verificar: `warp-cli --version` debe responder.

**El botón "Run Speed Test" quedó deshabilitado.**
- Falta el binario `speedtest` (no `ookla-speedtest`) en `PATH`. Instalarlo (ver arriba) y reabrir.
- Verificar: `speedtest --version` debe responder.

**"detection of game server" reporta "no partida activa" pero LoL está corriendo.**
- La detección usa la Live Client Data API de Riot (`https://127.0.0.1:2999/liveclientdata/`), que solo está disponible **durante una partida en curso** (no en lobby, picker, ni post-game). El diagnóstico core (gateway/DNS/Riot infra/traceroute) funciona igual — solo la etapa de "server de partida activa" se salta.
- El proceso detectado es `League of Legends.exe` (configurable en config.toml como `[game_detection].process_names`), NO `LeagueClientUx.exe` (que es el client launcher, no el juego).
- Para Valorant: el proceso es `VALORANT-Win64-Shipping.exe` (no `VALORANT.exe`, que es el launcher).

**Logs y DB se guardan en dónde?**
- Todo en `%APPDATA%\GND\`:
  - `history.db` — SQLite con runs históricos.
  - `logs\gnd_YYYYMMDD.jsonl` — logs JSON estructurados (1 archivo por día, rotación a medianoche, retención 30 días default).
  - `reports\*.md` — reportes periódicos (si `[reports].enabled=true`).
- Para limpiar logs antiguos: borrar los `.jsonl` más viejos a mano, o ajustar `[logging].retention_days` y esperar la próxima rotación medianoche. Para resetear la DB: borrar `history.db` (se recrea al próximo run — todos los baselines se pierden).

**La app crashea al arrancar con `ValueError: game_detection.active_game no reconocido`.**
- El string en `config.toml` bajo `[game_detection] active_game` no es `"league_of_legends"` ni `"valorant"`. Fail-fast intencional (config estática mal formada, no runtime de red). Verificar spelling exacto.

**No veo la pestaña de Charts o WARP Compare.**
- Las pestañas se construyen condicionalmente según los kwargs que MainWindow reciba (wiring en `composition_root.py` y `__main__.py`). Si `[warp_comparison].enabled=false` (default), la pestaña existe pero el botón está deshabilitado. Si `[speed_test].enabled=false`, igual. Si falta `series_source` (caso de tests), la pestaña Charts muestra empty state. En producción nunca debería faltar.

**`pytest` flakea en tests UI (tkinter `init.tcl`).**
- Known flake (lesson 12b.4.2). Tests que abren `tk.Tk()` real bajo carga (suite completa) pueden fallar ~10% por un race de init Tcl/Tk en Python 3.12/Windows. Solución: re-corre solo esos archivos aislados:
  ```powershell
  pytest tests/test_warp_comparison_section.py tests/test_speed_test_comparison_section.py
  ```
  Siempre pasan aislados.

---

## Reportar issues / contribuir

Issues: https://github.com/SantiagoSuarezL/gnd/issues
Para feedback sobre opencode (la herramienta), no sobre este repo:
https://github.com/anomalyco/opencode/issues
