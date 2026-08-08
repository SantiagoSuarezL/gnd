# Lessons Learned — Game Network Diagnostics (GND)

> MEMORIA ACTIVA. Se lee completa al inicio de sesión.
> Reglas de Fases 1-11: ver `lessons_learned_archive.md` (NO se lee automático,
> solo por grep/keyword si la tarea actual toca un módulo de esa fase).
> Rotación de fases: este archivo guarda las reglas de las últimas 2 fases
> en detalle completo. Si al cerrar una fase nueva quedan reglas de 3+ fases
> atrás, las más viejas pasan verbatim a `lessons_learned_archive.md` y se
> reemplazan por una línea en el índice de archivadas abajo.
> Hoy: detalle activo = Fase 12b.4 (12b.4.1, 12b.4.2 flake, 12b.4.3 WARP restore, 12b.4.4, 12b.4.5) + Fase 12b.5 (12b.5.1) + Fase 13 (13.1) + Fase 14.0a (14.0a.1 DNS regional).

## Índice de reglas archivadas (Fases 1-9, 12b.1-12b.2, 12b.3)

- 1.1 Imports circulares (Enum + dataclass mismo archivo)
- 1.2 Prefijo `gnd.` obligatorio en paquete editable
- 1.3 `domain/` faltante en plan de Fase 0, cruzar con ARCHITECTURE.md
- 2.1-2.7 Capa de red: tests con mocks, parser cross-platform, markers integration, sandbox vs Windows, IP legacy Riot
- 3.1-3.3 DNS resolution guarda hostname no IP resuelta, config hostnames no IPs fijas, check.ps1 stderr bug
- 4.1 Score: probes faltantes se excluyen, no penalizan como 0
- 5.1-5.2 Motor de reglas: None ≠ degradado, firma de orquestador necesita baselines
- 6.1-6.6 psutil: import diferido, IP efímera vs hostname estable, DoD in-vivo, filtrado CGNAT/TEST-NET, anti-telemetría, raddr polimórfico
- 7.1-7.2 Parser tracert dual EN/ES, culprit hop = sostenido no pico puntual
- 8.1-8.6 Monitoreo WinMTR: aggregación por hop_number, MonitoringSession snapshot válido, DI Sleeper+Clock, atomicidad session+hops, schema v2 retro-compat, wall-clock duration
- 9.1-9.6 Threading SQLite factory pattern, ThreadPoolExecutor pings, baselines cache, anomalías en veredicto, Vulture código muerto, hops loss>0 explícitos
- 10.1-10.5 matplotlib embebido: plt.close(fig) en refresh, backend Agg + close("all"), SeriesDataSource no cierra conn, ChartsSection empty state en renderer, packet_loss auto-zoom piso 5%
- 11.1 LoggerAdapter no contextvars (NO pre-construir alternativas "para el futuro")
- 11.2 JsonFormatter omite None en campos opcionales (tight JSON, jq-friendly)
- 11.3 Eventos estructurados con `event`+`stage` como keys queryables, naming `<namespace>.<verbo>`
- 11.4 Vulture falsos positivos en overrides stdlib (process/format/__eq__) — whitelistear, no borrar
- **12a.1-12a.4.3** ver `lessons_learned_archive.md` (rotación 3+ fases)
- **12b.1.1-12b.1.2** ver `lessons_learned_archive.md` (rotación 3+ fases): Export renderer función pura + escapado Markdown tablas vs prosa
- **12b.2.1-12b.2.2** ver `lessons_learned_archive.md` (rotación 3+ fases): Import diferido plyer + filtrado notify_only_on_issues omitir > toast vacía
- **12b.3.1-12b.3.2** ver `lessons_learned_archive.md` (rotación 3+ fases): Lectura segregada de runs históricos (nuevo puerto + bulk reconstruction, NO extender repo escritura) + threading.Timer one-shot rearme manual en `finally`
- **12b.4.1** ver `lessons_learned_archive.md` (rotación 3+ fases): Comparación WARP: nuevo caso de uso que compone el existente + controlador de estado, NO extender caso de uso base
- **12b.5.1** Speed test: nuevo caso de uso que compone diagnóstico + speed test, no extender RunFullDiagnostics (ver detalle abajo)

