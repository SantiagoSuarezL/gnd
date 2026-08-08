# Tech Stack — Game Network Diagnostics (GND)

## Stack Actual (Fase 0-11 completadas)

> Post-Fase 13 (sesión 1): bug `config.toml` de Fase 0 fixeado. `GndSettings.load()`
> ahora usa `TomlConfigSettingsSource` via `settings_customise_sources`
> + subclass dinámica en `load()` (pydantic-settings v2 no carga TOML
> automáticamente; antes usaba `_env_file=path` que es solo para `.env`).
> Ver `session_log_archive.md` (Post-Fase 13) y
> `tests/test_config_toml_loading.py` (test de regresión).
>
> Post-Fase 13 (sesión 2): bug `RealWarpController` flag `--output-format=json`
> inexistente en warp-cli 2026.6.x (fixeado → `status --no-paginate` texto
> plano + regex). El adapter detecta `mode` (warp/proxy/doh) y
> `tunnel_protocol` (WireGuard=UDP/MASQUE) via `warp-cli settings list` y
> los replica en el restore (Regla 12b.4.2 + 12b.4.3: restore fiel, no a
> ciego + fail-safe si parseo falla). Ver `session_log.md` y
> `lessons_learned.md` Regla 12b.4.3, `tests/test_real_warp_controller.py`.

**Lenguaje:** Python 3.12+ (cambiado de 3.13+ por entorno real del usuario)

**Dependencias principales:**
- `pydantic>=2.0` — validación de modelos y settings
- `pydantic-settings>=2.0` — `GndSettings(BaseSettings)` (Fase 0)
- `psutil>=5.9,<8` (runtime 7.2.2) — enumeración de conexiones de proceso (Fase 6)
- `matplotlib>=3.7,<4` (runtime 3.11.1) — gráficos embebidos en tkinter (Fase 10, `FigureCanvasTkAgg`)
- `pytest>=8.0` + `pytest-asyncio>=0.23` + `pytest-cov` — testing
- `ruff>=0.5` — linter único (E, F, I, UP, B)
- `black>=24.0` — formatter (line-length=88)
- `vulture>=2.16` (dev) — detección de código muerto (Fase 9, ver Regla de Oro 9.5)
- `logging` (stdlib) —	logging estructurado JSON (Fase 11). NO se introduce lib externa (structlog/loguru); EP §5 exige stdlib + Formatter propio.

**Capa de red (Fase 2 + 12a.4):** `subprocess` + `ping` nativo del OS, `socket.create_connection` fallback TCP SYN. `RealPingRunner` inyecta `ProcessRunner(Protocol)`. **Fase 12a.4:** soporte IPv6 opt-in vía flags `-4`/`-6` (Windows) o `ping6`/`traceroute -6` (POSIX), `family` kwarg en `PingRunner`/`TracerouteRunner` protocols, propagado a `ProbeResult.family`/`TracerouteResult.family`. Schema v3 con columna `family` en `probe_results`/`traceroute_results` (default 'ipv4').

**Capa de traceroute (Fase 7):** wrapper sobre `tracert.exe`/`traceroute`, parser dual EN/ES en `network/tracert_parser.py`, `detect_culprit_hop()` en `real_traceroute_runner.py`.

**Capa de monitoreo (Fase 8):** `monitoring/route_monitor.py` (orquesta N traceroutes), `monitoring/aggregator.py` (agregación pura), `database/sqlite_monitoring_repository.py` (schema v2), DI completa (TracerouteRunner + Sleeper + Clock).

**Capa UI (Fase 9):** `tkinter` (stdlib) dark mode, `ThreadPoolExecutor` + `threading` + `root.after(0, callback)`, `DatabaseConnectionFactory` (conexión SQLite por hilo).

**Capa visualización (Fase 10):** `matplotlib` embebido en tkinter via `FigureCanvasTkAgg`.     `visualization/`: `models.py` (`ChartDataSet`, `SeriesPoint` inmutables), `ports.py` (`SeriesDataSource` Protocol), `queries.py` (`SqliteSeriesDataSource`), `charts.py` (5 funciones puras `ChartDataSet → Figure`). `ui/charts_section.py`: pestaña 6ta con scroll + botón Refresh + auto-refresh tras run.

