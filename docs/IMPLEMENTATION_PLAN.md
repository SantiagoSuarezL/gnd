# IMPLEMENTATION PLAN — Game Network Diagnostics (GND)

**Versión:** 1.0
**Documentos relacionados:** `PRD.md`, `ARCHITECTURE.md`, `TECHNICAL_SPEC.md`

---

## Cómo usar este documento

Cada fase tiene un **Definition of Done** verificable. No se avanza a la fase siguiente sin que la anterior pase sus pruebas. Esto está pensado para ejecutarse con Opencode fase por fase, revisando el resultado antes de continuar.

---

## Fase 0 — Setup del proyecto

**Objetivo:** esqueleto del proyecto, sin lógica de negocio aún.

- Estructura de carpetas según `ARCHITECTURE.md` (`src/network`, `diagnostics`, `analysis`, `recommendations`, `database`, `visualization`, `config`, `models`, `ui`, `tests`, `docs`).
- `pyproject.toml` con Python 3.12+, `ruff`, `black`, `pytest`, `pydantic`, `psutil`.
- Configuración de `ruff` y `black` (line length, reglas activas) documentada en `ENGINEERING_PRINCIPLES.md`.
- CI local mínimo: script que corre `ruff check`, `black --check`, `pytest` en un solo comando.

**Definition of Done:** `pytest` corre (aunque sin tests reales todavía) y `ruff`/`black` no reportan errores sobre el esqueleto vacío.

---

## Fase 1 — Modelos de dominio y protocolos (sin red real)

**Objetivo:** todos los `dataclasses`/modelos de `TECHNICAL_SPEC.md` §1, y los `Protocol` de puertos (`PingRunner`, `TracerouteRunner`, `ConnectionInspector`, `DiagnosticsRepository`) definidos en `models/` y `domain/`.

- Tests unitarios de los modelos (validación de invariantes, ej. `LatencyStats` no permite `packet_loss_pct` fuera de 0–100).
- Implementaciones **fake/in-memory** de cada protocolo, para poder testear capas superiores sin tocar red real todavía.

**Definition of Done:** 100% de cobertura en `models/`, ningún import de `psutil`/`sqlite3`/`subprocess` dentro de `models/` o `domain/`.

---

## Fase 2 — Capa de red real (local + Internet)

**Objetivo:** implementar `PingRunner` real (ping local + Google/Cloudflare/Quad9), con el manejo de errores completo de `TECHNICAL_SPEC.md` §7.

- Implementar el fallback TCP SYN para diferenciar `FILTERED` de `UNREACHABLE`.
- Tests de integración contra targets reales (marcados como `@pytest.mark.integration`, no corren en CI sin red).
- Tests unitarios del parsing de resultados de `ping` (con outputs de ejemplo grabados como fixtures, no dependientes de red real).

**Definition of Done:** diagnóstico local + internet corre end-to-end contra red real sin crashear, incluso desconectando el cable de red a mitad de ejecución (simular con mock de timeout).

---

## Fase 3 — Base de datos y persistencia

**Objetivo:** esquema SQLite completo de `TECHNICAL_SPEC.md` §3, repositorio con Dependency Injection.

- Migraciones simples (versión de esquema en tabla `schema_version`).
- Repositorio implementa el `Protocol DiagnosticsRepository` del dominio.
- Tests con DB SQLite en memoria (`:memory:`).

**Definition of Done:** guardar y recuperar un `DiagnosticRun` completo (con probes y traceroutes anidados) pasa un test de round-trip exacto.

---

## Fase 4 — Análisis histórico y Network Score

**Objetivo:** `analysis/baseline.py` y `analysis/score.py` según `TECHNICAL_SPEC.md` §4.

- Baseline con media + desviación estándar por `provider`.
- Score ponderado 0–100 con la tabla de pesos definida.
- Tests con datasets sintéticos (ej. 30 días de latencias con una anomalía inyectada el día 31 → debe detectarse).