---

## Regla de Oro 12b.2.1 [Import diferido de libs de infraestructura: plyer, no solo psutil]

**Problema (Fase 12b.2):** Adapter `PlyerDesktopNotifier` Depends de `plyer.notification`. Si la lib no esta instalada en un env sin sync de pyproject (fresh CI runner, Docker minimal, sandbox sin deps actualizadas), el `import plyer` top-level truena el `composition_root` al arrancar — la UI no carga. Protocolo 8 fue keyword "psutil import diferido" pero la regla general es "toda lib de infraestructura externa (psutil, plyer, future libs C-extension) se importa DEFERIDO dentro de `__init__` del adapter, no top-of-module".

**Decisión:** PlyerDesktopNotifier hace `from plyer import notification` dentro de `__init__`, captura `ImportError` y marca `_available=False`. Las subsiguientes `.notify()` se vuelven no-op con log `event="notification.skip"` + `reason="plyer_unavailable"`. El wiring nunca crashea al arrancar por falta de lib — EP §1.2 respetado desde el constructor.

**Regla de Oro:** *Generalizar Protocolo 8: toda lib de infraestructura externa (no stdlib) importada en un adapter se importa DENTRO del `__init__` (o método), nunca top-of-module. Capturar `ImportError` y marcar un flag `_available`; el método publico se vuelve no-op con log si está caído. EP §1.2 se respeta desde el constructor, no desde el caller — el wiring nunca crashea al arrancar por lib faltante. Aplica a psutil (Fase 6), plyer (Fase 12b.2), y toda futura lib C-extension / platform-binding.*

---

## Regla de Oro 12b.2.2 [Filtrado notify_only_on_issues: omitir > toast vacía]

**Problema (Fase 12b.2):** Settings `notify_only_on_issues=True` pide suprimir notif para verdict EXCELENTE (safe_to_play). Donde suprimir — en el adapter (no llamar plyer) o en el formatter (devolver un signal de "no notificar")?

**Decisión:** El formatter `build_run_notification` devuelve `DesktopNotification | None`. Si `notify_only_on_issues=True` y verdict=safe_to_play, devuelve `None`. El caller (MainWindow) hace no-op con log `notification.skip` (no llama al adapter). NO devolver una `DesktopNotification(title="", message="")` — el VO valida campos no vacíos (raise), y aunque los permitiera, una toast vacía es peor que no-toast (el OS la muestra igual con header sin contenido, UX rara).

**Regla de Oro:** *Para features de "suprimir notif según un filtro", preferir un signal explícito (`None` del formatter) sobre emitir una payload vacía. El caller decide no-op con log estructurado (`event="notification.skip"`), el adapter nunca recibe una payload degenerada. Misma lógica que Regla 11.2 (omitir > null en JSON): omitir > toast vacía. El VO valida title/message no vacíos para que esto no se relaje accidentalmente.*

---

## Regla de Oro 12b.4.1 [Comparación WARP: dos runs completos + restore estado original, sin extender caso de uso existente]

**Problema (Fase 12b.4):** La feature de comparación con/sin Cloudflare WARP requiere ejecutar el diagnóstico completo DOS veces (WARP off + WARP on) y comparar resultados. El caso de uso existente `RunFullDiagnostics` orquesta un solo run. ¿Extender ese caso de uso con flags, o crear uno nuevo?

**Decisión:** Nuevo caso de uso `WarpComparisonUseCase` que compone (no hereda) `RunFullDiagnostics` + `WarpController`. Flujo: 1) Guarda estado WARP original, 2) disable → run (warp_off), 3) enable → run (warp_on), 4) restore estado original, 5) computa deltas (warp_on - warp_off: positivo = mejor con WARP) y veredicto. El `WarpController` Protocol abstrae `warp-cli` subprocess; `RealWarpController` usa import diferido (Regla 12b.2.1). Config `WarpComparison(enabled=False, restore_original_state=True, timeout_seconds=30, pause_between_runs_seconds=2.0)` opt-in.

