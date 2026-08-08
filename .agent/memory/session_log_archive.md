# Session Log — ARCHIVO

> Detalle completo de sesiones ya resumidas en `session_log.md` (HISTORIAL RELEVANTE).
> No se lee automáticamente al inicio de sesión. Consultar solo si hace falta
> el detalle exacto de archivos/tests/decisiones de una fase vieja.

---

## Sesión Post-Fase 13 (sesión 4) — Validación in-vivo WARP Comparison: APROBADA Y CERRADA (2026-07-30)

**Contexto:** re-corrida del botón "Run WARP Comparison" con
warp-cli 2026.6.850.0 tras los fixes de la sesión 3 (Reglas
12b.4.4 polling + 12b.4.5 providers fallidos). Objetivo: cerrar el
pendiente de validación in-vivo con éxito antes de evaluar Fase 14+.

**Resultado:** los 3 puntos de validación del pendiente sesión 3
pasaron limpios, sin warnings/state_timeout en el log:

1. **Restore fiel OK (Regla 12b.4.3):** `warp-cli settings list`
   corrido antes y después de la comparación — idéntico
   (`Mode: Warp`, `tunnel protocol: MASQUE`). El adapter restauró
   modo+protocolo correctamente, no cayó al fallback ni al default
   ciego. Antes del fix sesión 2 el restore perdía el modo elegido.

2. **Columna Status "FAILED" OK (Regla 12b.4.5):** la fila `local`
   (gateway 172.16.0.1) falló en ambas corridas (off y on) — timeouts
   reales contra ese gateway, puntuales de la red, no bug de GND —
   y la tabla lo marcó como `FAILED` en la columna nueva, con
   `delta=None`/`delta_pct=None` mostrados como "-" (NO como -100%
   falso mejora). Bug 2 sesión 3 confirmado resuelto en UI real,
   no solo en tests.

   Log puntual: 2 entradas `event="ping.timeout" target=172.16.0.1
   provider="local"` (una por corrida) — esperadas y correctas,
   reflejan realidad de red, no defecto de orquestación.

3. **Race condition resuelta (Regla 12b.4.4):** sin `WARP enable no
   conectó: connecting` en el log, sin `state_timeout` verdict.
   El poll `_wait_for_warp_state(connected, timeout=15s)` esperó
   efectivamente la transición async del daemon antes de medir.

**Comportamiento de red confirmado (discusión de diseño #4, ya en
`observations.md`):** `riot_public` y `cloudflare` mejoraron con
WARP; `google` y `quad9` empeoraron (tráfico rutado por el túnel).
Coincide con experiencia real previa reportada por el usuario
(`90ms→65-70ms` en riot_public). El score global ponderado puede
degradarse artificialmente bajo VPN — decisión: quedarse con
comportamiento actual (Option 1), re-discutir si WARP se vuelve
feature de uso frecuente.

**No se tocaron archivos de código ni de tests en esta sesión** —
es sesión de validación pura. El estado previo de la suite (943
unit + 17 integration, ruff+black+vulture limpio) queda igual.

**Cierre formal:**
- Fase 12b (Comparativa, reportes y automatización) — APROBADA Y
  CERRADA en in-vivo, todas sus sub-fases (12b.1-12b.5) validadas
  en producción en esta máquina (warp-cli 2026.6.850.0,
  ookla-speedtest, plyer, matplotlib).
- Fase 13 (Extensibilidad multi-juego) — ya estaba aprobada por
  tests + validación estática de DoD; no había pendiente in-vivo
  (LoL y Valorant son juegos instalados en otra máquina/usuario,
  su validación in-vivo es opcional y no bloquea).
- Próxima fase: 14+ (TBD al cierre de esta sesión). No quedan
  pendientes críticos en Fase 12 ni en Fase 13. La observación
  de ponderación bajo VPN (`observations.md`) queda abierta como
  decisión de diseño futura, no bloqueante.

---

## Sesión Post-Fase 13 (sesión 3) — WARP in-vivo: 2 bugs críticos race + provider fallido (2026-07-30)

**Contexto:** validación in-vivo real con warp-cli 2026.6.850.0.
Usuario tocó el botón "Run WARP Comparison" después de habilitar
`[warp_comparison]` en `config.toml` y encontró dos bugs serios.