**Capa logging (Fase 11):** `logging/` paquete nuevo. `logging/`: `formatter.py` (`JsonFormatter` — 1 registro = 1 línea JSON; campos canónicos `ts`/`level`/`logger`/`message` + contexto `run_id`/`provider`/`event` si presentes + extras del caller; `exc` con stacktrace multilinea si exc_info; omite campos `None`), `context.py` (`RunContextAdapter` LoggerAdapter con run_id/provider inyectados, caller extra PISA contexto), `configurer.py` (`build_default_handlers(logs_dir, stream, now)` = FileHandler JSONL diario `gnd_YYYYMMDD.jsonl` nivel DEBUG + StreamHandler stderr mismo formatter nivel WARNING; `configure_logging(handlers, level, replace_previous=True)` idempotente). Setup invocado desde `__main__.py`, configuración leida de `GndSettings.logging` (`logs_dir`, `level`, `console_level`). Alternativa contextvars+Filter considerada y descartada (Regla 11.1, YAGNI vs 9.5).

**Capa notificaciones (Fase 12b.2):** `notifications/` paquete nuevo. `notifications/`: `plyer_notifier.py` (`PlyerDesktopNotifier(app_name, timeout_seconds)` adapter de `plyer.notification`; import DEFERIDO en `__init__` — si plyer falta, `_available=False` y `.notify()` es no-op con log; captura `NotImplementedError`/`OSError`/`RuntimeError` del backend OS; emite eventos `notification.start`/`finish`/`error`/`skip`), `run_formatter.py` (función pura `build_run_notification(run, notify_only_on_issues) -> DesktopNotification | None`; mapea verdict → label humano ES; devuelve None si filtrado `notify_only_on_issues=True` y verdict=safe). VO `DesktopNotification(title, message)` en `models/notification.py`. Protocol `DesktopNotifier` en `domain/ports/notifier.py`. Fake `FakeDesktopNotifier` en `domain/fakes/`. Wiring via `build_notifier()` en `composition_root.py` (mismo patrón que `build_series_source` 10). UI integration: `_maybe_send_notification(run)` al final de `_apply_run` (main loop, plyer.notify blando <10ms).

**Capa games / multi-juego (Fase 13):** `models/game_endpoint.py` (VO `GameEndpoint(host, provider, family)` frozen — el módulo de juego declara provider+family, así `analysis/` lo trata como key de baseline opaca sin saber qué juego es). `domain/ports/game_diagnostics_module.py` (Protocol `GameDiagnosticsModule` runtime_checkable, 4 métodos: `public_endpoints() -> list[GameEndpoint]`, `process_names()`, `detect_active_server()`, `game_server_provider()`). `diagnostics/games/` sub-paquete: `league_of_legends.py` (`LeagueOfLegendsModule` adapter sobre lógica Riot existente — lee `targets.riot_public`+`riot_public_ipv6` y `game_detection.process_names` perezosamente, delega `detect_active_server()` al `ConnectionInspector` inyectado, `game_server_provider()="riot_game_server"` histórico), `valorant.py` (`ValorantModule` — provider `"valorant_public"`, process `VALORANT-Win64-Shipping.exe`, `game_server_provider()="valorant_game_server"`, reusa `ConnectionInspector`). `domain/fakes/fake_game_diagnostics_module.py` (`FakeGameDiagnosticsModule` programable con `*_calls` + setters). Refactor `RunFullDiagnostics` kwarg `game_module=None` opcional (backwards-compat: si None, path Riot hardcodeado). Config `game_detection.active_game="league_of_legends"` (default). Builder `build_game_module(inspector)` en composition_root mapea string → impl, fail-fast `ValueError` para valor no reconocido. DoD blindado con 3 tests estáticos (`inspect.getsource`+`pkgutil.walk_packages` sobre `analysis/`/`recommendations/`/`database/` verificando ausencia de "valorant"). Regla de Oro 13.1.