**Definition of Done:** el cálculo de baseline nunca mezcla `riot_public` con `riot_game_server`; test explícito que lo verifica.

---

## Fase 5 — Motor de recomendación

**Objetivo:** implementar las reglas ordenadas de `TECHNICAL_SPEC.md` §5 con explicaciones (`explanation: list[str]`) para cada veredicto.

- Cada regla es una función pura testeable de forma aislada.
- Tests de "todas las combinaciones relevantes" (matriz de escenarios: local malo, ISP malo, solo Cloudflare, solo Riot público, solo Riot game server, packet loss alto, jitter alto, todo bien).

**Definition of Done:** ninguna combinación de inputs produce `safe_to_play` si `packet_loss_pct > packet_loss_critical_pct` (test de invariante, no solo de caso feliz).

---

## Fase 6 — Detección de servidor de partida activo (Riot)

**Objetivo:** implementar `ActiveGameServerDetector` de `TECHNICAL_SPEC.md` §2.2.

- Escaneo de conexiones UDP del proceso vía `psutil`.
- Filtrado de IPs privadas/loopback.
- Confirmación cruzada opcional vía Live Client Data API.
- Manejo explícito de `AccessDenied` con mensaje claro a la UI.

**Definition of Done:** con una partida real de LoL corriendo, el detector encuentra una IP pública distinta de `riot_public` y la clasifica como `riot_game_server`. Sin partida activa, devuelve `None` sin error.

---

## Fase 7 — Traceroute y detección de hop culpable

**Objetivo:** wrapper sobre `tracert`, parsing a `TracerouteResult`, lógica de `culprit_hop_index` de `TECHNICAL_SPEC.md` §2.3.

- Tests con outputs de `tracert` grabados como fixtures (incluyendo hops que no responden, para verificar que no se tratan como error).

**Definition of Done:** dado un traceroute fixture con un salto de +80ms sostenido en el hop 7, el sistema identifica `culprit_hop_index = 7`.

---

## Fase 8 — Monitoreo continuo de ruta (estilo WinMTR)

**Objetivo:** sesiones de monitoreo con múltiples muestras en el tiempo, persistidas y vinculadas a un `run_id`.

**Definition of Done:** una sesión de 60 segundos de monitoreo produce estadísticas agregadas por hop (avg/worst/best/loss/jitter) coherentes con las muestras individuales.

---

## Fase 9 — UI (Current Status, Network Tests, Route Analysis, Historical Comparison, Recommendations)

**Objetivo:** UI dark mode, un clic ejecuta todo, sin bloquear la interfaz durante los sondeos (usar `asyncio` o threads con señales).

**Definition of Done:** el usuario puede ejecutar un diagnóstico completo y ver el resultado sin que la ventana se congele, con las 5 secciones del PRD visibles.

---

## Fase 10 — Visualización

**Objetivo:** gráficos de latencia en el tiempo, packet loss histórico, Cloudflare vs Google, latencia Riot histórica, mejores horas para jugar.

**Definition of Done:** los 5 gráficos del PRD se generan a partir de datos reales de la DB, no de datos de ejemplo hardcodeados.

---

## Fase 11 — Logging estructurado

**Objetivo:** logs JSON por ejecución con start time, tests ejecutados, fallos, excepciones, recomendación, duración.

**Definition of Done:** cada corrida completa produce un log parseable sin intervención manual.

---

## Fase 12 — Features avanzadas (post-v1)

Conjunto heterogéneo de 8 features post-v1 (PRD §7 should-have + nice-to-have,
TECHNICAL_SPEC §8). El alto impacto dispar entre features y el riesgo de mezclar
cambios que se cancelan entre sí motiva subdividir la fase en dos:

- **Fase 12a — Métricas locales + rotación/retención de logs.** Mediciones y
  capas nuevas que encajan en `RunFullDiagnostics.execute()` como etapas
  adicionales. Sin dependencias externas nuevas (solo stdlib + psutil ya
  presente). Riesgo bajo: extiende un orquestador ya probado, sin tocar Protocol
  existentes.