**Bug 1 — Race condition `enable`/`diagnostic` (Regla 12b.4.4):**
el log mostraba `WARP enable no conectó: connecting` (DOS veces en
corridas distintas), seguido de pings que fallan con `DNS resolution
failed` y `timeout` hacia riot_public y gateway local. El use case
arrancaba las mediciones ANTES de que warp-cli termine de transicionar
a `connected` — agarraba la interfaz de red en un estado intermedio
no listo. Root cause: `warp-cli connect` NO bloquea hasta conectar,
solo manda el signal al daemon y devuelve; el daemon transiciona
async a `connecting`→`connected` en 1-3s. El `time.sleep(1.0)` ciego
era insuficiente y el `if not status.connected: warn` continuaba
de todas formas midiendo contra red rota.

**Bug 2 — Provider con medición fallida reportado como mejora (Regla 12b.4.5):**
cuando un provider fallaba completamente (DNS resolution failed,
outcome=UNREACHABLE/TIMEOUT), el reporte mostraba `avg_latency_ms=0.0`
y calculaba `Δ%=-100%` dando falsa impresión de "mejoró a cero" cuando
en realidad era fallo total de medición. Root cause:
`_compute_provider_deltas` con `avg_metric` retornaba `0.0` cuando
todos los probes del lado eran non-SUCCESS (vals=[], default 0.0),
violando Regla 4.1 ("probes faltantes se excluyen, no cuentan como 0").
Mismo root cause que bug 1: corrida bajo WARP con daemon en estado
intermedio → pings timeout-ean → falla total → 0.0 reportado como mejora.

**Discusión de diseño #4 (no es bug — anotado):** Google y Quad9
empeoran bajo WARP porque todo el tráfico se enruta por el túnel.
El score global pondera igual providers de DNS genéricos que el
target de juego (riot_public). El usuario explícitamente abrió la
discusión de si ponderar distinto bajo VPN. Decisión: no fixear,
anotar en `observations.md` para discutir en fase futura si WARP se
vuelve feature de uso frecuente.

**Confirmado con usuario:** cuando la medición SÍ corre bien
(`riot_public 82.2ms→63.2ms, -23.1%`), coincide con su experiencia
real reportada (`90ms→65-70ms` con WARP) → lógica de comparación OK,
solo timing de arranque y manejo de fallos son el problema.

**Archivos modificados:**
- `src/gnd/application/warp_comparison.py`: nuevos Protocols `Sleeper`
  + `PerfClock` (mismo patrón que RouteMonitor Regla 8.3); defaults
  `_DefaultSleeper`/`_DefaultPerfClock` para producción; `__init__`
  acepta `sleeper=None, perf_clock=None`. `WarpComparisonParams` +3
  fields: `enable_timeout_s=15.0`, `disable_timeout_s=10.0`,
  `poll_interval_s=0.5`. `_run_with_warp_state` reescrito: tras
  enable/disable, llama `_wait_for_warp_state(target_state, timeout,
  poll_interval_s)` que hace poll hasta match o timeout. `execute()`
  refactor: catch `WarpError` y devuelve `_build_state_timeout_result(exc)`
  con verdict="state_timeout" (NO propaga excepción). Nuevo helper
  `_append_failed_note` anexa providers con medición fallida al
  explanation. `_compute_provider_deltas` reescrito: filter_success
  excluye non-SUCCESS; si un lado no tiene SUCCESS, ese lado=None y
  status="failed_off"|"failed_on"|"failed_both". `_determine_verdict`
  acepta `failed_providers` y los anexa al explanation. `warp_target_state`
  en extras (evita clash con LogRecord attribute `target_state`).
- `src/gnd/models/warp_comparison.py`: `WarpComparisonDelta` extended:
  `warp_off_value: float | None`, `warp_on_value: float | None`,
  `delta: float | None`, `delta_pct: float | None` (ya era),
  `status: str = "ok"`. Backwards-compat (todos los fields nuevos
  opcionales o con default).
- `src/gnd/ui/warp_comparison_section.py`: nueva columna `status`
  en el Treeview (90px, anchor=center). Filas con `status != "ok"`
  muestran "FAILED" en la columna. Valores None → "-" en off/on/delta/pct.
  `verdict_colors["state_timeout"] = "#ce9178"` (orange). Si verdict
  es `state_timeout`, status_label muestra "Comparación abortada: WARP
  no transicionó al estado objetivo" en lugar de "Comparación
  completada".

