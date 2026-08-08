# Session Log — Game Network Diagnostics (GND)

> MEMORIA ACTIVA. Se lee completa al inicio de sesión.
> REGLA DE ROTACIÓN (obligatoria, no opcional): al cerrar CADA sesión nueva,
> la sesión que hoy está en "ÚLTIMA SESIÓN" se comprime a 1-3 líneas y pasa a
> "HISTORIAL RELEVANTE"; el detalle completo se mueve a `session_log_archive.md`.
> Nunca debe haber más de 1 sesión en detalle completo en este archivo.

---

## ÚLTIMA SESIÓN (detalle completo)

### Post-Fase 14.0a — Empaquetado Windows: launcher VBS + acceso directo escritorio + CREATE_NO_WINDOW (2026-08-02)

**Contexto:** última tarea pedida: empaquetar GND como app de Windows
usable sin terminal. Evaluadas 3 opciones (PyInstaller `--onefile`,
`--onedir`, y `.vbs` + venv local). Decisión del usuario: **Opción C
(.vbs + venv local)** — repo sigue activo (14.0b-h pendientes), stack
matplotlib/tkinter/psutil con fricción conocida en PyInstaller,
usuario único, DB/logs ya en `%APPDATA%/GND/`.

**Launcher (`launch_gnd.vbs`, repo root):** WSH puro, sin cmd. Deriva
el repo root relativo a `ScriptFullName`, valida que el venv exista
(MsgBox si falta), `wsh.Run "pythonw.exe" -m gnd, 0, False`
(windowless). Fix intermedio documentado: un wrapper
`cmd /c cd /d && ...` spawnaba un conhost visible → revertido a
`wsh.Run` directo, que hereda el CurrentDirectory del proceso
windowless. `config.toml` se lee vía `Path.cwd()` → queda en repo root.

**Acceso directo (`scripts/install_shortcut.ps1`):** idempotente,
`$PSScriptRoot` auto-detecta el repo. `GND.lnk` en Desktop con
Target=`wscript.exe` + vbs, IconLocation=`imageres.dll,19` (Network
and Sharing Center), WorkingDirectory=repo root. Se ejecutó y se
verificó.

**Bug de producción fixeado:** al correr diagnósticos desde
pythonw.exe aparecían ventanas cmd (6+2 en Run Diagnostics, 6+2+1
speed test, 6+2+6 WARP) — cada `subprocess.run` sin creationflags
abría una ventana de consola visible cuando el padre es windowless.
Fix: nuevo helper `src/gnd/network/_subprocess_helpers.py` con
`subprocess_kwargs()` → `{"creationflags": 0x08000000}`
(CREATE_NO_WINDOW) solo Windows. Aplicado en los 5 adapters reales:
real_ping_runner, real_traceroute_runner,
real_network_interface_inspector, real_warp_controller,
real_speed_test_controller.

**Tests:** `tests/test_subprocess_helpers.py` (7 tests, mockean el
subprocess real y verifican el flag). Suite 1000 → 1007 unit, 17
integration, 1 flake tkinter 12b.4.2 conocido (pasa aislado).
ruff+black+vulture limpio. Verificación in-vivo del launcher: sin
conhost nuevos tras launch (baseline 2 → 2).

**Config:** `config.toml` (personal, features habilitadas) agregado a
`.gitignore` — no se pushea. `gnd_console_debug.log` también ignorado.

**Commits (4, sobre origin/main):** `424fd08` (Fase 13 + Fase 14.0a),
`e4199f1` (fixes post-Fase 13: config.toml, restore WARP fiel/race,
speed test), `59603c9` (empaquetado Windows + CREATE_NO_WINDOW),
`a17f40b` (chore: ignorar config.toml). SIN pushear aún.

**Lecciones:** NUNCA `Stop-Process -Name "wscript"` (mata el host de
opencode, incidente durante smoke-test). Protocolo Crítico 48 en
tech_stack.md: subprocesses Windows SIEMPRE con CREATE_NO_WINDOW.
Proyecto en pausa hasta 14.0b cuando el usuario lo pida.

---

## HISTORIAL RELEVANTE (comprimido, detalle completo en session_log_archive.md)

- **Fase 14.0a** — Protocols + VOs + Fakes para detección de IP real
  LoL vía lockfile+LCU. Decisión Opción 3: solo tier `exact_ip`
  (gameflow serverIp del LCU cuando partida InProgress), `regional_edge`
  pausado (mapping empírico: solo NA1/EUW1 resuelven Riot-direct).
  GameflowSession/LockfileData VOs, Protocols LockfileReader/LcuClient,
  Fakes FakeLockfileReader/FakeLcuClient, ActiveGameServerInfo
  +precision_tier (default proxy_login, backwards-compat). 50 tests.
  1000 tests. Detalle en `session_log_archive.md`.

