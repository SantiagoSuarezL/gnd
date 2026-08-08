# Graph Report - .  (2026-07-28)

## Corpus Check
- 142 files · ~72,115 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1684 nodes · 4106 edges · 100 communities (82 shown, 18 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 538 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- 50
- Api
- Repository
- Baseline
- Fakedatabaseconnectionfactory
- Errorcallback
- Monitoringsample
- Engine
- Faketracerouterunner
- Repository
- 99
- Window
- Repository
- Protocol
- 43
- Fakeaddr
- Basemodel
- Hop
- Ipv4
- Windows
- Connection
- Parse
- Runner
- Init
- Empty
- Init
- Engine
- Charts
- Frame
- Axes
- Init
- Fakeseriesdatasource
- Historicalbaseline
- 282
- Architecture
- Set
- Conftest
- Main
- Fakeconnectioninspector
- Parser
- Anomaly
- Fix
- Baseline
- Init
- 24
- Bug
- Models
- Text
- Anomalies
- Runner
- Jitter
- Path
- Anomaly
- 97
- Probe
- Source
- En
- Session
- Exception
- 126
- Integration
- Genuine
- Windows
- Datetime
- Evidence
- Parser
- Probe
- Windows
- Latency
- Processrunner
- Connectivity
- Windows
- Ipv4
- Processrunner
- Running
- Theme
- Unreachable
- Outcome
- Init
- Modules
- Decisions
- Conventions
- Strategy
- Scope
- Metrics
- Configuration
- Gnd
- 12
- 11
- Timeout
- Failure
- Unreachable
- Loss
- Timeout

## God Nodes (most connected - your core abstractions)
1. `ProbeResult` - 90 edges
2. `TracerouteResult` - 76 edges
3. `TracerouteHop` - 68 edges
4. `HistoricalBaseline` - 67 edges
5. `MonitoringSample` - 57 edges
6. `_probe()` - 51 edges
7. `FakeTracerouteRunner` - 50 edges
8. `RealPingRunner` - 49 edges
9. `evaluate_recommendation()` - 48 edges
10. `MonitoringSession` - 47 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `all_renderers()`  [INFERRED]
  scripts/verify_phase10_charts.py → src/gnd/visualization/charts.py
- `main()` --calls--> `SqliteSeriesDataSource`  [INFERRED]
  scripts/verify_phase10_charts.py → src/gnd/visualization/queries.py
- `_AllTimeoutProcess` --uses--> `RealPingRunner`  [INFERRED]
  scripts/verify_phase2_fallback_genuine.py → src/gnd/network/real_ping_runner.py
- `Listener` --uses--> `RealPingRunner`  [INFERRED]
  scripts/verify_phase2_fallback_genuine.py → src/gnd/network/real_ping_runner.py
- `print_anomalies()` --calls--> `format_anomalies_text()`  [INFERRED]
  scripts/verify_phase8_windows.py → src/gnd/monitoring/aggregator.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Riot IP Distinction (Public vs Game Server)** — readme_riot_public_ip, readme_game_server_ip, docs_architecture_three_layer_riot_connectivity, docs_technical_spec_network_protocols [EXTRACTED 1.00]
- **Recommendation Pipeline (Network → Analysis → Verdict)** — docs_technical_spec_network_protocols, docs_technical_spec_analysis, docs_technical_spec_recommendation_engine, docs_prd_user_stories [EXTRACTED 1.00]
- **Test Fixtures for Ping Parsing** — tests_fixtures_ping_outputs_linux_success, tests_fixtures_ping_outputs_linux_all_timeout, tests_fixtures_ping_outputs_windows_general_failure, docs_engineering_principles_testing_strategy [INFERRED 0.75]
- **Ping Failure Scenarios** — tests_fixtures_ping_outputs_windows_host_unreachable, tests_fixtures_ping_outputs_windows_partial_loss [INFERRED 0.85]
- **Traceroute Latency Anomaly Scenarios** — tests_fixtures_tracert_outputs_windows_dod_salto_80ms_sostenido_en, tests_fixtures_tracert_outputs_windows_pico_un_solo_hop_en, tests_fixtures_tracert_outputs_windows_salto_sostenido_en [INFERRED 0.85]
- **Bilingual Traceroute Test Pairs** — tests_fixtures_tracert_outputs_windows_dod_salto_80ms_sostenido_en, tests_fixtures_tracert_outputs_windows_dod_salto_80ms_sostenido_es, tests_fixtures_tracert_outputs_windows_hop_sin_respuesta_en, tests_fixtures_tracert_outputs_windows_hop_sin_respuesta_es [INFERRED 0.95]

## Communities (100 total, 18 thin omitted)

### Community 0 - "50"
Cohesion: 0.08
Nodes (22): Guarda una sesion de monitoreo completa (sesion + stats por hop). Aborta la…, _empty_session(), FakeMonitoringRepository, FakeRouteMonitor, Fake in-memory RouteMonitor + MonitoringRepository para tests. EP §4 (testing…, Devuelve una MonitoringSession con 0 muestras y 0 stats. Helper para que…, RouteMonitor que devuelve sesiones pre-configuradas. Uso tipico en tests:…, MonitoringRepository en memoria. Guarda y devuelve por run_id. (+14 more)

### Community 1 - "Api"
Cohesion: 0.09
Nodes (19): HttpClient, LiveClientApi, Protocol, Cliente opcional de la Live Client Data API de Riot. Complemento secundario de…, Implementacion por defecto de HttpClient usando stdlib urllib. Sin dependencias…, Abstraccion de un cliente HTTP GET para tests sin requests real. Devuelve…, Cliente de la Live Client Data API de Riot (localhost:2999). Uso: api =…, True si la Live Client Data API responde 200 con JSON. Rapido (timeout 1.5s por… (+11 more)

### Community 2 - "Repository"
Cohesion: 0.09
Nodes (25): FakeDiagnosticsRepository, Fake in-memory DiagnosticsRepository para tests sin SQLite real., DiagnosticsRepository que guarda en memoria (lista)., Fakes in-memory de todos los Protocol del dominio. IMPLEMENTATION_PLAN.md Fase…, make_probe(), make_rec(), make_run(), make_traceroute() (+17 more)

### Community 3 - "Baseline"
Cohesion: 0.07
Nodes (28): Calculo de baseline historico por provider. TECHNICAL_SPEC.md §4.1: la…, Modulo de analisis historico y Network Score. TECHNICAL_SPEC.md §4. Calcula…, compute_network_score(), Network Score — ponderado 0-100 segun TECHNICAL_SPEC.md §4.2. Cada componente…, Computa el Network Score 0-100 (TECHNICAL_SPEC.md §4.2). Pesos base: Riot…, Caso de uso RunFullDiagnostics — orquesta una corrida completa. Application…, Puertos (Protocols) del dominio. Definidos en ARCHITECTURE.md §2 (capa…, Puerto ConnectionInspector — inspecciona conexiones de proceso. Diseñado para… (+20 more)

### Community 4 - "Fakedatabaseconnectionfactory"
Cohesion: 0.08
Nodes (42): FakeDatabaseConnectionFactory, Connection, Factory que devuelve ``sqlite3.Connection`` para tests. A diferencia de…, Args: shared: si no es None, ``create_connection()`` devuelve siempre esa…, _insert_probe(), _make_source(), Connection, datetime (+34 more)

### Community 5 - "Errorcallback"
Cohesion: 0.09
Nodes (26): ErrorCallback, ProgressCallback, ResultCallback, main(), Flux: main thread (composition_root) + worker thread (controller)., DiagnosticParams, DiagnosticTargets, Crea un ProbeResult TIMEOUT placeholder (defense-in-depth). (+18 more)

### Community 6 - "Monitoringsample"
Cohesion: 0.11
Nodes (15): MonitoringSample, Una sola muestra de un hop en una sesion de monitoreo. ``rtt_ms=None`` indica…, aggregate_hops(), fill_ip_hostname_mode(), Agregacion pura de muestras de monitoreo en estadisticas por hop. Logica…, Rellena ``HopStats.ip``/``hostname`` con la MODA de observaciones. El…, Agrega muestras en estadisticas por hop_number. Args: samples: iterable de…, Capa de orquestacion de monitoreo de ruta (Fase 8). TECHNICAL_SPEC.md §2.4 +… (+7 more)

### Community 7 - "Engine"
Cohesion: 0.07
Nodes (42): _filtered(), Tests del motor de recomendacion — Fase 5. Matriz de tests con TODAS las…, Google+CF+Quad9 todos degradados → ISP., Solo 2 DNS degradados → no match (rule 3 puede aplicar)., Solo 1 DNS degradado → no match., CF degradado, Google+Quad9 OK → cloudflare., CF+Google degradados → no match (rule 2 podria aplicar si Quad9 tambien)., Game server degradado, internet OK → riot, not_recommended_ranked. (+34 more)

### Community 8 - "Faketracerouterunner"
Cohesion: 0.17
Nodes (17): FakeTracerouteRunner, TracerouteRunner que devuelve resultados pre-configurados., FakeClock, FakeMonotonic, FakeSleeper, _make_sample_tracert(), _patch_monotonic(), Wrapper que avanza ``time.monotonic()`` en cada llamada a traceroute. Permite… (+9 more)

### Community 9 - "Repository"
Cohesion: 0.10
Nodes (22): Connection, Row, Implementacion real de ``Protocol MonitoringRepository`` sobre SQLite.…, Recupera todas las sesiones vinculadas a ``run_id``. Devuelve una lista…, Persiste y recupera ``MonitoringSession`` sobre SQLite. Una sola…, _row_to_hop_stats(), SqliteMonitoringRepository, HopStats (+14 more)

### Community 10 - "99"
Cohesion: 0.08
Nodes (26): Score de un solo probe de Internet: latencia vs benchmark. Benchmark = 20ms…, _score_single_probe(), ProbeResult, ParsedPing, Resultado de parsear el output de `ping`. Attributes: rtt_ms: lista de RTTs…, Devuelve (avg, min, max, jitter, samples) o None si no hay RTTs., Implementa `Protocol PingRunner.ping`. EP §2.L (Liskov): signature y contrato…, _constraint6_packet_loss() (+18 more)

### Community 11 - "Window"
Cohesion: 0.11
Nodes (18): MainWindow — ventana principal dark mode con 5 secciones (PRD §7). Fase 9…, CurrentStatusSection, _fmt_ms(), _format_probe_anomalies(), HistoricalComparisonSection, NetworkTestsSection, Any, Misc (+10 more)

### Community 12 - "Repository"
Cohesion: 0.13
Nodes (32): _make_probe(), _make_rec(), _make_run(), _make_traceroute(), Tests de SqliteDiagnosticsRepository - Fase 3. Solo prueba save_run()…, Compat legacy: expone ``._conn`` para tests pre-Fase-9. Tras el fix threading…, save_run escribe un row en diagnostic_runs., save_run escribe probes en probe_results con provider correcto. (+24 more)

### Community 13 - "Protocol"
Cohesion: 0.09
Nodes (24): Protocol, Ejecuta un traceroute hacia `target_ip` con `max_hops` y `timeout_ms`. Devuelve…, TracerouteRunner, Clock, _DefaultClock, _DefaultSleeper, datetime, Protocol (+16 more)

### Community 14 - "43"
Cohesion: 0.13
Nodes (28): PingRunner real via subprocess sobre `ping` nativo del OS. Detecta si esta en…, RealPingRunner, Tests unitarios de `network/real_ping_runner` con subprocess mockeado. No tocan…, ProcessRunner falso: devuelve (stdout, stderr, rc) prefijados., End-to-end: hostname se resuelve internamente, pero target_ip guarda el valor…, _StubProcess, _tcp_netunreach(), _tcp_timeout() (+20 more)

### Community 15 - "Fakeaddr"
Cohesion: 0.16
Nodes (12): _FakeAddr, _FakeConn, _FakeProc, _make_detector(), Construye un detector con ProcessEnumerator fake y SIN exclusion. Para tests de…, Proceso con 2 UDP publicas: una IP de riot_public, otra distinta. El detector…, Proceso falso con .info y .net_connections configurable., Si TODAS las conexiones UDP publicas coinciden con riot_public -> None. Esto… (+4 more)

### Community 16 - "Basemodel"
Cohesion: 0.10
Nodes (26): BaseModel, BaseSettings, main(), Perfil E2E del RunFullDiagnostics.execute() completo (paralelismo incluido).…, build_run_full_diagnostics(), build_series_source(), Composition root — wiring unico (EP §2.D y §3). Punto unico donde se decide QUE…, Descubre la IP del gateway local (router). Metodo robusto multiplataforma sin… (+18 more)

### Community 17 - "Hop"
Cohesion: 0.12
Nodes (17): detect_culprit_hop(), Valida que el salto de latencia en ``candidate_idx`` se sostiene en hops…, Detecta el indice (0-based) del hop culpable del salto de latencia. Algoritmo…, _sustained_jump(), _hops(), Tests unitarios de `detect_culprit_hop` \u2014 logica pura (Fase 7). Sin red,…, Hops que no responden no son culpables ni son previos validos., El threshold es configurable (TECHNICAL_SPEC.md \u00a76 thresholds). (+9 more)

### Community 18 - "Ipv4"
Cohesion: 0.09
Nodes (17): _looks_like_ipv4(), TracerouteRunner real via subprocess sobre `tracert` nativo de Windows. Detecta…, Implementa `Protocol TracerouteRunner.traceroute`. EP \u00a72.L (Liskov):…, Resuelve `target` (hostname o IPv4) a una IPv4. - Si ya es IPv4 (regex simple),…, TracerouteResult vacio: hops no vacio (invariante del modelo exige al menos 1…, RealTracerouteRunner, Tests de integracion RealTracerouteRunner contra red real (Fase 7). Marcados…, Tests contra red real. (+9 more)

### Community 19 - "Windows"
Cohesion: 0.10
Nodes (21): banner(), main(), Verificacion end-to-end de Fase 6 para correr en Windows real con LoL abierto.…, Resuelve un hostname a IPv4 (para comparar con el game server)., resolve_ipv4(), Conn, _DefaultRiotPublicHostsProvider, _ip_in_private_range() (+13 more)

### Community 20 - "Connection"
Cohesion: 0.09
Nodes (20): Connection, Factory que abre ``sqlite3.connect(path)`` por call. Patrones de uso: -…, Path absoluto expandido (para diagnostico/tests)., Abre una conexion nueva + ensure_schema. Caller es el dueno.…, SqliteConnectionFactory, factory_db_path(), _params(), fixture (+12 more)

### Community 21 - "Parse"
Cohesion: 0.15
Nodes (11): parse(), Parsea el output completo de `tracert` (Windows, EN o ES). No lanza excepciones…, load_tracert_fixture(), Lee un fixture de output de `tracert` por nombre (sin extension). Ver Fase 7,…, Tests unitarios del parser de `tracert` (Fase 7). Sin red: todos los tests…, Casos borde y validaciones., Cabecera: extraccion de target_ip y target_hostname (sin y con hostname)., Parseo de lineas de hop (RTT, IP, responded). (+3 more)

### Community 22 - "Runner"
Cohesion: 0.13
Nodes (9): Fake in-memory TracerouteRunner para tests sin red real., TracerouteHop, TracerouteResult, _DefaultProcessRunner, Implementacion por defecto: wrap de subprocess.run., _make_traceroute_result(), Tests de TracerouteHop y TracerouteResult., TestTracerouteHop (+1 more)

### Community 23 - "Init"
Cohesion: 0.13
Nodes (20): Adaptadores de red real \u2014 capa de infraestructura (ARCHITECTURE.md…, is_host_alive(), probe(), Enum, Fallback TCP SYN para diferenciar FILTERED de UNREACHABLE. TECHNICAL_SPEC.md…, Resultado del fallback TCP SYN. OPEN: el connect completo -> host vivo.…, Ejecuta un TCP connect (SYN) contra (target_ip, port) con timeout. No lanza…, True si el host esta vivo (OPEN o REJECTED), False si no responde nada.… (+12 more)

### Community 24 - "Empty"
Cohesion: 0.11
Nodes (18): Construye un dataset vacío (para errores/empty state explícitos)., _cutoff(), _parse_ts(), datetime, Row, Implementación SQLite de ``SeriesDataSource`` (Fase 10). EP §3 (DI total):…, Serie de packet_loss_pct en el tiempo, agrupada por provider. Incluye SUCCESS y…, Comparativa Cloudflare vs Google: latencia avg_ms en el tiempo. DNs públicos… (+10 more)

### Community 25 - "Init"
Cohesion: 0.12
Nodes (12): Addr, Proc, ProcessEnumerator, ProcIterable, _PsutilEnumerator, Protocol, Devuelve un iterable de procesos del sistema. Envuelve…, Provee los hostnames configurados para `targets.riot_public`. El detector los… (+4 more)

### Community 26 - "Engine"
Cohesion: 0.12
Nodes (17): Protocol, Puerto RecommendationEngine — motor de recomendacion del dominio.…, Genera un Recommendation a partir de probes, baselines y thresholds. Cada…, RecommendationEngine, Una corrida completa de diagnóstico. TECHNICAL_SPEC.md §1: agrega todos los…, Entidades y value objects del dominio de GND. Contratos de datos definidos en…, Veredicto del motor de recomendación. TECHNICAL_SPEC.md §1 y §5.…, Recommendation (+9 more)

### Community 27 - "Charts"
Cohesion: 0.13
Nodes (25): _close_figures_after_test(), _make_dataset(), _normalize_color(), _parse_color(), fixture, Tests de charts.py (Fase 10) — render puro sobre fig/ax. EP §4: usa backend…, El axes del chart tiene fondo _BG (consistencia con ui/main_window.py)., Packet loss se grafica con fill_between para visualizar área. (+17 more)

### Community 28 - "Frame"
Cohesion: 0.12
Nodes (15): Frame, _chart_specs(), ChartsSection, Any, Figure, Misc, Inyecta la fuente de series (DI). Llamar antes de ``refresh``., Vuelve a consultar la DB y re-renderiza los 5 gráficos. Llamar desde el main… (+7 more)

### Community 29 - "Axes"
Cohesion: 0.18
Nodes (21): Axes, ChartsSection — pestaña "Charts" con los 5 gráficos del PRD §10 (Fase 10).…, all_renderers(), _finalize(), Figure, Funciones puras de renderización matplotlib (Fase 10). ARCHITECTURE.md §3 para…, Render 2: packet loss % en el tiempo, multi-series por provider. Línea con área…, Render 3: comparativa Cloudflare vs Google (2 series). Misma estructura que… (+13 more)

### Community 30 - "Init"
Cohesion: 0.11
Nodes (14): _hop_to_dict(), Any, Connection, Persiste DiagnosticRun completo en SQLite. Unica responsabilidad: guardar…, Args: db_factory: provee ``sqlite3.Connection`` por call. En un hilo worker (UI…, SqliteDiagnosticsRepository, DatabaseConnectionFactory, Protocol (+6 more)

### Community 31 - "Fakeseriesdatasource"
Cohesion: 0.12
Nodes (10): FakeSeriesDataSource, Implementación in-memory de ``SeriesDataSource``. Por defecto devuelve datos…, ChartDataSet, Datos listos para renderizar en un gráfico. ``title``: título del gráfico…, True si no hay puntos (la UI debe mostrar empty state)., Devuelve los grupos únicos preservando el orden de aparición., Protocol, Puertos de la capa de visualización (Fase 10). ARCHITECTURE.md §3:… (+2 more)

### Community 32 - "Historicalbaseline"
Cohesion: 0.12
Nodes (16): HistoricalBaseline, TestHistoricalBaseline, Tests de HistoricalBaseline., test_historical_baseline_valido(), test_period_days_invalido_falla(), test_stddev_cero_con_un_solo_sample_ok(), test_stddev_no_cero_con_un_solo_sample_falla(), test_valores_negativos_falla() (+8 more)

### Community 33 - "282"
Cohesion: 0.11
Nodes (24): Regla 5: Riot game server >2x baseline (TECHNICAL_SPEC §5.5). El ejemplo…, _rule5_riot_server_worse_than_baseline(), _probe(), Crea un ProbeResult con stats o sin ellos segun outcome., Test central del PRD: baseline 61ms, actual 126ms → rule 5 dispara. "Tu ruta es…, Rule 5 usa riot_game_server cuando existe (no riot_public)., Rule 5 usa riot_public cuando no hay game server., Sin baseline historico → rule 5 no matchea. (+16 more)

### Community 34 - "Architecture"
Cohesion: 0.10
Nodes (23): Clean Architecture, Dependency Injection, Dependency Injection Pattern, Non-Negotiable Principles, Review Checklist, SOLID Principles Applied, Testing Strategy, Definition of Done per Phase (+15 more)

### Community 35 - "Set"
Cohesion: 0.09
Nodes (23): _full_set(), parametrize, Todos sanos → no match., Todos los probes OK → safe_to_play., Constraint 6: safe_to_play + packet loss critico → not_recommended_ranked., Constraint 7: jitter critico → maximo playable., INVARIANTE: ninguna combinacion produce safe_to_play si packet_loss >=…, Local malo, ISP OK → serious_issue, local. (+15 more)

### Community 36 - "Conftest"
Cohesion: 0.14
Nodes (15): load_fixture(), Configuracion global de pytest. Provee helpers de fixtures (no pytest fixtures…, Lee un fixture de output de `ping` por nombre (sin extension)., Tests unitarios de `network/ping_parser` usando fixtures grabadas.…, test_linux_all_timeout_sin_error_letter(), test_linux_host_unreachable_error_letter_u(), test_linux_net_unreachable_error_letter_g(), test_linux_partial_loss_parsea() (+7 more)

### Community 37 - "Main"
Cohesion: 0.10
Nodes (21): main(), evaluate_recommendation(), Evalua las 7 reglas y genera un Recommendation. Fase 1 (reglas 1-5): primera…, Sin probes → safe_to_play (no hay datos = no hay problema)., Constraint 6: packet loss critico en local → no safe_to_play., INVARIANTE: probe con loss critico en cualquier provider impide safe_to_play.…, Packet loss alto en google → constraint 6 baja veredicto., Toda Recommendation tiene explanation no vacío (EP §1.3). (+13 more)

### Community 38 - "Fakeconnectioninspector"
Cohesion: 0.17
Nodes (14): FakeConnectionInspector, ConnectionInspector que devuelve servidor activo pre-configurado., ConnectionInspector, Protocol, Detecta el servidor de partida activo escaneando conexiones UDP de procesos.…, AccessDenied, NoSuchProcess, Exception (+6 more)

### Community 39 - "Parser"
Cohesion: 0.14
Nodes (14): _extract_ip_hostname(), _parse_hop_line(), ParsedHop, ParsedTracert, Parser del output de `tracert` nativo (Windows, EN y ES). TECHNICAL_SPEC.md…, Intenta parsear una linea como hop de `tracert`. Devuelve None si la linea no…, Extrae IP y hostname de la parte final de la linea de hop. Formats posibles:…, Un hop individual parseado del output de `tracert`. Attributes: hop_number:… (+6 more)

### Community 40 - "Anomaly"
Cohesion: 0.16
Nodes (13): probe(), Smoke test del fix Fase 9 — reproduce bug reportado. Escenario: Google actual…, Fake in-memory PingRunner para tests sin red real., LatencyStats, Estadísticas de latencia de un sondeo. Invariante (TECHNICAL_SPEC.md §1,…, Tests de LatencyStats — invariantes., test_avg_mayor_max_falla(), test_jitter_negativo_falla() (+5 more)

### Community 41 - "Fix"
Cohesion: 0.16
Nodes (13): build_use_case_with_db(), main(), _probe(), Verificación E2E del fix Fase 9: baseline anomalies → Recommendation. Este…, Construye RunFullDiagnostics con una DB específica (no producción)., Adaptador de persistencia SQLite para GND. TECHNICAL_SPEC.md §3. Implementa…, ensure_schema(), Esquema SQLite y migraciones. TECHNICAL_SPEC.md §3. Implementa las tablas… (+5 more)

### Community 42 - "Baseline"
Cohesion: 0.14
Nodes (19): compute_baseline(), Connection, datetime, Computa el baseline historico de latencia para un provider. Solo usa probes con…, _conn(), Baseline calcula media y stddev correctamente., Un solo sample -> stddev = 0., Provider sin datos -> zeros. (+11 more)

### Community 43 - "Init"
Cohesion: 0.14
Nodes (9): Capa de orquestacion de diagnostico — ARCHITECTURE.md §2. No implementa reglas…, ActiveGameServerDetector, ConnectionInspector real via enumeracion de conexiones UDP de proceso.…, _FakeEnumerator, _FakeRiotPublicProvider, _RaisingEnumerator, ProcessEnumerator falso: lista de procesos prefabricada., Enumerator que simula psutil.process_iter fallando a nivel sistema. (+1 more)

### Community 44 - "24"
Cohesion: 0.13
Nodes (12): Ejecuta una sesion de monitoreo de ruta contra un target. Toma N muestras de…, RouteMonitor, datetime, Tests unitarios del orquestador ``monitoring.route_monitor.RouteMonitor``. Sin…, Cada toma el hop 2 tiene IP distinta. Agregacion por hop_number metrica…, DoD Fase 8: estadisticas agregadas por hop coherentes con las muestras…, Runner que devuelve resultados pre-configurados en secuencia. Cada llamada a…, RotatingTracerouteRunner (+4 more)

### Community 45 - "Bug"
Cohesion: 0.18
Nodes (12): Repro del bug SQLite threading (corregido por Regla de Oro 9.1, Fase 9). Simula…, Fake in-memory ConnectionInspector para tests sin psutil real., Información del servidor de partido activo detectado. TECHNICAL_SPEC.md §1 y…, Tests de ActiveGameServerInfo y HistoricalBaseline., make_probe(), make_recommendation(), make_traceroute(), Tests de DiagnosticRun. (+4 more)

### Community 46 - "Models"
Cohesion: 0.21
Nodes (4): _good_hop_stats(), Tests unitarios de modelos de dominio MonitoringSession / HopStats /…, test_hop_stats_frozen(), TestHopStatsInvariants

### Community 47 - "Text"
Cohesion: 0.26
Nodes (6): format_anomalies_text(), Genera un resumen textual determinista de anomalias por hop. REGLA FIJA…, _hs(), Fabrica HopStats validos para tests de format_anomalies_text., Cubre la regla fijada con Santiago (2026-07-25): nunca omitir perdida parcial…, TestFormatAnomaliesText

### Community 48 - "Anomalies"
Cohesion: 0.17
Nodes (16): _constraint8_internet_latency_anomalies(), _get_probe(), _is_degraded(), _is_healthy(), Regla 2: Todo malo — ISP (TECHNICAL_SPEC §5.2). Si Google, Cloudflare Y Quad9…, Regla 3: Solo Cloudflare degradado (TECHNICAL_SPEC §5.3). Si Google y Quad9 OK,…, Regla 4: Solo Riot degradado (TECHNICAL_SPEC §5.4). Si Internet general OK,…, Restriccion 8: anomalías de baseline en providers Internet (no Riot). Este es… (+8 more)

### Community 49 - "Runner"
Cohesion: 0.17
Nodes (9): Tests de RealTracerouteRunner con subprocess mockeado (Fase 7). Cubre las…, Runner que devuelve `output` como stdout de tracert., Casos exitosos (output parseable)., DoD explicito: fixture con +80ms sostenido en hop 7 -> index 6 (0-based)., Pico de un solo hop (hop 4 = 80ms, hop 5 baja a 9ms) -> culprit=None., Salto sostenido real (hop 6: 74ms -> hop 7: 75ms) -> index 5., Hop 5 no responde, salto hop 4 -> 6 detectado correctamente., _runner_with_output() (+1 more)

### Community 50 - "Jitter"
Cohesion: 0.14
Nodes (14): normalize_jitter(), normalize_local_stability(), normalize_packet_loss(), Estabilidad de ruta local (gateway): combina loss y jitter. 60% weight en…, Normaliza packet loss a 0-100. 0% = 100, >= PACKET_LOSS_CEILING_PCT = 0.…, Normaliza jitter a 0-100. 0ms = 100, >= JITTER_CEILING_MS = 0. Interpolacion…, test_normalize_jitter_ceiling(), test_normalize_jitter_zero() (+6 more)

### Community 51 - "Path"
Cohesion: 0.21
Nodes (9): Path, main(), Connection, Verificación E2E de Fase 10 — los 5 gráficos del PRD §10. USO: python…, Adaptador sqlite3.Connection → DatabaseConnectionFactory. El factory real abre…, Siembra 14 días de probes sintéticos (cada 6h) para 4 providers., _RowProxyFactory, _seed_db() (+1 more)

### Community 52 - "Anomaly"
Cohesion: 0.22
Nodes (12): is_anomaly(), Determina si una latencia es anomala segun la regla avg + k*stddev. Un valor se…, normalize_internet_health(), Salud de Internet general: promedio de los DNS publicos disponibles. Regla…, Tests de analysis/baseline.py y analysis/score.py — Fase 4. Dataset sintetico:…, test_is_anomaly_above_threshold(), test_is_anomaly_no_data(), test_is_anomaly_within_threshold() (+4 more)

### Community 53 - "97"
Cohesion: 0.15
Nodes (13): Regla 1: Gateway local inestable (TECHNICAL_SPEC §5.1). Si provider='local'…, _rule1_gateway_local(), GW con loss critico → serious_issue, local., GW con jitter critico → serious_issue, local., GW con loss.warning → not_recommended_ranked, local., GW con jitter warning → not_recommended_ranked, local., GW no existe → no match (no penaliza)., test_rule1_gw_healthy_no_match() (+5 more)

### Community 54 - "Probe"
Cohesion: 0.15
Nodes (13): _make_probe(), Todos los providers sanos -> score alto., Packet loss alto -> score baja significativamente (25% del total)., Riot game server con latencia degradada vs baseline -> score baja (35%)., Probes faltantes redistribuyen peso, no penalizan. Regla: un componente sin…, Test clave: mismo score si Quad9 responde perfecto vs si no responde.…, Si TODOS los DNS faltan, el peso de internet_health (15%) se redistribuye entre…, test_score_all_good() (+5 more)

### Community 55 - "Source"
Cohesion: 0.29
Nodes (7): _default_best_hours(), _default_latency(), _default_packet_loss(), Fake ``SeriesDataSource`` para tests de UI sin tocar DB (Fase 10). Siguiendo el…, Modelos inmutables de la capa de visualización (Fase 10). ARCHITECTURE.md §3:…, Un punto de una serie temporal: ``y`` en el instante ``x``. ``group`` permite…, SeriesPoint

### Community 56 - "En"
Cohesion: 0.18
Nodes (11): Windows Tracert All Timeout, Windows Tracert With Hostnames, Windows Tracert Sustained Latency Jump 80ms, Windows Tracert Sustained Latency Jump 80ms Spanish, Windows Tracert Unresponsive Hop, Windows Tracert Unresponsive Hop Spanish, Windows Tracert Single Hop Latency Spike, Windows Tracert Sustained Latency Increase (+3 more)

### Community 58 - "Exception"
Cohesion: 0.20
Nodes (8): Exception, OSError (tracert no existe, permisos) -> empty result, no crashea., Si target es hostname que no resuelve, devuelve empty result., Runner que lanza `exc` al ejecutar subprocess., Timeouts y subprocess fallos., Si tracert expira pero ya escribió algunos hops, devuelve partial., _runner_with_exception(), TestRealTracerouteRunnerTimeouts

### Community 59 - "126"
Cohesion: 0.20
Nodes (6): Casos borde y validaciones., Output vacio (tracert fallo silencioso) -> empty result., El target_ip original (hostname) NO se resuelve en el resultado. La IP resuelta…, Threshold custom via constructor afecta deteccion., Tolerancia custom para sostenibilidad., TestRealTracerouteRunnerEdgeCases

### Community 60 - "Integration"
Cohesion: 0.22
Nodes (9): integration, parametrize, RFC 5737 TEST-NET-3: 203.0.113.0/24 es no-rutable por definicion., Verifica el fallback TCP SYN en vivo: un host que bloquea ICMP pero expone TCP…, DoD Fase 2: diagnostico local + internet end-to-end sin crashear., test_diagnostico_completo_no_crashea(), test_fallback_tcp_syn_funciona_contra_host_icmp_bloqueado(), test_ping_ip_documentada_inalcanzable_no_crash() (+1 more)

### Community 61 - "Genuine"
Cohesion: 0.36
Nodes (7): _AllTimeoutProcess, Listener, main(), Verificacion del camino FILTERED genuine end-to-end. No mockea el ProcessRunner…, ProcessRunner que simula `ping` con 100% packet loss (Windows)., start_listener(), stop_listener()

### Community 62 - "Windows"
Cohesion: 0.33
Nodes (8): banner(), main(), print_anomalies(), print_session_summary(), Verificacion end-to-end de Fase 8 para correr en Windows real. DoD Fase 8…, Resumen determinista de anomalias por hop. REGLA FIJA (2026-07-25): cualquier…, Recomputa manualmente las estadisticas a partir de session.samples y las…, verify_coherence()

### Community 63 - "Datetime"
Cohesion: 0.22
Nodes (5): datetime, Ejecuta la corrida completa y devuelve el DiagnosticRun. Args: targets:…, Wrapper defensivo sobre ConnectionInspector. EP §1.2: cualquier fallo del…, Lanza todos los pings en paralelo con ThreadPoolExecutor. EP §1.2: un ping…, Lanza traceroutes en paralelo. Mismo patron que pings.

### Community 64 - "Evidence"
Cohesion: 0.40
Nodes (4): _AllTimeoutProcess, main(), Demo del DoD de Fase 2: fallback TCP SYN funcionando de verdad. Este script NO…, ProcessRunner que simula output de `ping` con 100% packet loss. Fuerza el…

### Community 65 - "Parser"
Cohesion: 0.40
Nodes (5): lineiters_no_blank(), parse(), Parser del output de `ping` nativo (Windows y Linux/macOS). TECHNICAL_SPEC.md…, Parsea el output completo de `ping` y devuelve un ParsedPing. Detecta…, Filtra lineas vacias (helper).

### Community 66 - "Probe"
Cohesion: 0.53
Nodes (6): _insert_probe(), _insert_run(), _populate_30day_dataset(), Connection, datetime, Poblacion de 30 dias de latencias normales + anomalia dia 31. Providers:…

### Community 67 - "Windows"
Cohesion: 0.60
Nodes (4): banner(), main(), probe_tcp(), Verificacion end-to-end de Fase 2 para correr en Windows real. Corre el…

### Community 68 - "Latency"
Cohesion: 0.40
Nodes (5): normalize_riot_latency(), Normaliza la latencia Riot vs baseline a 0-100. Formula: threshold =…, test_normalize_riot_latency_above_threshold(), test_normalize_riot_latency_no_baseline(), test_normalize_riot_latency_within_avg()

### Community 69 - "Processrunner"
Cohesion: 0.40
Nodes (3): ProcessRunner, Protocol, Contrato para ejecutar el binario `tracert`. Permite inyectar un mock en tests…

### Community 70 - "Connectivity"
Cohesion: 0.50
Nodes (4): 3-Layer Riot Connectivity Model, Risks and Assumptions, Game Server IP (active match), Riot Public IP (auth/patch)

### Community 71 - "Windows"
Cohesion: 0.67
Nodes (3): banner(), main(), Verificacion end-to-end de Fase 7 para correr en Windows real. Corre el…

### Community 72 - "Ipv4"
Cohesion: 0.50
Nodes (3): _looks_like_ipv4(), Resuelve `target` (hostname o IPv4) a una IPv4. - Si ya es IPv4 (regex simple),…, True si `target` parece una IPv4 valida (no hostname).

### Community 73 - "Processrunner"
Cohesion: 0.50
Nodes (3): ProcessRunner, Protocol, Contrato para ejecutar el binario `ping`. Permite inyectar un mock en tests sin…

### Community 75 - "Theme"
Cohesion: 0.50
Nodes (4): apply_dark_theme(), Aplica un tema dark a ttk via `ttk.Style`. tkinter no trae un dark theme oob,…, Style, Tk

### Community 76 - "Unreachable"
Cohesion: 0.67
Nodes (4): Windows Ping Host Unreachable, Windows Ping Partial Loss, Windows Ping Success, Windows Ping Success Spanish

### Community 77 - "Outcome"
Cohesion: 0.67
Nodes (3): DiagnosticOutcome (Success|Filtered|Unreachable|Timeout), Error Handling Matrix, Windows Ping General Failure Fixture

## Knowledge Gaps
- **33 isolated node(s):** `gnd`, `Target Python 3.12+`, `Target Windows 11`, `Riot Public IP (auth/patch)`, `Game Server IP (active match)` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ProbeResult` connect `99` to `Repository`, `Baseline`, `Errorcallback`, `Engine`, `Window`, `Repository`, `43`, `Connection`, `Engine`, `Init`, `282`, `Set`, `Main`, `Anomaly`, `Fix`, `Bug`, `Anomalies`, `Jitter`, `Anomaly`, `97`, `Probe`, `Datetime`, `Processrunner`?**
  _High betweenness centrality (0.162) - this node is a cross-community bridge._
- **Why does `TracerouteResult` connect `Runner` to `50`, `Repository`, `Baseline`, `Errorcallback`, `Monitoringsample`, `Faketracerouterunner`, `Repository`, `Window`, `Repository`, `Protocol`, `Basemodel`, `Ipv4`, `Connection`, `Engine`, `Init`, `24`, `Bug`, `Models`, `Session`, `Datetime`, `Processrunner`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `HistoricalBaseline` connect `Historicalbaseline` to `282`, `Baseline`, `Latency`, `Main`, `Errorcallback`, `Baseline`, `Anomalies`, `Anomaly`, `Connection`, `Probe`, `Init`, `Engine`, `Init`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `ProbeResult` (e.g. with `DiagnosticParams` and `DiagnosticTargets`) actually correct?**
  _`ProbeResult` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `TracerouteResult` (e.g. with `DiagnosticParams` and `DiagnosticTargets`) actually correct?**
  _`TracerouteResult` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `TracerouteHop` (e.g. with `SqliteDiagnosticsRepository` and `FakeTracerouteRunner`) actually correct?**
  _`TracerouteHop` has 35 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `HistoricalBaseline` (e.g. with `DiagnosticParams` and `DiagnosticTargets`) actually correct?**
  _`HistoricalBaseline` has 10 INFERRED edges - model-reasoned connections that need verification._