**Capa speed test (Fase 12b.5):** `models/speed_test.py` (VOs `SpeedTestResult`, `SpeedTestDelta`, `SpeedTestComparisonResult` frozen). `domain/ports/speed_test_controller.py` (Protocol `SpeedTestController` + `SpeedTestError`). `domain/fakes/fake_speed_test_controller.py` (Fake con resultados programables). `network/real_speed_test_controller.py` (adapter real con `ookla-speedtest` subprocess, `--format=json`, import diferido Regla 12b.2.1). `application/speed_test_comparison.py` (`SpeedTestComparisonUseCase` que compone `RunFullDiagnostics` + `SpeedTestController` — Regla 12b.4.1). Pendiente: config, wiring, UI.

**Capa reportes (Fase 12b.3):** `reports/` paquete nuevo. `reports/`: `composer.py` (función pura `compose_period_report(runs, config, period_start, period_end) -> str | None` — header del período + agregados (avg/min/max score, verdict distribution, most_common_responsible_component) + lista compacta de runs (escapado Markdown Regla 12b.1.2) + top-K runs renderizados vía `render_run_to_markdown` de 12b.1; ranking por menor score, output cronológico; devuelve `None` si runs vacío), `scheduler.py` (`ReportsScheduler` con `threading.Timer` daemon, DI Clock + Sleeper + ReportWriter + DesktopNotifier; captura Exception y rearma Timer en `finally`; lifecycle start/stop idempotente; hook `tick_now()` para tests). VO `ReportConfig(period, top_runs, reports_dir, notify_on_generated, notify_only_on_clean_period)` en `models/report_config.py` + enum `ReportPeriod(WEEKLY|MONTHLY)`. Protocol `RunHistoryReader` en `domain/ports/run_history_reader.py`. Fake `FakeRunHistoryReader` en `domain/fakes/`. Adapter `SqliteRunHistoryReader` en `database/sqlite_run_history_reader.py` (lee `DiagnosticRun` completos en rango half-open [start, end) — reconstrucción bulk por `run_id IN (...)` evita N+1; `ensure_schema` idempotente al construct). Wiring via `build_report_pipeline()` en `composition_root.py`. UI integration: kwarg opcional `report_scheduler` en `MainWindow`, método `close()` registrado como `WM_DELETE_WINDOW` protocol (hook para `scheduler.stop()` antes de `destroy()`); arranca en `run()` solo si `settings.reports.enabled=True`.

**Arquitectura (Clean Architecture estricta):**
```
src/gnd/
├── models/           # Entidades inmutables (dataclass frozen) — 100% cobertura
├── domain/           # Puertos (Protocol) + Fakes in-memory
│   ├── ports/        # PingRunner, TracerouteRunner, ConnectionInspector,
│   │                 # DiagnosticsRepository, RecommendationEngine,
│   │                 # RouteMonitor, MonitoringRepository,
│   │                 # DatabaseConnectionFactory (Fase 9),
│   │                 # DnsResolver (12a.2), NetworkInterfaceInspector (12a.3),
│   │                 # DesktopNotifier (12b.2), RunHistoryReader (12b.3)
│   └── fakes/        # Implementaciones fake para testear sin red/DB
├── network/          # (Fase 2/7/12a) adaptadores de red real: RealPingRunner (IPv6), RealTracerouteRunner (IPv6), RealDnsResolver (12a.2), RealNetworkInterfaceInspector (12a.3)
├── monitoring/        # (Fase 8) orquestación monitoreo continuo
├── diagnostics/       # (Fase 6) orquestación de pruebas
│   ├── riot/          #   ActiveGameServerDetector (psutil) + LiveClientApi
│   └── games/         #   (Fase 13) módulos por juego (GameDiagnosticsModule): league_of_legends, valorant
├── analysis/          # (Fase 4) baseline histórico + Network Score
├── recommendations/    # (Fase 5) motor de reglas — 7 reglas + constraints
├── database/          # (Fase 3/8/9/12a) SQLite repositorio (schema v3 con family en probes/traceroutes) + ConnectionFactory
├── visualization/      # (Fase 10) gráficos
├── logging/            # (Fase 11) JsonFormatter + RunContextAdapter + configure_logging
├── export/             # (Fase 12b.1) render Markdown de DiagnosticRun — funcion pura, sin IO
├── reports/             # (Fase 12b.3) composer Markdown de periodo + scheduler periodic con threading.Timer (reusa export/)
├── config/             # (Fase 0) settings Pydantic
├── ui/                 # (Fase 9) tkinter dark mode
└── application/         # (Fase 9) RunFullDiagnostics — orquesta las 7 etapas
```