- **Post-Fase 13 (sesión 4)** — Validación in-vivo WARP Comparison:
  APROBADA Y CERRADA con warp-cli 2026.6.850.0. Restore fiel
  `Mode: Warp`/`MASQUE` idéntico antes/después (Regla 12b.4.3 OK).
  Columna `FAILED` para `local` (172.16.0.1 timouteó, puntuale de
  red, no bug de GND, Regla 12b.4.5 OK). Sin race condition
  (Regla 12b.4.4 OK). Fase 12b cerrada en producción. Fase 13
  ya estaba aprobada por tests; no Pendientes in-vivo para
  LoL/Valorant. Discusión diseño #4 (ponderación DNS genéricos
  bajo VPN) en `observations.md`. Próxima fase: 14+. Detalle en
  `session_log_archive.md`.
  modo/protocolo: bug `RealWarpController` flag `--output-format=json`
  inexistente en warp-cli 2026.6.x (fixeado → `status --no-paginate`
  texto plano + regex). Adapter detecta mode (warp/proxy/doh) y
  tunnel_protocol (WireGuard=UDP/MASQUE) via `settings list`, los
  replica en el restore. Fail-safe si parseo falla. Incident de
  memoria (auto-provocado, PowerShell encoding corrompe `session_log_archive.md`,
  irrecuperable ~600 líneas de Fase 2-12b.5; salvaguarda permanente
  en PROTOCOLO_SALIDA/INICIO/INDEX). Lesson 12b.4.3 (restore fiel o
  fail-safe). 22 tests. 936 tests. Detalle en `session_log_archive.md`.

- **Post-Fase 13 (sesión 1)** — Habilitación real Speed Test + fixes
  producción: bug `config.toml` roto desde Fase 0 (pydantic-settings
  v2 no carga TOML auto). Bug badge "IMPROVED" enmascaraba latencia
  +684%. Bug template variable cruzada. Fix via subclass dinámica en
  `load()` + reescribir `_determine_verdict` priorizando deltas. Fix
  wiring `build_warp_controller` (timeout_seconds → enable_timeout_s).
  Lesson 12b.4.2 (flake tkinter suite completa). 24 tests. 920 tests.
  Detalle en `session_log_archive.md`.