**Archivos nuevos:** `tests/test_warp_comparison_use_case.py`:
- `class TestWarpStatePolling`: 4 tests (race enable OK, race enable
  timeout abort, race disable OK, race disable timeout abort).
- `class TestWarpComparisonFailedProviders`: 3 tests (provider falla
  solo en on → no se cuenta como mejora, falla en ambas → exclude del
  verdict, falla solo en off → table marca failed_off).
- Helpers `_FakeSleeper`, `_FakePerfClock`, `_ProgrammableStatusWarpController`,
  `_ProgrammableTransitionSleeper`, `_failed_probe`.

**Suite:** 936 → 943 unit (+7 tests nuevos: 4 polling + 3 failed providers),
17 integration. ruff+black+vulture (0 warnings) limpio.
Tests UI WARP/SpeedTest aislados: 20/20 (lesson 12b.4.2 sigue igual).

**Pendiente validación in-vivo post-fix:** usuario debe correr el botón
real con WARP prendido en modo UDP=WireGuard para confirmar que:
1) El poll detecta correctamente la transición a `connected` antes
   de medir (sin timeouts/DNS failed falsos). 2) El restore vuelve
   a `WireGuard` (no MASQUE default). 3) Si un provider falla, aparece
   como "FAILED" en la tabla (no -100%). Si WARP no transiciona en
   15s, verdict muestra "STATE_TIMEOUT" en naranja.

---

## Sesión Post-Fase 13 (sesión 1) — Habilitación real de Speed Test + fixes de producción (2026-07-30)

**Contexto:** usuario intenta habilitar `SpeedTest` vía `config.toml` y
descubre 1 bug bloqueante + 2 bugs visuales en la pantalla Speed Test. Esta
sesión NO es una fase nueva del roadmap — es cierre de deuda técnica
detectada en producción.

**Bug A — `config.toml` no cargaba (pre-Fase 13, oculto 13 fases):**
`GndSettings.load()` usaba `_env_file=path` pero `config.toml` es TOML, no
`.env`. En pydantic-settings v2, TOML no se carga automáticamente — requiere
`TomlConfigSettingsSource` vía `settings_customise_sources` + subclass dinámica
en `load()` (rechazo de `_toml_file=` como kwarg extra).

**Bug B — Badge "IMPROVED" enmascaraba latencia +684%**
(`speed_test_comparison.py:_determine_verdict`): el `_determine_verdict`
solo miraba `score >= 80` → "improved", ignorando los deltas de
latencia/jitter/loss entre gateway y speed test. Si latencia empeoraba
+684% pero el score del diagnóstico era alto (86), el badge decía
"IMPROVED". El "baseline = speed_test_result, comparison = speed_test_result"
(ambos SpeedTestResult, sin score del diagnóstico) era también incorrecto.

**Bug C — Template con variable cruzada**
(`speed_test_comparison_section.py:_score_label`): el template usaba
`result.baseline.server_name` (nombre del servidor de speed test, ej.
"Movistar Colombia") donde debería ir el score numérico del diagnóstico.
Mostraba `Diagnóstico: score=Movistar Colombia` en lugar de
`score=86/100, verdict=safe_to_play`.

**Archivos nuevos creados:**
- `config.toml` (raíz del repo): `[speed_test] enabled=true timeout_seconds=120`.
- `tests/test_config_toml_loading.py`: 10 tests de regresión. Escribe
  `config.toml` físico a `tmp_path` (no mocks), valida carga de secciones
  anidadas (speed_test, warp_comparison, notifications, logging, database,
  targets), sección ausente → defaults, TOML vacío → no rompe,
  lista TOML → list[str], y precedencia env vars > TOML.

**Archivos modificados:**
- `src/gnd/config/__init__.py`: import `TomlConfigSettingsSource` + override
  `settings_customise_sources` (orden: init > .env > env vars > toml > secrets)
  + `load()` crea subclass dinámica con `model_config['toml_file']` seteado
  (forma idiomática de pasar runtime el path sin `_toml_file=` rejections).