**Configuración tooling (pyproject.toml):**
- `requires-python = ">=3.12"`, `target-version = "py312"`
- `ruff.select = ["E", "F", "I", "UP", "B"]`
- `[tool.vulture]` con `min_confidence = 60` + whitelist documentada

**Configuración de logging (Fase 11, default configurable via GndSettings):**
- `logs_dir`: `%APPDATA%/GND/logs` (default), expande %APPDATA% en runtime.
- `level`: `"INFO"` para el root logger (el FileHandler captura todo lo que el root permita).
- `console_level`: `"WARNING"` (stderr handler más restrictivo — no saturea terminal).
- Archivo: `gnd_YYYYMMDD.jsonl` (un archivo por día, rotación trivial por nombre).

**Limitaciones v1 resueltas (Fase 12a.1):**
- **Rotación a medianoche:** `TimedRotatingFileHandler(when='midnight', backupCount=N)` reemplazó a `FileHandler`. Rotación automática a las 00:00 sin reiniciar la UI.
- **Retención automática:** `backupCount=config.Logging.retention_days` (default 30) purga logs más viejos que N días en cada rotación.

**Suite de tests:** 943 unitarios + 17 integration.

---

## Protocolos Críticos (Inamovibles)

> Regla corta y prescriptiva acá. La historia completa (bug, root cause, código)
> vive en `lessons_learned.md` o `lessons_learned_archive.md` — referenciada por
> número, no repetida.