- **Fase 2** (Capa de red real): PingRunner + fallback TCP SYN + parser cross-platform. 95 tests. Aprobada.
- **Verif. Fase 2 Windows**: TIMEOUT contra Riot IP legacy = host inalcanzable real, no bug. 99 tests.
- **Pre-Fase 3**: fix check.ps1 (stderr PowerShell), DNS resolution en RealPingRunner, config Pydantic con hostnames Riot.
- **Fix score**: probes faltantes se excluyen del promedio, no como 0. 142 tests.
- **Fase 5** (Motor de recomendación): 7 reglas + 2 constraints, fix None≠degradado, firma con baselines. 202 tests.
- **Fase 6** (ActiveGameServerDetector): psutil + filtrado IPs + anti-telemetría. v1 ajustado, riot_public como proxy. 273 tests.
- **Transparencia proxy riot_public**: motor agrega nota explícita cuando usa riot_public. 278 tests.
- **Fase 7** (Traceroute + culprit hop): parser dual EN/ES, sostenido≠pico. Verificado in-vivo Windows. 336 tests.
- **Fase 8** (Monitoreo WinMTR): agregación por hop_number, wall-clock duration (Regla 8.6). 426 tests.
- **Fase 9** (UI): fix threading SQLite (factory por hilo), 129s→14.5s, Historical Comparison real. 456 tests. Reglas 9.1-9.6.
- **Fix crítico post-Fase 9**: anomalías de baseline degradan veredicto en `recommendations/engine.py`. 463 tests.
- **Fase 10 inicial**: 5 gráficos PRD §10 matplotlib embebido en tkinter, SeriesDataSource Protocol + 5 queries puras, ChartsSection 6ta pestaña. 497 tests.
- **Fase 10 cierre**: fix legibilidad packet_loss_over_time — `ylim_sup = min(100.0, max(5.0, max_y * 1.2))` (Regla 10.5). 3 tests nuevos. 497 tests.
- **Fase 11** (Logging JSON estructurado): JsonFormatter + RunContextAdapter + configure_logging. FileHandler JSONL diario + StreamHandler stderr. 3 fixes post-revisión: YAGNI contextvars eliminado, rotación limitación v1, retención sin implementar. 520 tests. Aprobada.
- **Fase 12a** (Métricas locales): 12a.1 rotación+retención JSONL, 12a.2 DNS timing serial, 12a.3 Wi-Fi/Ethernet (verificado in-vivo), 12a.4 IPv6 opt-in (verificación empírica). Refactor 12a.4 pausa rota → fixed IndentationError/dup methods. 596 tests.
- **Fase 12b.1** (Export Markdown): renderer función pura `render_run_to_markdown` en paquete `export/`, botón UI top bar + filedialog + logging. Escapado Markdown tablas vs prosa. 45 tests nuevos. 641 tests.
- **Fase 12b.2** (Notificaciones de escritorio plyer): paquete `notifications/` con PlyerDesktopNotifier adapter (import diferido Regla 12b.2.1) + `build_run_notification` formatter puro (filtrado notify_only_on_issues via signal None Regla 12b.2.2) + VO `DesktopNotification` + Protocol `DesktopNotifier` + Fake. Wiring via `build_notifier()`, integración `_maybe_send_notification` en `_apply_run`. 46 tests nuevos. 687 tests. Aprobada.
- **Fase 12b.3** (Reportes semanales/mensuales automáticos): `reports/` paquete (compose_period_report función pura + ReportsScheduler con threading.Timer), VO `ReportConfig`, Protocol `RunHistoryReader` + `SqliteRunHistoryReader` (lectura segregada del repo de escritura, bulk reconstruction, half-open range), wiring via `build_report_pipeline()`, integración opcional en MainWindow con `close()` hook para detener el scheduler. 54 tests nuevos. 741 tests. Aprobada.
- **Fase 12b.4** (Comparación con/sin Cloudflare WARP): `warp_controller/` Protocol + `RealWarpController` (warp-cli subprocess, import diferido Regla 12b.2.1) + `FakeWarpController` (estado programable, modos de fallo). `WarpComparisonUseCase` orquesta 2 runs (WARP off → WARP on → restore estado original), computa deltas por provider (latencia/jitter/loss/score) y veredicto agregado (improved/degraded/neutral/unavailable). Config `WarpComparison(enabled=False, restore_original_state=True, timeout_seconds=30, pause_between_runs_seconds=2.0)`. Wiring condicional via `build_warp_controller()` + `build_warp_comparison()`. UI: botón "Run WARP Comparison" en top bar + pestaña "WARP Compare" con veredicto, score delta, tabla de deltas por provider. Backwards-compat: MainWindow sin kwargs WARP funciona igual (pre-12b.4). 54 tests nuevos. 789 tests. Aprobada.
- **Fase 12b.5** (Speed test bajo demanda): Modelos `SpeedTestResult`/`SpeedTestDelta`/`SpeedTestComparisonResult` (models/speed_test.py), Protocol `SpeedTestController` + `SpeedTestError` (domain/ports/), `FakeSpeedTestController` (domain/fakes/), `RealSpeedTestController` con ookla-speedtest subprocess (network/), `SpeedTestComparisonUseCase` que compone RunFullDiagnostics + SpeedTestController (application/), `SpeedTestComparisonController` + `SpeedTestComparisonSection` (ui/). Config `SpeedTest(enabled=False, timeout_seconds=120)`, wiring via `build_speed_test_controller()` + `build_speed_test_comparison()`, UI: botón "Run Speed Test" + pestaña "Speed Test". Backwards-compat: MainWindow sin kwargs Speed Test funciona igual. 48 tests nuevos. 843 tests. Aprobada.
- **Fase 13** (Extensibilidad multi-juego): COMPLETADA. Protocol `GameDiagnosticsModule` (4 métodos: public_endpoints → `list[GameEndpoint]` VO provider+family, process_names, detect_active_server, game_server_provider). Impl `LeagueOfLegendsModule` (adapter sobre lógica Riot existente, reusa `ConnectionInspector`, game_server_provider="riot_game_server") + `ValorantModule` (provider "valorant_public", process `VALORANT-Win64-Shipping.exe`). Refactor `RunFullDiagnostics` kwarg `game_module` opcional (backwards-compat: None = path Riot hardcodeado). Config `game_detection.active_game="league_of_legends"`. Builder `build_game_module` mapea string → impl. DoD validado: `analysis/`, `recommendations/`, `database/` sin tocar (3 tests estáticos blindan). 53 tests nuevos. 896 tests. Aprobada. Detalle en `session_log_archive.md`.
- **Post-Fase 13** (Habilitación real Speed Test + fixes producción): bug `config.toml` roto desde Fase 0 (pydantic-settings v2 no carga TOML auto, requiere `TomlConfigSettingsSource`). Bug badge "IMPROVED" enmascaraba latencia +684% en speed test (`_determine_verdict` solo miraba score). Bug template `result.baseline.server_name` (Mostrar nombre server en lugar de score diagnóstico). Fix: subclass dynámica en `load()` para toml_file runtime, agregar `diagnostic_score`/`diagnostic_verdict` al VO, reescribir `_determine_verdict` priorizando deltas lower-is-better, fix template UI. + `build_warp_controller` wiring bug (timeout_seconds → enable_timeout_s). Lesson nueva 12b.4.2 (flake tkinter en suite completa). 24 tests nuevos. 920 tests. Detalle en `session_log_archive.md`.