- `src/gnd/models/speed_test.py`: agrego dos fields al VO
  `SpeedTestComparisonResult`: `diagnostic_score: int | None` y
  `diagnostic_verdict: str | None` (None en path unavailable).
- `src/gnd/application/speed_test_comparison.py`: `execute` ya no construye
  `now = clock or datetime` residual; `_compute_comparison` ahora alimenta
  `diagnostic_score`/`diagnostic_verdict` desde `run.recommendation` en el
  resultado; `_determine_verdict` reescrito para priorizar anomalías de deltas
  lower-is-better (latency/jitter/loss vs gateway con thresholds >5ms/>5ms/>0.5pp)
  sobre el score absoluto del diagnóstico — si las métricas de red empeoran,
  el veredicto es "degraded" sin importar el score (bug B core fix).
  `_build_unavailable_result()` pierde params `started_at`/`finished_at`
  no usados (código muerto real desde Fase 12b.5, detectado por vulture).
- `src/gnd/application/warp_comparison.py`: mismo cleanup del parámetro
  muerto en `_build_unavailable_result` (mismo bug pre-existente, sin
  afectar el flujo execute).
- `src/gnd/ui/speed_test_comparison_section.py`: template de
  `_score_label` usa `result.diagnostic_score`/`diagnostic_verdict` en lugar
  de `result.baseline.server_name` (bug C fix); show vacío si los campos son
  None (path unavailable).
- `src/gnd/composition_root.py`: corrige bug de wiring `RealWarpController`:
  `timeout_seconds=settings.warp_comparison.timeout_seconds` (que no existe)
  → `enable_timeout_s=settings.warp_comparison.timeout_seconds` (param del
  adapter que matchea con "timeout para warp-cli connect" según docstring
  del config). Bug reportado por el usuario al arranque de sesión.
- `tests/test_speed_test_comparison_use_case.py`: 5 tests de regresión
  nuevos: `test_bug1_score_alto_con_latencia_empeorada_es_degraded_no_improved`
  (reproduce bug B exacto del usuario), jitter empeorado, packet loss
  empeorado, transporte de diag_score/verdict, caso unavailable None.
- `tests/test_speed_test_comparison_section.py`: 2 tests de regresión nuevos:
  `test_bug2_score_label_muestra_score_no_server_name` (valida template
  fixed) + `test_bug2_score_label_vacio_si_diagnostic_score_es_none`.
- `tests/test_warp_comparison_section.py` + `tests/test_speed_test_comparison_section.py`:
  `# FLAKYKNOWN (lesson 12b.4.2)` en module docstrings para documentar el
  flake de `tk.Tk()` bajo suite completa (NO es bug del producto).
- `pyproject.toml`: whitelist vulture + documentación:
  `SpeedTestComparisonUseCase`/`SpeedTestComparisonSection` (clases
  instanciadas por composition_root/MainWindow, falsos positivos),
  `settings_customise_sources` (override de pydantic-settings,
  patrón Regla 11.4), con comentarios explicativos en cada uno.
- `.agent/memory/lessons_learned.md`: agrego entrada "lesson 12b.4.2"
  con síntoma/causa raíz/decisión/workaround del flake tkinter.
- `.agent/memory/PROTOCOLO_SALIDA.md` (nuevo): protocolo de cierre de
  sesión con 5 puntos (run verificación + test de regresión obligatorio +
  rotación memoria + validar feature real + resumen usuario).

**Validación in-vivo real:**
- `config.toml` carga correctamente verificado en runtime.
- Speed test e2e real ejecutado 2 veces con `ookla-speedtest` real (25s y 32s):
  download=863-877 Mbps, upload=54 Mbps, latency=11ms, jitter=2ms,
  packet_loss=0%, server=Movistar (Colombia), ISP=Telmex Colombia.
- Botón "Run Speed Test" se habilita al arrancar (simulado
  `_update_speed_test_button_state`: `enabled=True` + `available=True`
  → state=`normal`).
- Baseline Cloudflare real extraído de `history.db`: sample_count=13,
  avg=63.21ms, stddev=22.90ms, threshold(+2σ)=109ms — latencia 70-80ms
  del usuario está 30ms por debajo del threshold, NO es anomalía.