1. **Separación estricta `models/` vs `domain/`** — ningún archivo en `models/`/`domain/` importa `psutil`, `sqlite3`, `subprocess`, `socket`. (Ref: 1.3)
2. **Ningún resultado de red es excepción** — `ProbeOutcomeKind = SUCCESS | FILTERED | UNREACHABLE | TIMEOUT`. `FILTERED` se excluye de baseline/score.
3. **Separación `riot_public` vs `riot_game_server`** — providers distintos en BD, baseline, motor de recomendación.
4. **Explicación obligatoria en recomendación** — `Recommendation.explanation: list[str]` nunca vacío.
5. **Inmutabilidad por defecto** — todos los modelos `@dataclass(frozen=True)`.
6. **Dependency Injection por constructor** — Protocol por `__init__`, wiring único en `composition_root`.
7. **Motor de recomendación: probes `None` = "desconocido", no "degradado"** (Ref: 5.1)
8. **psutil import diferido y encapsulado** (Ref: 6.1)
9. **IPs del game server vs `ProbeResult.target_ip`: propósitos distintos, no contaminan entre sí** (Ref: 3.1, 6.2)
10. **Filtrado de IPs más amplio que RFC1918 mínimo** — RFC1918 + loopback + link-local + CGNAT + TEST-NET + multicast. (Ref: 6.4)
11. **DoD de Fase 6 no tiene fixture reemplazable** — requiere partida real + `scripts/verify_phase6_windows.py`. (Ref: 6.3)
12. **Transparencia obligatoria al usar proxy `riot_public`** — `explanation` debe decir explícitamente cuándo se usa como proxy. (Ref: 6.7)
13. **psutil pin `<8`** por estabilidad de API `raddr`. (Ref: 6.6)
14. **Traceroute: parser Windows EN+ES + `culprit_hop_index`** sostenido≠pico. (Ref: 7.1, 7.2)
15. **Monitoreo WinMTR: agregar por `hop_number`, no por IP.** (Ref: 8.1)
16. **Invariante MonitoringSession: `samples=[]` + `hop_stats` no vacío = snapshot DB válido.** (Ref: 8.2)
17. **DI total en RouteMonitor: Sleeper + Clock inyectables**, nunca `time.sleep`/`datetime.now` directo en tests. (Ref: 8.3)
18. **Atomicidad repo: `save_session` = transacción única padre+hijos.** (Ref: 8.4)
19. **Schema v2 retro-compatibilidad: solo AÑADIR tablas, nunca modificar existentes.** (Ref: 8.5)
20. **Wall-clock duration en monitoreo: programar tomas ANTES, no medir elapsed después.** (Ref: 8.6)
21. **Threading SQLite: Factory pattern, una conexión por hilo, nunca compartida.** (Ref: 9.1)
22. **Paralelización de pings/traceroutes con `ThreadPoolExecutor`** para I/O subprocess-bound. (Ref: 9.2)
23. **Cache de resultados cross-thread (`last_baselines`)** en vez de re-consultar DB desde el main loop. (Ref: 9.3)
24. **Motor de recomendación debe reflejar anomalías de baseline en el veredicto**, no solo fallas absolutas. (Ref: 9.4)
25. **"ruff+black+pytest verde" NO es suficiente contra código muerto** — Vulture obligatorio antes de cerrar fase. (Ref: 9.5)
26. **Cualquier hop con `packet_loss > 0` y `responded=True` debe aparecer explícito en el resumen textual**, sin importar `n`. Blindado en `monitoring/aggregator.format_anomalies_text`. (Ref: 9.6)
27. **matplotlib embebido en tkinter: `plt.close(fig)` en cada refresh** para no acumular figures en pyplot global registry. `ChartsSection._clear_canvases` destruye widgets Tk + cierra figs. (Ref: 10.1)
28. **Tests de matplotlib: backend `Agg` forzado + `plt.close("all")` en fixture autouse** — no abren GUI, no acumulan figures entre tests. (Ref: 10.2)
29. **`SeriesDataSource` NO cierra las conns que recibe** — la factory es dueña del lifecycle. (Ref: 10.3)
30. **ChartsSection empty state: el renderer pinta el texto de "sin datos", la UI solo dispara refresh.** Decisión visual vs. orquestación. (Ref: 10.4)
31. **Gráfico packet_loss: auto-zoom del eje Y** con `min(100.0, max(5.0, max_y * 1.2))` — piso 5% (evita colapsar), headroom 1.2x (deja espacio sobre el pico), tope 100% (rango físico). Evita que datos típicos <2% queden aplastados contra el piso. (Ref: 10.5)
32. **Logging estructurado: `LoggerAdapter` por corrida, no `ContextVar` + Filter global** — explícito, sin estado global. Reservar contextvars para concurrencia real (no v1). (Ref: 11.1)
33. **`JsonFormatter` omite campos `None`** — nunca emitir `null` en `run_id`/`provider`/`event` ausentes; JSON tight = más queryable. (Ref: 11.2)
34. **Evento estructurado: `event` + `stage` obligatorios como keys queryables** — naming `<namespace>.<verbo>` (ej. `run.start`, `stage.error`, `ping.fallback_tcp_syn`). No incrustar en `message` humano. (Ref: 11.3)
35. **Vulture: overrides de ABCs/lib estándar (`LoggerAdapter.process`, `Formatter.format`) son falsos positivos** — son contratos de override invocados por la stdlib. Whitelistear, no borrar. (Ref: 11.4)
36. **TimedRotatingFileHandler: `backupCount` = `retention_days`** — mapeo directo: con `when='midnight'`, cada backup = 1 día. Sin días parciales. (Ref: 12a.1)
37. **DNS timing como etapa serial post-pings** — getaddrinfo es syscall corta (~30-80ms cached); 6 hosts serial = <500ms overhead. No requiere ThreadPoolExecutor (ahorro marginal, complejidad innecesaria). `RealDnsResolver` envuelve en Executor solo para timeout. (Ref: 12a.2)
38. **NetworkInterfaceInspector: netsh + regex EN/ES + timeout duro 3000ms** — en Windows, `netsh wlan show interfaces` puede colgar si el driver WLAN no responde. Timeout obligatorio (EP §1.2). Regex preparado para outputs EN y ES (idioma del SO no determinista). (Ref: 12a.3)
39. **Schema migration v2→v3: `ALTER TABLE ... ADD COLUMN family TEXT NOT NULL DEFAULT 'ipv4'` es retro-compatible** — añadir columnas a tablas existentes rompe la regla estricta "solo añadir tablas, nunca tocar existentes" (Protocolo 19), pero ADD COLUMN con DEFAULT no pierde info: las rows pre-migración reciben 'ipv4' automáticamente. Idempotente via PRAGMA table_info check (SQLite no soporta `ADD COLUMN IF NOT EXISTS` — OperationalError 'duplicate column name' si se reintenta). (Ref: 12a.4)
40. **IPv6 opt-in via config.targets.*_ipv6, sin flag aparte** — la presencia/ausencia de IPs en `DiagnosticTargets.{google_dns_ipv6, cloudflare_ipv6, quad9_ipv6, riot_public_ipv6}` determina si el orquestador duplica specs v6 (pings + traceroutes). No hay un flag booleano `ipv6_enabled` separado — YAGNI/TDA: los datos determinan, el flag sería redundante. Familia propagada a los resultados vía `family='ipv4'|'ipv6'` (default 'ipv4' en modelos para backwards-compat). Naming de targets con sufijo `:v6` para distinguir en logs/UI sin colisionar con el `provider`. (Ref: 12a.4)
41. **Export: renderer funcion pura, separado del MVC UI** — el renderer de un `DiagnosticRun` a string (Markdown por ahora) es función libre en `export/`, no clase con deps ni parte del MVC de la UI. Sin IO (el caller abre el path y escribe el str). Se omite el Protocol `RunRenderer` multi-formato — YAGNI mientras haya un solo formato (Markdown). Output tight: secciones opcionales (DNS/interfaz/game server) se omiten si no aplican (Regla 11.2 volcada a Markdown: omite > null). Escapado: pipes/backticks en CELDAS de tablas se escapan (rompen columnas); campos libres en líneas (headline) NO se escapan backticks — son code-inline válido de Markdown. (Ref: 12b.1)
42. **Libs de infraestructura externa: import DEFERIDO en `__init__` del adapter, no top-of-module** — generaliza Protocolo 8 (psutil). Toda lib externa (psutil, plyer, futuras) importada en un adapter se importa DENTRO del `__init__`, captura `ImportError` y marca `_available=False`; el método publico se vuelve no-op con log `event="<feature>.skip"` si está caído. EP §1.2 se respeta desde el constructor — el wiring (`composition_root`) nunca crashea al arrancar por lib faltante, el usuario ve UI y el toggle de settings la revive. (Ref: 12b.2.1)
43. **Filtrado de notif/eventos: omite > emitir payload degenerada** — cuando un feature "se suprime según una condición" (ej. `notify_only_on_issues=True` suprime verdict EXCELENTE), el formatter devuelve `None` y el caller hace no-op con log `<event>.skip` con `reason=...`. NO devolver un payload vacío (`DesktopNotification(title="", message="")`) — el VO valida campos no vacíos (raise) y aunque los permitiera, una notif/post/mensaje vacío es peor que no-emitir (el receptor lo muestra igual con UX rara). Misma logica que Regla 11.2 (omitir > null en JSON) aplicada a surfaces del OS / mensajería. (Ref: 12b.2.2)
44. **Lectura de runs históricos: puerto segregado + bulk reconstruction, NO extender repo de escritura** — para features que necesitan leer `DiagnosticRun` completos (export masivo, reportes, sync externo), crear Protocol + adapter nuevo (`RunHistoryReader` / `SqliteRunHistoryReader`), NO extender `SqliteDiagnosticsRepository` con queries de lectura (mezcla SRP, su docstring lo prohíbe desde Fase 3). El reader pide conn nueva por call via la misma factory (Regla 9.1) pero NO la cierra (la factory es dueña del lifecycle — cerrar rompe tests con `FakeDatabaseConnectionFactory` sobre conn compartida). Cuando reconstruye modelos compuestos (DiagnosticRun con probes/traceroutes anidados), usar queries bulk filtradas por `run_id IN (...)` — evita N+1 sobre runs grandes. Half-open range [start, end) consistente con `range()` Python y con el encadenamiento de períodos (end de uno = start del siguiente, sin doble conteo). (Ref: 12b.3.1)
45. **`threading.Timer` stdlib es one-shot: rearme manual en `finally` para hacerlo periódico** — `threading.Timer(interval, callback)` de stdlib dispara el callback UNA vez y termina (no es `setInterval`). Para schedulers periódicos, el callback debe ejecutar su lógica en try/except (capturar toda `Exception` con `event="<namespace>.error"` y NO reagendar en el except) y el `finally` rearma el siguiente tick SI el scheduler sigue `_started=True`. El hilo daemon nunca muere por un tick transitorio (EP §1.2 a nivel daemon). Lifecycle con `threading.Lock` + flag `_started` para que `start()`/`stop()` sean idempotentes y `stop()` corte el ciclo de rearme. Para tests, exponer un hook sincrónico (`tick_now()`) que ejecuta el callback sin rearma — permite verificar la lógica sin esperar tiempo real. (Ref: 12b.3.2)