- **Fase 12b — Comparativa, reportes y automatización.** Acciones diferenciales
  e infraestructura de salida. Dependencias externas nuevas y flujos de UI
  externos al run corriente. Riesgo medio/alto: se planifica en detalle al
  cerrar 12a (asumiendo la data extra producida por 12a).

### Fase 12a — Métricas locales + rotación/retención de logs

Orden de implementación: un ítem por vez, cada uno con DoD propio y aprobación
antes de pasar al siguiente (no implementar los 4 de corrido).

#### 12a.1 — TimedRotatingFileHandler (rotación + retención, carry-over Fase 11)

**Objetivo:** rotar el JSONL a medianoche y purgar archivos viejos de forma
automática, saldando la limitación v1 documentada de Fase 11.

**Implementación:**
- `logging/configurer.py:build_default_handlers()` swap `FileHandler` ->
  `TimedRotatingFileHandler(when='midnight', backupCount=N, encoding='utf-8')`.
- `config/__init__.py:Logging` gana campo `retention_days: int = 30` (mapea a
  `backupCount`). El nombre base del archivo mantiene `gnd_YYYYMMDD.jsonl`
  (`TimedRotatingFileHandler` rotado agrega `.YYYY-MM-DD_HH-MM-SS` de stdlib;
  el sufijo diario se conserva en el nombre base pre-rotación).
- `JsonFormatter` y `RunContextAdapter` intocados.
- El test existente
  `test_filename_suffix_reflects_now_but_does_not_rotate_at_midnight` invierte
  su aserción: ahora valida que SÍ rota (sintetiza el disparo del rollover vía
  `doRollover()` o mock del clock interno del handler).

**Dependencias nuevas:** ninguna (stdlib `logging.handlers`).
**Choque con protocolos:** ninguno. Swap local en `configurer.py`; el
contrato del handler sigue siendo `logging.Handler`.

**Definition of Done:** un proceso long-running rota el JSONL al cruzar 00:00
(rollover simulable en test); archivos más viejos que `backupCount` se purgan
solos; `ruff+black+vulture` limpio; suite verde.

#### 12a.2 — DNS timing (TECHNICAL_SPEC §8 gap)

**Objetivo:** medir tiempo de resolución DNS por separado, no embebido en ping.
Nueva etapa `dns` en `RunFullDiagnostics.execute()` entre pings (etapa 1) y
traceroutes (etapa 4).

**Implementación:**
- Protocol `DnsResolver` en `domain/ports/dns_resolver.py` + Fake en
  `domain/fakes/`.
- Adaptador real `network/real_dns_resolver.py`: `socket.getaddrinfo` con
  timeout vía `socket.setdefaulttimeout` temporal o patrón equivalente
  (no `asyncio`; stdlib sincrónico, threading-safe).
- Modelo `models/dns_measurement.py` (`DnsResolution` frozen: hostname,
  resolved_ip, elapsed_ms, error, family `AF_INET|AF_INET6`).
- Inyectado por constructor en `RunFullDiagnostics` con default `None`
  (backwards compatible: tests existentes no rompen).
- `config/__init__.py` gana sub-modelo `Dns` (`enabled: bool = True`,
  `hosts: list[str]` default = los hosts de `targets.riot_public` +
  gateway; `timeout_ms: int = 1000`).
- Persistencia: tabla nueva `dns_results` (Regla 9.6 / Protocolo 19 —
  Schema v2: solo añadir, nunca modificar existentes). `DiagnosticsRepository`
  gana método `save_dns_results(run_id, results)` no invasivo.
- `composition_root` añade `dns_resolver=` al wiring.
- Logging: `stage.start dns` / `stage.finish dns` con `n_resolved` /
  `n_failed` (Regla 11.3, Protocolo 34).