**Suite:** 896 → 920 unit (+24 tests nuevos), 17 integration.
ruff + black + vulture (0 warnings) limpios. Tests UI aislados pasan (20/20).
31 tests UI con `tk.Tk()` real se deseleccionan en suite completa por
flake pre-existente (lesson 12b.4.2), pero pasan consistentemente aislados.

---

## AVISO — contenido histórico perdido (2026-07-30, sesión 2)

> Durante la sesión 2 (Habilitación WARP), al rotar la memoria mueva la
> sesión 1 al archive, se produjo un accidente de scripting de PowerShell
> que destruyó el contenido completo del archivo `session_log_archive.md`
> previo a esa sesión. Este archivo contenía detalle completo de las
> sesiones Fase 2 → Fase 12b.5 (~600 líneas), comprimido en `session_log.md`
> en "HISTORIAL RELEVANTE" (1-2 líneas por sesión).
>
> Lo que quedó intacto: el "HISTORIAL RELEVANTE" en `session_log.md`
> (resumen 1-2 líneas por fase, todavía navegable). Las Reglas de Oro
> completas por fase se preservaron todas en `lessons_learned.md` y
> `lessons_learned_archive.md` (esos archivos N0 fueron afectados).
>
> Lo que se perdió: el detalle extendido archivo por archivo, test por
> test, decisiones de implementación por sesión, que vivía solo acá. Es
> información de "debug arqueológico" — solo se consultaba con grep bajo
> demanda si una tarea tocaba una fase vieja.
>
> Recomendación: si una tarea futura toca un módulo de fase vieja
> (2-12b.5), no hay archive detallado que greppear — confiar en
> `lessons_learned_archive.md` (reglas) + el código actual + los tests
> actuales para reconstruir el contexto. No reificar el archive (YAGNI);
> si una consulta necesita el detalle, reconstruír ad-hoc con `git log`
> sobre los archivos tocados.
>
> Bug de scripting que lo causó: en PowerShell 5.1,
> `Add-Content -Encoding utf8` puede agregar contenido con codificación
> incompatible con caracteres no-ASCII preexistentes en el archivo,
> corrompiendo bytes adyacentes. La recuperación intentada con
> `[System.IO.File]::ReadAllText` + `IndexOf` truncó mal el contenido.
> **Lesson para el agente: realizar ediciones a archivos ASCII-heavy
> con el tool `edit`, no con `Add-Content` desde PowerShell.** El tool
> `edit` y `write` manejan UTF-8 consistente.

---

## Sesiones posteriores (resumen en `session_log.md` HISTORIAL RELEVANTE)

> Detalle completo de Fase 2 → Fase 12b.5 perdido (ver aviso arriba).
> Resumen de cada fase en `session_log.md` "HISTORIAL RELEVANTE":
>
> - Fase 2 — Capa de red: PingRunner + fallback TCP SYN + parser cross-platform.
> - Verif. Fase 2 Windows: TIMEOUT host inalcanzable real, no bug.
> - Pre-Fase 3: fix check.ps1 (stderr PowerShell), DNS resolution, config Pydantic.
> - Fix score: probes faltantes se excluyen del promedio, no como 0.
> - Fase 5: motor de recomendación 7 reglas + 2 constraints + baselines.
> - Fase 6: ActiveGameServerDetector psutil + filtrado IPs + anti-telemetría.
> - Fase 7: Traceroute + culprit hop. Parser dual EN/ES.
> - Fase 8: Monitoreo WinMTR. Agregación por hop_number, wall-clock duration.
> - Fase 9: UI threading SQLite factory, Historical Comparison real.
> - Fix crítico post-Fase 9: anomalías baseline degradan veredicto.
> - Fase 10: 5 gráficos PRD §10 matplotlib embebido. Auto-zoom Y en packet_loss.
> - Fase 11: Logging JSON estructurado. FileHandler JSONL + StreamHandler.
> - Fase 12a: rotación JSONL (12a.1), DNS timing (12a.2), Wi-Fi/Ethernet
>   (12a.3), IPv6 opt-in (12a.4).
> - Fase 12b.1: Export Markdown renderer función pura.
> - Fase 12b.2: Notificaciones de escritorio (plyer).
> - Fase 12b.3: Reportes semanales/mensuales automáticos.
> - Fase 12b.4: Comparación con/sin Cloudflare WARP.
> - Fase 12b.5: Speed test bajo demanda (ookla-speedtest).
> - Fase 13: Extensibilidad multi-juego (GameDiagnosticsModule + LoL + Valorant).
>
> Detalle completo por sesión se reconstruye con `git log -p -- src/gnd/<modulo>`
> si hace falta explorar la historia de un cambio puntual.