46. **Comparación WARP: nuevo caso de uso que compone el existente + controlador de estado, NO extender caso de uso base** — para features que orquestan MÚLTIPLES runs del mismo caso de uso con estado mutado entre medio (WARP on/off, speed test antes/después), crear un NUEVO caso de uso que COMPONGA el existente + un controlador de estado (WarpController, SpeedTestController), NO extender el caso de uso original con flags condicionales. El nuevo caso de uso es dueño del lifecycle: save state → mutate → run → mutate → run → restore → compute deltas. Separación de responsabilidades: el caso de uso base (RunFullDiagnostics) sigue siendo "una corrida"; el comparador es "dos corridas + análisis". (Ref: 12b.4.1)

47. **Extensibilidad multi-juego: el módulo de juego DECLARA el provider en un VO, orquestador consume Protocol vía kwarg opcional backwards-compat** — para features por-plugin (multi-juego/multi-backend), NO pasar `list[str]` y dejar que el orquestador adivine el provider de baseline (lo acoplaría al primer plugin y rompería el DoD "no tocar analysis"). El plugin declara sus identificadores en un VO (`GameEndpoint(host, provider, family)`) — `analysis/`/`database/` tratan el provider como string opaco (key de baseline propia por juego). El orquestador añade un kwarg `game_module=None` OPCIONAL: si `None`, fallback al path hardcodeado de la fase anterior (backwards-compat total, tests previos no se rompen); si presente, specs de pings/traceroutes + detección + provider del probe-al-server vienen del módulo. `composition_root` expone `build_game_module(inspector)` que mapea `settings.game_detection.active_game` (string) → impl, fail-fast `ValueError` para valor no reconocido (config estática corrupta, no runtime de red). Bíndice el DoD con tests estáticos (`inspect.getsource` + `pkgutil.walk_packages` sobre los paquetes que NO debían tocarse, verificando ausencia del nombre del nuevo juego) — si una fase futura rompe el invariant, el test falla en CI. (Ref: 13.1)

