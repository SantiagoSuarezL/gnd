---

## Regla de Oro 12b.4.1 [Comparación WARP: dos runs completos + restore estado original, sin extender caso de uso existente]

**Problema (Fase 12b.4):** La feature de comparación con/sin Cloudflare WARP requiere ejecutar el diagnóstico completo DOS veces (WARP off + WARP on) y comparar resultados. El caso de uso existente `RunFullDiagnostics` orquesta un solo run. ¿Extender ese caso de uso con flags, o crear uno nuevo?

**Decisión:** Nuevo caso de uso `WarpComparisonUseCase` que compone (no hereda) `RunFullDiagnostics` + `WarpController`. Flujo: 1) Guarda estado WARP original, 2) disable → run (warp_off), 3) enable → run (warp_on), 4) restore estado original, 5) computa deltas (warp_on - warp_off: positivo = mejor con WARP) y veredicto. El `WarpController` Protocol abstrae `warp-cli` subprocess; `RealWarpController` usa import diferido (Regla 12b.2.1). Config `WarpComparison(enabled=False, restore_original_state=True, timeout_seconds=30, pause_between_runs_seconds=2.0)` opt-in.

**Regla de Oro:** *Para features que orquestan MÚLTIPLES corridas de un caso de uso existente con estado mutado entre medio (WARP on/off, speed test antes/después), crear un NUEVO caso de uso que COMPONGA el existente + un controlador de estado (WarpController, SpeedTestController), NO extender el caso de uso original con flags condicionales. El nuevo caso de uso es dueño del lifecycle: save state → mutate → run → mutate → run → restore → compute deltas. Separación de responsabilidades: el caso de uso base (RunFullDiagnostics) sigue siendo "una corrida"; el comparador es "dos corridas + análisis".*

---

## Regla de Oro 12b.3.1 [Lectura de runs históricos: nuevo puerto + adapter, NO extender repo de escritura]

**Problema (Fase 12b.3):** Scheduler de reportes necesitaba leer `DiagnosticRun` completos en un rango de fechas para generar Markdown. Pero `SqliteDiagnosticsRepository` solo escribe (`save_run`) — su docstring desde Fase 3 lo advertía: *"No expone metodos de lectura — analysis/ (Fase 4) accede directamente a una conexion SQLite (pedida via la misma factory) para las queries historicas"*. ¿Extender el repo con métodos de lectura, o crear un nuevo puerto?

**Decisión:** Nuevo Protocol `RunHistoryReader` + adapter `SqliteRunHistoryReader`. Interface Segregation estricta: el repo de escritura sigue siendo solo escritura (una responsabilidad); el reader tiene un solo método (`get_runs_in_period(start, end) -> list[DiagnosticRun]`); tests del reader no mezclan con tests del writer. Reconstruye cada `DiagnosticRun` con sus dependencias (probes, traceroutes, AGS, DNS, iface) en una sola conn — 1 query bulk por tabla filtrada por `run_id IN (...)` (evita N+1).

**Regla de Oro:** *Para features de "leer datos persistidos para presentación externa" (export, reportes, sync), NO extender el repo de escritura con queries de lectura (mezcla responsabilidades + rompe SRP). Crear un nuevo Protocol + adapter segregado, con su propio Fake para tests. El reader pide conn nueva por call via la misma `DatabaseConnectionFactory` (Regla 9.1: nunca compartir conn cross-thread) pero NO cierra la conn (la factory es dueña del lifecycle — cerrar rompería tests con `FakeDatabaseConnectionFactory` sobre conn compartida). Cuando la lectura reconstruye modelos compuestos (DiagnosticRun con probes/traceroutes anidados), usar queries bulk filtradas por la lista de IDs en vez de N queries por run.*

---

## Regla de Oro 12b.3.2 [threading.Timer stdlib: rearme manual en `finally` para hacerlo periódico]

**Problema (Fase 12b.3):** `threading.Timer(interval, callback)` de stdlib dispara el callback UNA sola vez y termina — no es un `setInterval` como en JS. Si el callback debe ejecutarse periódicamente (scheduler de reportes), hay que rearma manualmente tras cada tick. Además, si el callback levanta una excepción no capturada, el hilo daemon "muere silenciosamente" (no se loguea, no se rearma, el scheduler queda zombie).

**Decisión:** El callback `_tick_once()` ejecuta su ciclo en try/except (captura toda `Exception` con `logger.exception` + `event="report.error"` y NO rearma dentro del except). El `finally` rearma `self._schedule_next_tick()` SI el scheduler sigue `_started=True` (que se setea en `start()` y se limpia en `stop()` con un `threading.Lock`). Resultado: el daemon nunca muere por un tick transitorio (DB corrupta, disco lleno, etc.) — próximo tick vuelve a intentar. Cancelación: `stop()` cancela el Timer pendiente vía `self._timer.cancel()` + `_started=False`; idempotente.

**Regla de Oro:** *Para schedulers periódicos con `threading.Timer` stdlib, recordar que es ONE-SHOT: rearme manual en `finally` del callback (no en `except` — capturar primero, reagendar siempre). Capturar TODA Exception en el callback y loguear via `event="<namespace>.error"` (EP §1.2 a nivel hilo daemon: el scheduler nunca se autodestruye por un tick transitorio). Lifecycle con `threading.Lock` + flag `_started` para que `start()`/`stop()` sean idempotentes y `stop()` corte el ciclo de rearme. Para tests, exponer un hook sincrónico (`tick_now()`) que ejecuta el callback sin rearma — permite verificar la lógica sin esperar tiempo real.*