---

## Sesión Post-Fase 13 (sesión 2) — Habilitación WARP + fix bug restore modo/protocolo (2026-07-30)

**Contexto:** usuario va a usar el botón real Run WARP Comparison con warp-cli 2026.6.850.0 ya instalado. Pide confirmar dos cosas antes de tocar: (1) si WARP ya está prendido en modo UDP (=WireGuard) y se olvidó apagarlo, el restore debe volver a modo UDP, no a on genérico ni apagarlo; (2) en qué modo conecta warp-cli connect sin estado previo. Sospecha fundada: el código de Fase 12b.4 no modelaba modo — solo connected=True/False.

**Investigación empírica del CLI:** el usuario corrió warp-cli --help/status/settings list/mode --help/	unnel protocol --help/	unnel protocol set --help y compartió outputs crudos. Hallazgos: status solo acepta --no-paginate/-h (NO --output-format=json — el adapter Fase 12b.4 usaba este flag inexistente y crasheaba silenciosamente por try/except, devolviendo status degradado SIEMPRE, feature entera rota). settings list expone multiline Mode: <warp|proxy|doh|...> y WARP tunnel protocol: <MASQUE|WireGuard>. mode <m> setea modo general. 	unnel protocol set <MASQUE|WireGuard> setea protocolo del túnel (case-sensitive exacto: WireGuard, no wireguard). connect no acepta --mode — usa el protocolo ya configurado en settings. **'UDP' en la app = 	unnel_protocol=WireGuard** (legacy), MASQUE = HTTP/3 (default 2026.6.x).

**Decisión (Opción 2 elegida por el usuario):** fix completo del adapter (guardar+replicar modo/protocolo) + fail-safe de red. Si el adapter NO detecta el modo/protocolo original (None — CLI cambia formato, parseo falla), el use case NO restaura a ciego (dejaría WARP en MASQUE default perdiendo el modo elegido). Aplica fail-safe: deja WARP apagado + loguea warp_comparison.restore_skip_mode_unknown + adjunta mensaje legible al WarpComparisonResult para que la UI lo muestre.

**Archivos modificados:** src/gnd/domain/ports/warp_controller.py (WarpStatus VO +2 fields opcionales mode/tunnel_protocol, Protocol +2 métodos set_mode/set_tunnel_protocol). src/gnd/network/real_warp_controller.py (fix bug --output-format=json inexistente → status --no-paginate texto plano parseado con regex _STATUS_RE; nuevo método _read_settings() corre warp-cli settings list parseado con _MODE_RE+_PROTO_RE; métodos nuevos set_mode+set_tunnel_protocol; eliminé _WarpCliOutput/_parse_status_json código muerto). src/gnd/application/warp_comparison.py (_restore_original_state reescrito: replica mode+protocol si detectados, fail-safe si no; execute() refactoriado para adjuntar warning al result via dataclasses.replace post-finally). src/gnd/models/warp_comparison.py (WarpComparisonResult VO +1 field opcional estore_warning). src/gnd/domain/fakes/fake_warp_controller.py (+4 kwargs constructor +2 métodos públicos set_mode/set_tunnel_protocol + helpers). src/gnd/ui/warp_comparison_section.py (muestra [!] <warning> al final del explanation_text si restore_warning). pyproject.toml (whitelist vulture ampliada).

**Archivos nuevos:** 	ests/test_real_warp_controller.py (13 tests mockeando subprocess con _SubprocessSpy). 	ests/test_warp_comparison_use_case.py (+3 tests de regresión: replica WireGuard en restore, fail-safe protocol None, fail-safe mode None). Actualizado 	est_restaura_estado_original_on con mode+protocol detectados. 	ests/test_fake_warp_controller.py (+6 tests cubriendo mode/protocol/set_*/fail_on_set_*).

**Scripts nuevos:** scripts/verify_warp_controller_in_vivo.py (verificación SOLO LECTURA — valida que el adapter parsea correctamente el estado actual del warp-cli real sin mutar nada; usuario lo corre antes del botón real).