**Regla de Oro:** *Para features que orquestan MÚLTIPLES corridas de un caso de uso existente con estado mutado entre medio (WARP on/off, speed test antes/después), crear un NUEVO caso de uso que COMPONGA el existente + un controlador de estado (WarpController, SpeedTestController), NO extender el caso de uso original con flags condicionales. El nuevo caso de uso es dueño del lifecycle: save state → mutate → run → mutate → run → restore → compute deltas. Separación de responsabilidades: el caso de uso base (RunFullDiagnostics) sigue siendo "una corrida"; el comparador es "dos corridas + análisis".*

---

## Regla de Oro 12b.5.1 [Speed test: nuevo caso de uso que compone diagnóstico + speed test, no extender RunFullDiagnostics]

**Problema (Fase 12b.5):** La feature de speed test bajo demanda requiere ejecutar `ookla-speedtest` CLI y comparar las métricas de ancho de banda con el diagnóstico de red. El caso de uso existente `RunFullDiagnostics` orquesta un solo run de probes/traceroutes. ¿Extender ese caso de uso con speed test inline, o crear uno nuevo?

**Decisión:** Nuevo caso de uso `SpeedTestComparisonUseCase` que compone (no hereda) `RunFullDiagnostics` + `SpeedTestController`. Flujo: 1) Ejecuta diagnóstico completo (RunFullDiagnostics.execute), 2) Ejecuta speed test (SpeedTestController.run), 3) Computa deltas entre latencia/jitter/packet loss del gateway (diagnóstico) y el speed test, 4) Genera veredicto. El speed test se ejecuta DESPUÉS del diagnóstico para no interferir con los probes (un speed test consume ancho de banda). El `SpeedTestController` Protocol abstrae `ookla-speedtest` subprocess; `RealSpeedTestController` usa import diferido (Regla 12b.2.1). Config `SpeedTest(enabled=False, timeout_seconds=120)` opt-in.

**Regla de Oro:** *Para features que añaden una medición de ancho de banda o subprocess externo al pipeline de diagnóstico, crear un NUEVO caso de uso que COMPONGA el existente + un controlador (SpeedTestController), NO extender RunFullDiagnostics con lógica de speed test. El speed test consume ancho de banda y puede durar 30-90s — ejecutarlo DESPUÉS del diagnóstico (no durante) para no afectar probes/traceroutes. El nuevo caso de uso es dueño del lifecycle: run diagnostic → run speed test → compute deltas → return result. Separación de responsabilidades: RunFullDiagnostics sigue siendo "un run de probes"; el comparador añade "speed test + análisis".*

---

## Regla de Oro 13.1 [Extensibilidad multi-juego: módulo de juego que expone provider, orquestador kwarg opcional backwards-compat]

**Problema (Fase 13):** Agregar un juego nuevo (Valorant) sin tocar `analysis/`, `recommendations/`, ni `database/` (DoD). El orquestador `RunFullDiagnostics` estaba acoplado a Riot: hardcodeaba `_PROVIDER_RIOT_PUBLIC`/`_PROVIDER_RIOT_GAME_SERVER`, y la "Etapa 3b" pingueaba el server detectado con `provider="riot_game_server"`. ¿Cómo abstraer el "juego activo" sin romper los 843 tests existentes ni tocar las capas inferiores?

**Decisión:** Protocol `GameDiagnosticsModule` (`runtime_checkable`) con 4 métodos:
  1. `public_endpoints() -> list[GameEndpoint]` — VO `GameEndpoint(host, provider, family)`. **Clave: el módulo declara su `provider`** (no `list[str]` del spec literal §7), así `analysis/` trata el provider como string opaco (key de baseline) sin saber qué juego es. Para LoL: `provider="riot_public"`; Valorant: `provider="valorant_public"` → baselines separados sin tocar analysis.
  2. `process_names()` — set de procesos del cliente del juego.
  3. `detect_active_server()` — delega al `ConnectionInspector` inyectado (LoL reusa `ActiveGameServerDetector` con anti-telemetría; no se reescribe).
  4. `game_server_provider()` — provider del probe-al-server (ej. `"riot_game_server"`, `"valorant_game_server"`) — separado del de `public_endpoints` (mismo split `_PROVIDER_RIOT_PUBLIC` vs `_PROVIDER_RIOT_GAME_SERVER` de hoy).