**Threading — decisión explícita:**
La nueva etapa DNS corre **serial, NO en el `ThreadPoolExecutor` de pings**
(Regla 9.2), por tres razones:
1. `socket.getaddrinfo` es syscall bloqueante rápida (típicamente <50ms por
   host); el overhead de schedulear N=4-6 hosts en pool vs serial es
   marginal vs el beneficio de simplicidad.
2. Los pings corren ANTES que la resolución DNS (DNSVer unido a pings
   ayuda a interpretar resultados posteriores), prohibiendo
   paralelizarlos juntos sin reordenar el pipeline.
3. Se preserva el patrón que ya usa el esquema actualmente: las etapas
   secuenciales (detect_game_server, baseline, recommendation, persistence)
   corren serial en el worker thread — DNS sigue ese mismo molde.

**Impacto estimado en tiempo total del run:**
N hosts DNS × ~30-80ms c/u (resolución cacheada en OS) = **~150-500ms
adicionales** sobre los ~14s actuales (`run.finish duration_ms` típico de
Fase 9). ≈1-3% de overhead — despreciable. En caso de fail/timeout, cada host
agrega `timeout_ms` (default 1000ms), pero el wrapper defensivo (estilo
`_safe_detect_active_server`) nunca propaga excepción: un host que falla se
registra como `DnsResolution(error=...)` y la corrida continúa.

**Dependencias nuevas:** ninguna (stdlib `socket`).
**Choque con protocolos:**
- Protocolo 1 (separación `models/`/`domain/`): adaptador en `network/`,
  Protocol en `domain/`, modelo en `models/` — ✓.
- Protocolo 6 (DI por constructor): nuevo kwarg con default `None`,
  backwards compatible — ✓.
- Protocolo 19 (Schema v2): tabla nueva, no toca existentes — ✓.
- Protocolo 32 (LoggerAdapter no contextvars): la etapa DNS usa el
  `RunContextAdapter` ya construido al inicio de `execute()`, sin
  propagación global — ✓.

**Definition of Done:** cada corrida con `dns.enabled=True` produce
`DnsResolution` por host configurado, persistidos en `dns_results`;
run log emite `stage.start/finish dns` con `run_id`; un host que falla
no aborta la corrida (queda como `error=...`); `ruff+black+vulture`
limpio; suite verde.

#### 12a.3 — Detección Wi-Fi vs Ethernet + intensidad de señal (PRD §7 should-have)

**Objetivo:** detectar tipo de interfaz activa (Wi-Fi/Ethernet/otra) e
intensidad de señal Wi-Fi (dBm/SSID cuando aplica). Información de contexto
local, persistida en `DiagnosticRun` (no muta el motor de recomendación v1).

**Implementación:**
- Modelo `models/network_interface.py` (`NetworkInterfaceSnapshot` frozen:
  `type: WIFI|ETH|OTHER`, `name`, `is_default_route`, `wifi_ssid?`,
  `wifi_signal_dbm?`).
- Protocol `NetworkInterfaceInspector` en `domain/ports/` + Fake.
- Adaptador real `network/real_interface_inspector.py`:
  - **Detección de SO obligatoria antes de invocar `netsh`** (Protocolo
    distinto, ver abajo): en no-Windows, `netsh` no existe; se evita el
    intento fallido. Reusa el patrón existente
    `if platform.system() == "Windows":` ya aplicado en
    `network/real_ping_runner.py:163` y `real_traceroute_runner.py:313`.
  - Windows: `subprocess` sobre `netsh wlan show interfaces` con **timeout
    explícito** de 3s (configurable en nuevo sub-modelo `Network`), parseo
    con regex para `SSID:` y `Signal:` (convertir % → dBm con fórmula
    estándar `dBm = (quality - 100) / 2 - 100` de Windows). Para tipo
    interfaz, default-route heuristic cross-platform vía `psutil.net_if_addrs()`
    + gateway ya detectado por `composition_root._resolve_gateway_ip`.
  - No-Windows (Linux/macOS): solo reporta `type=OTHER` + `name` (sin
    SSID/signal); no lanza excepción, no invoca `netsh`. Para Linux futuro
    podría usarse `iwconfig`/`nmcli`; queda como limitación documentada.
  - `psutil` import diferido dentro del método (Protocolo 8, replicar
    `active_game_server_detector.py` ya existente).