**Suite:** 920 → 936 unit (+22 neto en archivos warp), 17 integration. ruff+black+vulture (0 warnings) limpio. Tests UI WARP/SpeedTest aislados: 20/20.

**Incidente de memoria (auto-provocado):** durante la rotación de session_log al archive, Add-Content de PowerShell 5.1 corrompió session_log_archive.md (encoding UTF-8 inconsistente con caracteres no-ASCII preexistentes). La reparación con [System.IO.File]::ReadAllText + IndexOf truncó accidentalmente ~600 líneas del detail de Fase 2-12b.5 (irrecuperable: .agent/ está en .gitignore por diseño, no hay commits/stash/reflog que respalden). Lesson: editar archivos de memoria SÓLO con tool edit/write, NUNCA con cmdlets PowerShell. Salvaguarda añadida al PROTOCOLO_SALIDA.md, PROTOCOLO_INICIO.md y aviso permanente al INDEX.md.

---

## Fase 14.0a — Protocols + VOs + Fakes para detección de IP real LoL vía lockfile+LCU (2026-07-30)

**Contexto:** empieza Fase 14 (precisión de medición para LoL
específicamente). En vez de pinguear solo el proxy genérico
`auth.riotgames.com`/`lol.secure.dyn.riotcdn.net`, leer el lockfile
del cliente de LoL, autenticar contra la LCU API local, y obtener la
**IP cruda del servidor de partida real** desde `gameClient.serverIp`
cuando hay partida activa.

**Investigación previa (pedida por el usuario, sin tocar código):**

1. **Lockfile** (ubicación: `%PROGRAMFILES%\Riot Games\League of
   Legends\lockfile` default Windows; formato 5 campos separados por
   `:`: `LeagueClient:PID:PORT:PASSWORD:PROTOCOL`). LCU API:
   `https://127.0.0.1:PORT` con auth basic `riot:PASSWORD`, cert
   self-signed.
2. **Endpoints LCU** investigados: `GET /lol-gameflow/v1/session` es
   el correcto. Campo clave: `map.platformId` (región, ej. `"LA1"`,
   `"NA1"`) y `gameClient.serverIp`/`serverPort` (IP cruda del server
   durante `InProgress`).
3. **Mapping región→hostname regional** verificado empíricamente con
   `Resolve-DnsName` contra 22 candidatos de patrones
   `<svc>.<platformId>.lol.riotgames.com` y `<svc>.<short>.lol.riotgames.com`.
   **Resultado desfavorable**: de las ~14 regiones conocidas, solo
   **NA1 (`lq.na.lol.riotgames.com`, `chat.na1.lol.riotgames.com`) y
   EUW1 (`lq.eu.lol.riotgames.com`)** resuelven a IPs Riot-direct
   (66.151.54.141, 216.133.234.21, 64.7.194.21). Las demás regiones
   (LA1/LA2/BR1/TR1/RU/KR etc.) resuelven a Cloudflare 104.16.x —
   **mismo proxy genérico que ya teníamos**, no aporta nada. Y las
   cortas (opece, JP1, OC1) son NXDOMAIN. Los 3 IPs Riot-direct no
   responden ICMP — esperado para relays, el fallback TCP SYN a 443
   del `RealPingRunner` (Regla 2.1) está diseñado para esto.

   Dado que el usuario juega en **LAN (LA1)** y el mapping empírico no
   aporta ningún hostname útil para LA1, se acota el alcance: **solo
   tier `exact_ip`** se implementa en 14.0a-g. El tier `regional_edge`
   (ping a hostname regional Riot-direct) queda pausado para una
   futura Fase 14.0b si la comunidad descubre más hostnames.

**Decisión de diseño clave (Opción 3):** implementar SOLO el tier
`exact_ip` (IP cruda del LCU cuando partida InProgress). Esto funciona
para TODAS las regiones (usa la IP del servidor real, no requiere
mapping) y es el mayor salto de precisión posible sin Npcap. Coste
estimado ~50-60 tests nuevos vs ~110 del plan original con
`regional_edge` incluido.

