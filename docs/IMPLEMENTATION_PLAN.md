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

- Comparación con/sin Cloudflare WARP.
- Speed test bajo demanda (nunca automático).
- Notificaciones de escritorio.
- Exportar a PDF/Markdown.
- Detección Wi-Fi vs Ethernet + intensidad de señal.
- Medición de tiempo de resolución DNS.
- Soporte IPv6.
- Reportes semanales/mensuales.

Cada una de estas se planifica como sub-fase independiente cuando se priorice, siguiendo el mismo formato (objetivo + DoD).

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