- Inyectado en `RunFullDiagnostics` con default `None` (BC).
- `config/__init__.py` gana sub-modelo `Network`
  (`inspect_interface: bool = False` default opt-in — usuarios con
  interfaces raras pueden skip; `netsh_timeout_ms: int = 3000`).
- Persistencia: tabla nueva `interface_snapshots` (Schema v2 ✓), nullable
  SSID/signal.
- Etapa nueva en `execute()` serial al final (post-recommendation,
  pre-persistence): `stage.start interface` / `stage.finish interface`.

**Detección de SO y timeout (criterio explícito):**
1. `platform.system() == "Windows"` checkeo antes de construir el comando
   `netsh` (no hay subprocess inválido en Linux/macOS — se evita el parseo
   de error y la rama empty de `subprocess.run` que levanta
   `FileNotFoundError`).
2. `subprocess.run(..., timeout=netsh_timeout_ms/1000)` — explícito, default
   3000ms. Si `netsh` cuelga (driver WLAN atascado, raro), no bloquea la
   corrida. `subprocess.TimeoutExpired` capturado, snapshot con
   `type=OTHER, error="netsh timeout"`.
3. Fallback `type=OTHER` en cualquier error; nunca excepción a la UI
   (Protocolo/EP §1.2).

**Dependencias nuevas:** ninguna (`psutil` presente desde Fase 6, stdlib
`subprocess`/`re`/`platform`).
**Choque con protocolos:**
- Protocolo 8 (psutil import diferido): replicar el patrón del
  `active_game_server_detector.py` — ✓.
- Protocolo 19 (Schema v2): tabla nueva con columnas nullable — ✓.
- Protocolo 5 (`frozen=True`): snapshot inmutable, se construye una vez — ✓.

**Definition of Done:** en Windows, `execute()` con `inspect_interface=True`
produce un `NetworkInterfaceSnapshot` con `type` correcto y, si Wi-Fi, SSID +
signal dBm (tolerancia ±5dBm vs lectura manual en Windows); en no-Windows,
`type=OTHER` sin excepción; `netsh` que cuelga por > timeout no aborta la
corrida; `ruff+black+vulture` limpio; suite verde.

#### 12a.4 — Soporte IPv6 (TECHNICAL_SPEC §8 gap)

**Objetivo:** permitir ping y traceroute sobre IPv6 cuando el ISP asigna IPv6.
Opt-in por config; no se ejecuta salvo configuración explícita.

**Implementación:**
- `config/__init__.py:Targets` gana campos `*_ipv6` (default `None` — si
  está, ejecuta probes v6 además del v4).
- `RealPingRunner.ping()` y `RealTracerouteRunner.traceroute()` reciben
  parámetro `family: int = socket.AF_INET` opcional; wrapper OS-appropriate
  `-6`/`-4` (Windows `ping -6`, `tracert -6`; POSIX `ping6`/`traceroute -6`
  dependiendoAvailability).
- `ProbeResult` gana campo `family: str = "ipv4"` (BC — string short, no
  enum, para no disparar Regla 1.1 de imports circulares; default string
  no rompe serialized históricos).
- `RealPingRunner` detecta `:` en `target_ip` para inferir default `'ipv6'`
  si `family=None`.
- `tracert_parser` revisado: traceroute IPv6 usa el MISMO formato de output
  textual que IPv4 en `tracert` Windows; no se anticipa parser nuevo —
  se valida con evidencia empírica (ver DoD).