48. **Subprocesses de infraestructura en Windows: SIEMPRE `CREATE_NO_WINDOW`** — cuando la app corre windowless (launcher `pythonw.exe` via VBS, post-Fase 14.0a), cada `subprocess.run` que invoca un binario de consola (ping, tracert, netsh, warp-cli, ookla-speedtest) abre UNA ventana de cmd propia que parpadea en pantalla (el usuario vio 6+2 terminales en Run Diagnostics, 6+2+1 en speed test, 6+2+6 en WARP). Fix: `subprocess_kwargs()` en `network/_subprocess_helpers.py` devuelve `{"creationflags": 0x08000000}` (CREATE_NO_WINDOW) solo en Windows — el proceso hijo corre invisible, la UI de tkinter queda como única surface. NO usar wrapper `cmd /c cd /d && ...` en el VBS para setear working directory: `cmd.exe` spawn su propio `conhost.exe` que también se ve como terminal parpadeante; `wsh.Run` hereda `CurrentDirectory` del Shell WSH si el proceso es windowless. Los tests mockean `subprocess.run` así que el flag no los afecta; 7 tests nuevos en `tests/test_subprocess_helpers.py`. (Ref: launcher VBS + post-Fase 14.0a)

---

## Empaquetado y acceso directo (post-Fase 14.0a)