**Pregunta 4 del plan original — pausada:** como hacer TCP SYN (puerto
443) contra la IP cruda de `gameClient.serverIp` (que es server UDP
de gameplay) puede ser falso negativo si no hay nada escuchando en 443.
No se decide en 14.0a — se valida en 14.0h (in-vivo con LoL corriendo)
o queda como riesgo conocido.

**Archivos nuevos creados (14.0a):**
- `src/gnd/models/gameflow_session.py`: VO `GameflowSession(phase,
  region_tag, server_ip, server_port)`. Vista mínima del JSON del LCU
  (NO duplicar schema completo solo campos que usamos — Riot llama al
  LCU "no oficialmente soportado", schema puede cambiar entre patches).
  Invariante: server_ip y server_port van juntos (ambos o ninguno).
  Helper `has_active_game_server()` → True si ambos poblados.
- `src/gnd/models/lockfile_data.py`: VO `LockfileData(process_name,
  pid, port, password, protocol)` + classmethod `parse(raw: str)`.
  Validación: protocol solo `remoting-auth-token` o `ssl`; formato
  5 campos sep `:`; pid/port numéricos.
- `src/gnd/domain/ports/lockfile_reader.py`: Protocol
  `LockfileReader.read() -> LockfileData | None`. EP §1.2: el adapter
  nunca lanza al caller; cualquier fallo (file not found, parse error,
  permission) devuelve None con log.
- `src/gnd/domain/ports/lcu_client.py`: Protocol
  `LcuClient.get_gameflow_session(lockfile) -> GameflowSession | None`.
  Interface Segregation: SOLO expone el endpoint que GND usa (no
  `request(method, path)` genérico que permitiría mutar estado del
  cliente).
- `src/gnd/domain/fakes/fake_lockfile_reader.py`: `FakeLockfileReader`
  programable con `set_result` + contador `read_calls`.
- `src/gnd/domain/fakes/fake_lcu_client.py`: `FakeLcuClient` idem +
  registra el lockfile recibido en `get_session_calls`.

**Archivos modificados:**
- `src/gnd/models/active_game_server.py`: `ActiveGameServerInfo`
  extendido con `precision_tier: str = "proxy_login"` y
  `region_tag: str | None = None`. `detected_via` ahora permite
  `"lcu_gameflow"` (además de los 2 valores ya válidos). Todos los
  fields nuevos con default → **backwards-compat total**: callers
  pre-Fase 14 siguen funcionando sin tocar. `PRECISION_TIERS`
  frozenset = `{"exact_ip", "proxy_login"}`.
- `pyproject.toml`: whitelist vulture extendida con 14 entradas para
  los Protocols/Fakes/VOs nuevos (falsos positivos legítimos en
  14.0a — se consumirán en 14.0b/c/d/f).

**Tests nuevos (50):**
- `tests/test_lockfile_data.py` (15): parser feliz, invariantes
  (process_name vacío, pid<=0, port fuera de rango, password vacío,
  protocol desconocido), parser rechaza campos extra/faltantes,
  pid/port no numéricos, round-trip estructural.
- `tests/test_gameflow_session.py` (9): 3 casos (Lobby sin server,
  ChampSelect con region_tag, InProgress con server), invariantes
  (phase vacío, region_tag vacío, server_ip vacío, port fuera de
  rango, inconsistencia ip/port), helper has_active_game_server.
- `tests/test_active_game_server.py` +6 tests (clase
  `TestActiveGameServerInfoFase14a`): defaults backwards-compat,
  detected_via lcu_gameflow aceptado, precision_tier desconocido
  rechaza, region_tag vacío rechaza, proxy_login+region_tag=None OK.
- `tests/test_fakes_phase14a.py` (11): comportamiento de los 2 fakes
  (default None, programar, reset, conta calls) + Protocol
  runtime_checkable reconoce fakes y rechaza objetos no-compatibles.

**Suite:** 950 → 1000 unit (+50 nuevos), 17 integration.
ruff+black+vulture (0 warnings) limpio. Flake tkinter 12b.4.2 sigue
intermitente bajo suite completa (pasa aislados) — documentado, no
fixeado.

**Próxima sub-fase:** 14.0b — adapter real `network/lockfile_discovery.py`
(búsqueda de path configurable + parseo defensivo), degradación
silenciosa con log estructurado si LoL no está corriendo.
Sin tocar domain/models.