- No es un orquestador nuevo: son **etapas duplicadas** — si
  `targets.<X>_ipv6` is not None, append a `ping_specs` con `family=ipv6`.
- Persistencia: columna `family` añadida a `probe_results` (Schema v2:
  columna nueva nullable con default `'ipv4'`, no rompe reads existentes).

**Dependencias nuevas:** ninguna (stdlib `socket`; binarios nativos
`ping -6`/`tracert -6`/`ping6`).
**Choque con protocolos:**
- Protocolo 14 (parser dual EN/ES sostenido≠pico): el parser de tracert
  gana test IPv6, pero el formato esperado es el mismo — validar empírico.
- Protocolo 19 (Schema v2): columna nueva con default string — ✓.
- Protocolo 5 (frozen=True): añadir campo con default no rompe inmutabilidad.

**Definition of Done — condición de evidencia empírica (no closes con solo
unit tests de fixtures asumidos):**
Antes de cerrar 12a.4:
1. Correr `ping -6 <ipv6-host>` y `tracert -6 <ipv6-host>` reales en la
   máquina de desarrollo (Windows). Si no hay IPv6 pública disponible
   (ISP sin IPv6), documentar la limitación como "no verificado in-vivo,
   pendiente de entorno con IPv6" Y dejar el feature opt-in desactivado
   por defecto, similar al dictamen de Fase 2 (Riot IP legacy).
2. Capturar outputs reales del `tracert -6` y `ping -6` (al menos un caso
   feliz + un caso timeout) como fixtures textual en `tests/fixtures/`.
3. Verificar que `tracert_parser` los parsea sin modificaciones o, si
   difiere, añadir rama mínima al parser + tests.
4. Reproducir el dictamen Fase 2: pipelines deterministas probados en
   CI, comportamiento en red real verificado manualmente y documentado.

**Riesgo:** si el parser IPv6 difiere del IPv4 (formato distinto del tracert
Windows para hop con hostname IPv6), este item escalará a refactor del
parser, aumentando scope. Por eso se dejó al final dentro de 12a.

### Fase 12b — Comparativa, reportes y automatización

Orden de implementación: un ítem por vez, cada uno con DoD propio y aprobación
antes de pasar al siguiente (mismo molde que 12a). Decisiones tomadas al kickoff
con el producto:

- **Export (PDF/Markdown):** solo Markdown. PDF queda fuera (YAGNI; el usuario
  puede "Print to PDF" desde un visor de Markdown si lo necesita; reportlab
  ~30MB de dep nueva no se justifica para v1.1).
- **Speed test:** `ookla-speedtest` subprocess (binario oficial en PATH, igual
  patrón que `warp-cli` en WARP compare) + FakeSpeedTestRunner para tests.
  Nunca automático, nunca bloqueante — botón bajo demanda.
- **Notificaciones:** `plyer` (lib multiplataforma, abstrae toast nativos Win).
  Suma dep al pyproject.
- **Reportes automáticos:** reusa el renderer de Export (12b.1) para generar
  el contenido; scheduler con `threading.Timer` integrado al controller
  existente (YAGNI APScheduler/Celery).

Ítems (sub-fases 12b.1 → 12b.5):

- 12b.1 — Export Markdown
- 12b.2 — Notificaciones de escritorio (plyer)
- 12b.3 — Reportes semanales/mensuales automáticos (reusa 12b.1)
- 12b.4 — Comparación con/sin Cloudflare WARP (`warp-cli` subprocess)
- 12b.5 — Speed test bajo demanda (`ookla-speedtest` subprocess)

#### 12b.1 — Export Markdown

**Objetivo:** el usuario puede exportar la última corrida (`DiagnosticRun`)
a un archivo `.md` autoexplicativo, que contenga: header con metadatos del
run, score + veredicto + headline, explicación del motor de recomendación,
tabla de probes (target/provider/outcome/latencias/loss/jitter/family),
sección de traceroutes (hops por provider + culprit), secciones opcionales
(DNS si `dns_results` no vacío, interfaz de red si `interface_snapshot` no
None, game server activo si `active_game_server` no None).