**Decisión:** launcher VBS + venv local (no PyInstaller). Razones:
- Stack (matplotlib + tkinter + psutil + pydantic) tiene fricción
  conocida con hooks de PyInstaller — un `.exe` autónomo traería
  problemas de `importerror` con TCL/TK embebido y posibles falsos
  positivos de antivirus en binarios no firmados.
- El repo sigue activo (Fases 14.0b-h pendientes); PyInstaller forzaría
  rebuild en cada cambio de código, mientras el VBS ejecuta `python -m gnd`
  contra el código vivo sin intervención.
- El usuario es único, el workspace vive en una máquina; no hay
  audiencia que justifique la portabilidad self-contained.
- DB/logs/reports ya usan `%APPDATA%/GND/` con `os.path.expandvars`
  (no rutas relativas) — el launcher no rompe nada.

**Archivos creados:**
- `launch_gnd.vbs` (repo root): wrapper WSH que deriva el repo root
  desde `WScript.ScriptFullName` (sobrevive movimientos del repo),
  fuerza el working directory del proceso hijo via `cmd /c cd /d "repo"
  && "pythonw.exe" -m gnd` (porque `wsh.Run` no garantiza heredar
  `CurrentDirectory`), y corre `pythonw.exe` (no `python.exe`) para que
  no abra consola. `WindowStyle=0` + `cmd /c` ocultan todo. Si el venv
  o `pythonw.exe` no existen, muestra un `MsgBox` claro.
- `scripts/install_shortcut.ps1`: crea/actualiza `GND.lnk` en el escritorio
  del usuario. `TargetPath=wscript.exe`, `Arguments="launch_gnd.vbs"`,
  `WorkingDirectory=repoRoot`, `IconLocation=%SystemRoot%\System32\imageres.dll,19`
  (ícono "Network and Sharing Center" — estable entre Win10/11, cero
  archivos nuevos, sin dependencias). Idempotente (sobrescribe el
  `.lnk` si ya existe). Auto-detecta el repo root via `$PSScriptRoot`.

**Mantenimiento futuro:**
- **Cambio de código Python:** NO requiere acción — el VBS ejecuta
  `python -m gnd` contra el código vivo del repo. La siguiente vez
  que el usuario abra el `.lnk`, corre la versión nueva.
- **Cambio de dependencias en el venv** (`pip install` nuevo): NO
  requiere acción con el launcher — el VBS usa el `pythonw.exe`
  del venv tal cual.
- **Movimiento del repo a otra ruta:** re-correr `scripts/install_shortcut.ps1`
  para regenerar el `.lnk` con el nuevo path absoluto. El VBS mismo
  deriva paths relativos a su propia ubicación, así que sigue
  funcionando sin cambios (siempre que siga en el repo root).
- **Migración futura a PyInstaller** (si en algún momento el repo
  deja de tener venv en esa máquina, ej. se quiere redistribuir): el
  VBS se borra y se apunta el `.lnk` directamente al `.exe`. La
  estructura del repo no cambia.

**Cómo correr la verificación visual después de cualquier cambio del launcher:**
- Doble-click en `GND.lnk` → debe abrir la UI sin terminal visible,
  con el ícono de Network and Sharing Center.
- Si no abre, `Stop-Process -Name "pythonw" -Force` (limpia zombies),
  relanzar el `.lnk`.
- Para debug, `cscript //nologo launch_gnd.vbs 2> gnd_console_debug.log`
  permite capturar stderr de `python.exe` (no `pythonw.exe` —
  este último no redirige output). Archivo ignorado en `.gitignore`.