`RunFullDiagnostics` añade kwargs `game_module=None` (backwards-compat total: si `None`, cae al path Riot hardcodeado; si presente, specs de pings/traceroutes/detección vienen del módulo con sus providers). `composition_root` añade `build_game_module(inspector)` que mapea `settings.game_detection.active_game` a la impl ("league_of_legends" | "valorant"), fail-fast `ValueError` para valor no reconocido. DoD blindado con 3 tests estáticos: `inspect.getsource` + `pkgutil.walk_packages` verifica que `analysis/`/**`recommendations/`/`database/`** no mencionan "valorant" (si lo hicieran, rompería el DoD).

**Regla de Oro:** *Para features de extensibilidad por-plugin (multi-juego, multi-backend, multi-formato), la abstracción clave es un `GameDiagnosticsModule`-style Protocol donde el plugin DECLARA los identificadores que las capas inferiores usan como keys opacas (provider de baseline, nombre de módulo). NO pasar `list[str]` y dejar que el orquestador adivine/hardcodee el provider — el provider es dato del plugin, va en un VO (`GameEndpoint`). El orquestador consume el Protocol vía kwarg OPCIONAL (backwards-compat: si `None`, fallback al path hardcodeado de la fase anterior) — así migrar callers es incremental y los tests previos no se rompen. Bíndice el DoD con tests estáticos (`inspect.getsource` sobre los paquetes que NO debían tocarse) — si una fase futura rompe el invariant, el test falla temprano en CI.*

---

## Regla de Oro 14.0a.1 [Hostnames regionales "Riot-direct": verificar empíricamente antes de meterlos al código]

**Problema (Fase 14.0a):** Plan original de 14.0 proponía usar
hostnames regionales del patrón `lq.<platformId>.lol.riotgames.com`
para el tier `regional_edge` — la fuente de la comunidad (gist
"`LAS_Network_Diagnostic.bat`" de Pulgafree) confirmaba `lq.la2` para
LA2, y la extrapolación por analogía sugería que el resto de
regiones seguía el mismo patrón. Antes de implementar, el usuario
exigió verificación DNS empírica de CADA hostname candidato (solo
LA2 tenía verificación; el resto era "inferido").

**Verificación con `Resolve-DnsName -DnsOnly` contra 22 candidatos
de patrones `lq.<platformId>`, `lq.<short>`, `chat.<platformId>`:**

Resolución DNS de hostnames regionales de LoL — Riot-direct vs
Cloudflare-anycast:

| platformId | Hostname                  | Resolución              | Clasificación                  |
|------------|---------------------------|-------------------------|--------------------------------|
| NA1        | `lq.na.lol.riotgames.com` | `66.151.54.141`         | Riot-direct (usable)           |
| EUW1       | `lq.eu.lol.riotgames.com` | `64.7.194.21`           | Riot-direct (usable)           |
| LA2        | `lq.la2.lol.riotgames.com` | Cloudflare `104.16.x`    | CF-anycast (= proxy genérico)  |
| BR1        | `lq.br.lol.riotgames.com`  | Cloudflare `104.16.x`    | CF-anycast                     |
| TR1, RU, KR | `lq.<id>.lol.riotgames.com` | Cloudflare `104.16.x`  | CF-anycast                     |
| LA1, EUNE1, JP1, OC1, LAN, LAS, SEA | (varios)        | NXDOMAIN                | No existen                     |

**Solo 2 regiones de las ~14 tienen hostnames Riot-direct usables**.
La mayoría resuelve a Cloudflare anycast (104.16.x) — el mismo
proxy genérico que ya teníamos con `auth.riotgames.com`, o sea,
pinguearlos no aporta signal nueva. La comunidad había publicado
`lq.la2` como "Riot-direct" pero hoy resuelve a CF — migración de
LATAM a Cloudflare y el gist quedó desactualizado.

**Decisión (Opción 3):** implementar solo el tier `exact_ip` (la IP
cruda que el LCU expone via `gameClient.serverIp` cuando hay partida
InProgress). Este tier funciona para **TODAS las regiones** porque
usa información directa del cliente del usuario, no necesita mapping
de hostnames pre-construido. El tier `regional_edge` queda pausado
para una futura Fase 14.0b si la comunidad encuentra más hostnames
Riot-direct confiables.

**Regla de Oro:** *Cuando se van a meter al código hostnames DNS
descubiertos por la comunidad (no oficiales de Riot), **verificar
empíricamente con `nslookup`/`dig`/`Resolve-DnsName` que cada uno
resuelve a IPs del publisher (no a IPs de CDN/anycast del mismo
proxy genérico que ya tenemos)**. Incluir el mapping solo con las
regiones confirmadas, y hacer fallback explícito a comportamiento
previo para las demás — no inventar hostnames. Distinguir hostname
"Riot labeled" (resuelve a Cloudflare) de hostname "Riot-direct"
(IP del ASN de Riot); solo el segundo aporta signal nueva en
medición de red. La comunidad publica findings que caducan cuando
Riot migra infra ≠ verdad presente; confiar ciegamente en patrones
no verificados mete código idéntico al fallback disfrazado de
mejora — sobre-vender al usuario sin mejora real.*

---

## lesson 12b.4.2 [FLAKE: tkinter `init.tcl` bajo pytest suite completa en Windows]

**Síntoma (post-Fase 13):** tests que llaman `tk.Tk()` real —
`test_warp_comparison_section.py::TestWarpComparisonSection::*` y
`test_speed_test_comparison_section.py::TestSpeedTestComparisonSection::*` —
fallan intermitentemente (~10% de las corridas) con:
`_tkinter.TclError: Can't find a usable init.tcl in the following dirs: {C:\...\tcl\tcl8.6}` +
`couldn't read file "...init.tcl": No error`. Pasa SIEMPRE aislado
(`pytest tests/test_xxx_section.py`), falla SÓLO bajo carga (suite completa).

**Causa raíz:** bug ambiental de tkinter + Python 3.12 en pytest bajo Windows.
Múltiples `tk.Tk()` consecutivos (uno por test) abren handles a
`init.tcl`/`tcl8.6/`; si un test anterior no lo cerró perfectamente o si
Windows file-locking interfiere, el siguiente `tk.Tk()` no encuentra/init.tcl
usable. NO es bug del producto — el código tkinter de GND es correcto.
`root.destroy()` en `finally` está bien pero Tcl/Tk init tiene race interno.

**Decisión:** NO fixear (no es bloqueante). Documentar como known issue:
- Comentario `# FLAKYKNOWN (lesson 12b.4.2)` en los module docstrings de ambos
  tests (`test_warp_comparison_section.py`, `test_speed_test_comparison_section.py`).
- Workaround actual: si la corrida falla por este flake, re-corre solo los tests
  UI afectados (`pytest tests/test_xxx_section.py`) — siempre pasan aislados.
- Para CI futuro (cuando haya CI): usar `-p no:randomly` o correr los tests
  UI en un worker separado, o marcar los tests con `@pytest.mark.flaky(reruns=2)`
  (requiere `pytest-rerunfailures`).
- **No eliminar `root = tk.Tk()` real** — los tests mockear tkinter pierden
  valor (no prueban la render real que joke bug 2 del speed test atrapó).

**Por qué no es bug del producto:** la UI del producto abre UN solo `Tk()` al
arrancar (en `MainWindow.run()`) y vive por toda la sesión — no hay race.
El flake SOLO aparece en la suite de tests donde ~14 tests abren/cierran root
en segundos.

**Lección general:** tests UI que abren `tkinter.Tk()` real en suite grande
pueden flakear por issues de Tcl/Tk init race. Documentar con `# FLAKYKNOWN`
+ referencia a la lesson, NO silenciar con `try/except` (mascararía bugs
reales). Re-correr aislado es el workaround; `[tool.pytest.ini_options]`
con `-p no:cacheprovider` ayuda pero no fixea.

---

## Regla de Oro 12b.4.3 [WARP restore: replicar modo/protocolo o fail-safe, NO restaurar a ciego]

**Problema (Post-Fase 13, sesión 2):** el adapter `RealWarpController` de
Fase 12b.4 usaba `warp-cli status --output-format=json` — flag **inexistente**
en warp-cli 2026.6.x (la version real del usuario). El adapter crasheaba con
`CalledProcessError`, capturado por try/except, devolvía `WarpStatus(
connected=False, registration_status="error", ...)` SIEMPRE — la feature
entera de comparación WARP estaba rota silenciosamente desde la Fase 12b.4
(se testeo solo con Fake, núnca contra warp-cli real). Adicionalmente, el
restore solo modelaba `connected=True/False` — NO el "modo" (UDP/MASQUE) ni
el "protocolo del túnel" (WireGuard/MASQUE). Si el usuario prendía WARP a
mano en modo UDP (=WireGuard) y corría la comparación, el restore llamaba
`warp-cli connect` que usa el protocolo default de settings (cambió entre
versiones, ahora MASQUE), perdiendo el modo elegido.

**Investigación empírica del CLI (output del usuario):**
- `warp-cli status` solo acepta `--no-paginate` y `-h`. NO `--output-format=json`
  ni `-j`. Output texto plano: `Status update: Connected\nNetwork: healthy`.
- `warp-cli settings list` expone multiline: `(default) Mode: Warp` (modo
  general) y `(network policy) WARP tunnel protocol: MASQUE` (protocolo
  del túnel). Sin flag JSON, regex multiline lo parsea confiablemente.
- `warp-cli mode <warp|proxy|doh|warp+doh|dot|warp+dot|tunnel_only>` setea
  modo general. `warp-cli tunnel protocol set <MASQUE|WireGuard>` setea
  protocolo. `connect` NO acepta `--mode` — usa el protocolo ya configurado
  en settings. **"UDP" en la app de Cloudflare = `tunnel_protocol=WireGuard`**
  (legacy), MASQUE = HTTP/3 (default 2026.6.x).

**Decisión (Opción 2: fix completo + fail-safe de red):**
1. **Adapter real fix:** `get_status()` ahora usa `status --no-paginate`
   texto plano + regex `_STATUS_RE = re.compile(r"Status update:\s*(\w+)")`.
   Nuevo método `_read_settings()` corre `warp-cli settings list` (timeout
   10s, no crashea el get_status si falla) y parsea `_MODE_RE` +
   `_PROTO_RE` → `_WarpSettings(mode, tunnel_protocol)`. Si el parseo falla
   (formato cambió en version futura), devuelve `_WarpSettings(None, None)`.
   El `WarpStatus` retornado por `get_status()` ahora incluye `mode` +
   `tunnel_protocol` (None = no detectado, signal fail-safe).
2. **Protocol extendido:** `WarpController.set_mode(m)` /
   `set_tunnel_protocol(p)` declarados en el Protocol + implementados en
   adapter real (`warp-cli mode <m>` / `warp-cli tunnel protocol set
   <WireGuard|MASQUE>`).
3. **Use case restore fiel:** `_restore_original_state` ahora: si
   `connected=False` → `disable()` (simétrico, igual que antes). Si
   `connected=True` Y `mode != None` Y `protocol != None` → `set_mode(m)`
   + `set_tunnel_protocol(p)` + `enable()` (restore fiel). Si `connected=True`
   PERO `mode=None` o `protocol=None` → **fail-safe**: NO `enable()` ciego
   (dejaría WARP en MASQUE default, perdiendo el modo elegido). En su
   lugar `disable()` + log `warp_comparison.restore_skip_mode_unknown` +
   devuelve warning legible que el use case adjunta al
   `WarpComparisonResult.restore_warning` via `dataclasses.replace` (result
   es frozen). La UI muestra el warning al final del explanation_text con
   prefijo `[!]`.
4. **`execute()` refactor:** el result se guarda en var de scope exterior
   (no `return result` adentro del try), el restore corre en `finally`, si
   devuelve warning, se adjunta al result con `dataclasses.replace` antes
   del return final (afuera del try).

**Regla de Oro:** *Cuando una feature orquesta un estado externo mutado
(adapters de red/CLI/IO: WARP on/off, proxies, network interfaces) y debe
restaurarlo al terminar, el "estado" no es solo on/of — puede tener
sub-dimensiones (modo, protocolo, configuración). El adapter debe DETECTAR
el estado completo antes de mutarlo y REPLICARLO en el restore, no solo
on/off. Si la detección de alguna dimensión falla (CLI expuso formato
distinto, parseo no matchea), **fail-safe explícito**: NO restaurar a ciego
al estado "default" del adapter (que puede ser distinto del default del
usuario) — dejar el estado donde quedó, loguear el gap y avisar al usuario
con un warning que adjunte al resultado. La inmutabilidad (frozen dataclass)
del result se preserva via `dataclasses.replace`, no via mutación directa.
Bíndice el parseo del CLI externo con tests mockeando `subprocess.run` y
scripteando el stdout — nunca asumas el formato del CLI; las versiones
cambian y los tests con Fake no detectan formatos que no existen en el
adapter real.*

---

## Regla de Oro 12b.4.4 [Race condition: subprocesses async NO son sync, hay que POLL con timeout]

**Problema (Post-Fase 13 sesión 3):** el adapter `RealWarpController` de
Fase 12b.4 asumía que `warp-cli connect` es sync — bloquea hasta que el
túnel esté conectado. **No es así**: `warp-cli connect` bloquea solo hasta
que el daemon acepta el comando y devuelve; el daemon transiciona async
a `connecting` y luego a `connected` en 1-3s típicamente. El use case
arrancaba la fase de mediciones inmediatamente con `time.sleep(1.0)` ciego
y si el daemon estaba en `connecting`, los pings/DNS se ejecutaban contra
una interfaz de red en estado intermedio y reportaban timeouts/DNS failed
erróneos (red rota cuando en realidad era solo estado transitorio).

Bug crítico detectado in-vivo con warp-cli 2026.6.850.0: el log del usuario
mostraba `WARP enable no conectó: connecting` DOS veces en corridas
distintas, seguido de pings que fallan con `DNS resolution failed` y
`timeout` hacia riot_public y gateway local — mediciones inválidas
reportadas como válidas.

**Decisión:** poll de status con timeout configurable, NO sleep ciego fijo.
- `_wait_for_warp_state(target_state, timeout_s, poll_interval_s)`:
  loop que llama `get_status()` cada `poll_interval_s` hasta alcanzar
  `target_state` o agotar timeout. Raises `WarpError` con mensaje
  claro si timeout.
- DI completa: `Sleeper` Protocol (mismo patrón que RouteMonitor Regla 8.3)
  para tests deterministas con fake sleeper; `PerfClock` Protocol
  para tests con fake clock (NO usar `time.perf_counter()` directo).
- Timeouts configurables en `WarpComparisonParams`: `enable_timeout_s=15`,
  `disable_timeout_s=10`, `poll_interval_s=0.5`. Default razonable para
  producción; ajustable via config si hay redes lentas.
- `WarpError` raised en timeout → capturado en `execute()` que devuelve
  `WarpComparisonResult(overall_verdict="state_timeout", ...)` con
  mensaje explicando que se abortó la comparación. EP §1.2: nunca
  propaga excepción a la UI.
- UI: nueva rama `verdict_colors["state_timeout"] = "#ce9178"` (orange)
  + status_label muestra "Comparación abortada: WARP no transicionó al
  estado objetivo" en lugar de "Comparación completada".

**Regla de Oro:** *Cuando una feature invoca un subprocess CLI externo
para mutar un estado del sistema (`warp-cli connect`, `wg-quick up`,
`netplan apply`, `netsh wlan connect`, etc.), NUNCA asumas que el
comando bloquea hasta que el estado deseado esté activo. El subprocess
puede ser solo el "signal" al daemon; el daemon transiciona async.
Único mecanismo confiable para confirmar estado objetivo: poll de
status/query con timeout configurable, con abort explícito y
resultado claro si no se alcanza. Inyectar Sleeper + PerfClock para
tests deterministas (mismo patrón que cualquier loop con sleep+time en
el use case). Defaults razonables (15s enable, 10s disable, 0.5s poll)
pero configurables — redes lentas pueden necesitar timeouts más largos.*

---

## Regla de Oro 12b.4.5 [Providers con medición fallida: excluir del delta, NO contar como 0]

**Problema (Post-Fase 13 sesión 3):** el `_compute_provider_deltas` de
Fase 12b.4 sumaba probes con `p.stats is not None` y dividía por
`len(vals)` — si un lado (off/on) tenía todos los probes non-SUCCESS
(`stats=None` por invariante del modelo ProbeResult), `vals=[]` y
retornaba `0.0` por default. Resultado: provider con probe SUCCESS en
off (avg=30ms) y probe TIMEOUT en on se computaba como delta=-30 con
delta_pct=-100% — **falsa mejora perfecta** cuando en realidad era fallo
total de medición bajo WARP.

Bug detectado in-vivo con warp-cli 2026.6.850.0: el reporte mostraba
"cloudflare: avg_latency_ms=0.0, delta=-100%" como si WARP hubiera
mejorado cloudflare a cero, cuando en realidad todos los pings a
cloudflare (1.1.1.1) habían timeout-eado porque el diagnóstico se
ejecutó antes de que WARP terminara de transicionar a connected
(bug 12b.4.4 — mismo root cause, mismo escenario).

**Decisión:** Regla 4.1 estricta — probes non-SUCCESS se EXCLUYEN del
aggregate, NO se cuentan como 0. Si un lado (off/on) no tiene ningún
probe SUCCESS, ese lado se marca `None` y el delta/delta_pct también
`None`. La UI muestra "-" en las celdas y una columna extra `status`
con valor `FAILED` para que el usuario vea que no hubo medición.

Modelo `WarpComparisonDelta` extendido:
- `warp_off_value: float | None` (antes era `float`)
- `warp_on_value: float | None`
- `delta: float | None`
- `delta_pct: float | None` (ya era None antes; ahora explícito)
- `status: str = "ok"` — `"ok"` | `"failed_off"` | `"failed_on"` |
  `"failed_both"`. Distingue qué lado falló.

`WarpComparisonResult.verdict_explanation` ahora puede tener una línea
final `"Medición fallida (excluida): <provider>, <provider>"` para
los providers con fallo en alguna corrida. El análisis neutral/verdict
ignora providers con `delta=None` (no se cuentan como "mejoró" ni
"empeoró" artificialmente).

UI: tabla de deltas agregó columna `Status` (90px). Filas con
`status != "ok"` muestran `FAILED` en esa columna.

**Regla de Oro:** *Cuando una métrica agregada se computa a partir de
mediciones parciales (latencia, jitter, loss, score, etc.), NUNCA
cuentes una medición faltante como 0 — excluye (Regla 4.1 estricta).
Distinguí tres casos: medición exitosa en ambos lados → delta
computado; medición faltante en un lado → delta=None, status
indica qué lado falló; medición faltante en ambos → ambos lados None,
status="failed_both". La UI muestra "-" en valores/deltas faltantes y
una columna/línea explícita de status para que el usuario entienda
que la medición no se hizo (vs. un delta "perfecto" sospechoso).
La Regla 4.1 (excluir probes faltantes) aplica al aggregate del
provider — la Regla 12b.4.5 la formaliza al nivel de delta entre
dos runs. Errar en esto le da al usuario la falsa impresión de que
WARP/DNS/etc. "mejoró a cero" cuando en realidad nunca se midió.*