**Implementación:**
- Paquete nuevo `src/gnd/export/`. No toca `RunFullDiagnostics` ni los
  Protocol existentes — Export es presentation puro sobre `DiagnosticRun`
  (modelo ya accesible en cualquier capa).
- `export/markdown_renderer.py`: función pura
  `render_run_to_markdown(run: DiagnosticRun) -> str`. Sin IO (file write
  es aparte), sin dependencias nuevas (solo stdlib + `models/`). Pure
  function testeable directamente con fakes.
- `export/__init__.py`: re-exports el renderer.
- UI: `MainWindow._last_run: DiagnosticRun | None` almacenado en
  `_apply_run`. Botón "Export Markdown" en la top bar (al lado del
  botón Run). Estado inicial `disabled`; habilitado solo si hay un run
  reciente.
- Click handler: si `_last_run` es None → no-op (botón ya disabled por
  guarda). Si hay, abre `filedialog.asksaveasfilename(defaultextension=".md")`,
  llama al renderer, escribe archivo. Errores capturados y logueados
  (Regla 11.3: `event="export.start"` / `export.finish` / `export.error`
  con `path` en `extra`); состояние bar actualizado con feedback.
- No se persiste nada nuevo en la DB — el export es puramente sobre el
  `DiagnosticRun` ya generado (la DB histórica queda intacta).

**Decisiones de diseño:**
- Renderer como **función libre**, no clase (sin estado). Justificación: no
  hay dep externas que inyectar y el input (`DiagnosticRun`) es inmutable.
  YAGNI un Protocol `RunRenderer` con múltiples implementaciones — solo
  Markdown por ahora.
- Sin stream/writer abstracto: el caller (UI) abre el path y escribe el
  string. Mantener el renderer puramente bidimensional (in: DiagnosticRun,
  out: str) maximiza testabilidad.
- Botón en la top bar (no en una sección) porque export aplica a la corrida
  entera, no a una vista particular.

**Dependencias nuevas:** ninguna (stdlib `pathlib` / `tkinter.filedialog`
en la UI, ya en stack).

**Choque con protocolos:**
- Protocolo 1 (separación `models/`/`domain/`): `export/` importa solo de
  `models/` — no toca `psutil`/`sqlite3`/`subprocess`. OK.
- Protocolo 6 (DI por constructor): N/A — el renderer es función libre,
  no clase con deps.
- Regla 11.3 (eventos estructurados): click handler emite `export.start` /
  `export.finish` / `export.error` con `path` en `extra`.
- Protocolo 25 (vulture): el renderer es reachable desde `MainWindow`, no
  genera falsos positivos.

**Definition of Done:**
- Botón "Export Markdown" presente, disabled hasta que haya un run reciente.
- Click → `asksaveasfilename` → genera `.md` válido en el path elegido.
- El `.md` contiene: header (run_id, timestamps, duración), score + veredicto
  + headline, explanation (lista), tabla de probes (target/provider/outcome/
  latencias/loss/jitter/family), sección traceroutes (hops por provider +
  culprit marcado), secciones opcionales (DNS / interfaz / game server)
  solo si aplican.
- Tests unitarios del renderer cubren: run mínimo, run con DNS, run con
  interfaz Wi-Fi, run con game server, probes con todos los outcome kinds
  (SUCCESS/FILTERED/UNREACHABLE/TIMEOUT), traceroutes con/ sin culprit.
- Test smoke de MainWindow cubre button availability toggle (disabled sin
  run, enabled con run) y llama al renderer con un run fake (sin interaction
  real con filedialog — mock/stub en código o pytest fixture).
- `ruff+black+vulture` limpio. Suite verde (596 + tests nuevos de 12b.1).

Reglas transversales que aplican a toda la fase (12a y 12b):

- **Protocolo 1** (separación `models/`/`domain/`): adaptadores reales en
  `network/`, Protocol en `domain/`, modelos en `models/`.
- **Protocolo 6** (DI por constructor): nuevos_kwargs en
  `RunFullDiagnostics` con default `None` (backwards compatible).
- **Protocolo 19** (Schema v2 retro-compat): solo AÑADIR tablas/columnas
  con defaults nullable, nunca modificar existentes.
- **Protocolo 5** (`frozen=True`): añadir campos con default no rompe
  inmutabilidad.
- **Protocolo 8** (psutil import diferido): replicar patrón
  `active_game_server_detector.py` para todo nuevo adaptador que use psutil.
- **Regla 9.1 / `DatabaseConnectionFactory`**: ninguna feature 12a introduce
  cross-thread nuevo. `execute()` pide conn del worker thread existente; las
  nuevas persistencias pasan por `repository.save_run` extendido (que ya pide
  su conn propia).
- **Regla 11.1 / `controller.py` (single-run)**: ninguna feature 12a lanza
  corridas paralelas; el guard `is_running()` del controller sigue válido.
- **Protocolo 25** (vulture obligatorio antes de cerrar): todas las features
  whitelisteada con comentario explicativo en `pyproject.toml` si generan
  falsos positivos (Regla 11.4 — overrides de ABCs/lib estándar).
- **Logging (Reglas 11.3 / 11.2, Protocolos 32-34)**: cada etapa nueva emite
  `stage.start`/`stage.finish` con keys `event`+`stage` y naming
  `<namespace>.<verbo>`. `JsonFormatter` omite `None`.
- **Graphify**: tras cada feature, post-commit (hook activo) reconstruye
  `graphify-out/graph.json`. Verificar `GRAPH_REPORT.md` por god nodes
  introducidos (riesgo: `composition_root` gana 3 imports nuevos en 12a;
  revisitado en cierre).

Dependencias nuevas:

- **Fase 12a:** ninguna externa (solo stdlib + `psutil` ya presente).
- **Fase 12b (potenciales, se confirman al kickoff de 12b):**
  - WARP compare: binario `warp-cli` en PATH (no lib Python); FakeWarpController
    para tests.
  - Speed test: `slicer` (lib) ó subprocess `ookla-speedtest` — decisión
    técnica al kickoff de 12b.
  - Notificaciones: `plyer` (lib multiplataforma) — verificar estado.
  - Export PDF: `reportlab` (preferido sobre `weasyprint` por dependencias
    GTK/Cairo en Windows).
  - Reportes: stdlib `sqlite3` + scheduler (`threading.Timer` o integrado al
    controller existente).

Cada ítem de la fase se planifica como sub-fase independiente cuando se
priorice, siguiendo el mismo formato (objetivo + DoD + dependencias + choques).

---

## Fase 13 — Extensibilidad multi-juego

**Objetivo:** implementar `GameDiagnosticsModule` (Protocol de `ARCHITECTURE.md` §7) para al menos un segundo juego (ej. Valorant), validando que no fue necesario tocar `analysis/`, `recommendations/`, ni `database/`.

**Definition of Done:** agregar un juego nuevo es, en líneas de código, mayormente contenido dentro de `diagnostics/games/<nuevo_juego>.py`.

---

## Estrategia de testing transversal

- **Unitarios:** dominio, análisis, motor de recomendación — sin red ni disco real, 100% mockeado vía los `Protocol`.
- **Integración:** capa de red real, marcada aparte, no bloqueante para desarrollo offline.
- **Fixtures grabadas:** outputs reales de `ping`/`tracert` guardados como texto para tests deterministas y reproducibles sin depender de la red del momento.
- **Invariantes de negocio como tests explícitos:** ej. "nunca `safe_to_play` con packet loss crítico" — estos son los tests que más valor aportan y deben escribirse antes que los de caso feliz.
