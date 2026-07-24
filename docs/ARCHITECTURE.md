# ARCHITECTURE — Game Network Diagnostics (GND)

**Versión:** 1.0
**Documentos relacionados:** `PRD.md`, `TECHNICAL_SPEC.md`, `ENGINEERING_PRINCIPLES.md`

---

## 1. Principios arquitectónicos

- **Clean Architecture**: las dependencias apuntan hacia adentro. El dominio (modelos, reglas de negocio) no conoce nada de SQLite, UI, ni sockets.
- **Separación estricta de capas**: red, análisis, recomendación, persistencia, UI, visualización y configuración son módulos independientes conectados por interfaces (Protocols de Python), nunca por imports directos cruzados.
- **Dependency Injection explícita**: nada se instancia "a mano" dentro de la lógica de negocio; todo se inyecta por constructor.
- **Determinismo primero, IA después**: el motor de recomendación v1 es 100% basado en reglas explicables. La futura integración LLM (sección 18 del spec original) es una capa de *explicación en lenguaje natural* sobre el resultado ya determinado — nunca decide por sí sola.
- **Nunca crashear por condiciones de red**: toda falla de red es un resultado de dominio (`Unreachable`, `Filtered`, `Timeout`), nunca una excepción no controlada que suba hasta la UI.

## 2. Vista de capas (Clean Architecture)

```
┌───────────────────────────────────────────────────────────┐
│                         UI Layer                          │
│        (presentación, orquestación de acciones)           │
└───────────────────────┬───────────────────────────────────┘
                        │ depende de
┌───────────────────────▼─────────────────────────────────────┐
│                  Application / Use Cases                    │
│   RunFullDiagnostics, AnalyzeHistoricalBaseline,            │
│   DetectActiveGameServer, GenerateRecommendation            │
└───────────────────────┬─────────────────────────────────────┘
                        │ depende de
┌───────────────────────▼───────────────────────────────────────┐
│                     Domain (core)                             │
│   Entidades: DiagnosticResult, TracerouteHop, Baseline,       │
│   Recommendation, NetworkScore                                │
│   Puertos (Protocols): PingRunner, TracerouteRunner,          │
│   ConnectionInspector, DiagnosticsRepository                  │
└───────────────────────┬───────────────────────────────────────┘
                        │ implementado por
┌───────────────────────▼──────────────────────────────────────┐
│                  Infrastructure (adapters)                   │
│   network/ (ICMP, UDP, traceroute real vía subprocess/raw    │
│   sockets), database/ (SQLite repo), config/ (settings),     │
│   visualization/ (matplotlib/plotly render)                  │
└──────────────────────────────────────────────────────────────┘
```

El **dominio no importa `psutil`, `sqlite3`, ni `subprocess` directamente** — solo define los Protocols (interfaces) que la infraestructura implementa. Esto permite testear el motor de recomendación con mocks sin tocar la red real.

## 3. Módulos y responsabilidades

| Módulo | Responsabilidad | No debe hacer |
|---|---|---|
| `network/` | Ejecutar ICMP ping, UDP probes, traceroute crudo. Devuelve DTOs de infraestructura. | No interpreta resultados, no decide nada. |
| `diagnostics/` | Orquesta las pruebas (local, internet, Riot, traceroute, monitoreo continuo) y arma `DiagnosticResult`. | No accede a la DB directamente. |
| `analysis/` | Calcula baseline histórico, detecta desviaciones, calcula el Network Score 0–100. | No conoce la UI ni el formato de presentación. |
| `recommendations/` | Motor de reglas que traduce análisis → veredicto humano. | No ejecuta pings ni traceroutes. |
| `database/` | Persistencia SQLite, repositorios. | No contiene lógica de negocio. |
| `visualization/` | Generación de gráficos a partir de datos ya calculados. | No calcula ni interpreta datos. |
| `config/` | Carga y valida configuración (targets, thresholds, timeouts). | No contiene lógica de diagnóstico. |
| `ui/` | Presentación, click del usuario, orquestación visual. | No contiene reglas de negocio ni acceso directo a red/DB. |
| `models/` | Entidades y value objects compartidos (Pydantic/dataclasses). | Sin dependencias a infraestructura. |

## 4. El modelo de 3 capas de conectividad Riot (crítico para este proyecto)

Este es el elemento arquitectónico distintivo de GND frente a un ping tool genérico:

```
┌───────────────────────────┐
│   Riot Client (launcher)  │  → infraestructura de auth/patch, IP pública fija
└────────────┬──────────────┘
             │
┌────────────▼──────────────┐
│  League Client (LCU)      │  → lobby, cola, matchmaking. TCP/HTTPS.
│  API local: 127.0.0.1:*   │     (puerto + token en "lockfile")
└────────────┬──────────────┘
             │ al entrar a partida, matchmaking asigna
┌────────────▼───────────────┐
│  Game Server (la partida)  │  → IP DINÁMICA por partida/datacenter.
│  Tráfico principalmente UDP│     Esta es la IP que determina el ping real.
└────────────────────────────┘
```

**Implicación de diseño:** el módulo `diagnostics/riot/` debe tener DOS sub-componentes desacoplados:

1. `RiotPublicEndpointProbe` — pinguea la(s) IP(s) públicas configurables (ej. `104.160.136.3`) como proxy de "salud general de Riot".
2. `ActiveGameServerDetector` — un puerto (`Protocol`) con implementación por defecto vía enumeración de conexiones de proceso (`psutil`, filtrando UDP del proceso `League of Legends.exe`), y opcionalmente reforzado con la **Live Client Data API** (`https://127.0.0.1:2999/liveclientdata/`) para confirmar que hay partida activa y sincronizar el momento del sondeo.

Estos dos componentes alimentan registros **distintos** en la base histórica (`provider = "riot_public"` vs `provider = "riot_game_server"`), para que la comparación histórica compare peras con peras.

## 5. Flujo de datos — ejecución completa (un clic)

```
UI: click "Run Diagnostics"
   → Application.RunFullDiagnostics use case
       1. diagnostics/local        → gateway ping
       2. diagnostics/internet     → Google, Cloudflare, Quad9
       3. diagnostics/riot         → público + detección de game server (si hay partida activa)
       4. diagnostics/traceroute   → para cada target relevante
       5. analysis/baseline        → compara contra histórico (por provider)
       6. recommendations/engine   → aplica reglas → Recommendation
       7. database/repository      → persiste el run completo
       8. ui/                      → renderiza estado + recomendación + gráficos
```

Cada paso debe poder fallar de forma aislada (ej. Quad9 no responde) sin abortar el pipeline completo — el resultado parcial sigue siendo válido y se marca explícitamente como parcial.

## 6. Decisiones tecnológicas

| Decisión | Elección | Justificación |
|---|---|---|
| Lenguaje | Python 3.12+ | Requisito del proyecto; usar `typing` moderno (PEP 695) |
| Validación de datos | Pydantic v2 | Contratos de datos claros entre capas |
| Persistencia | SQLite (stdlib `sqlite3` o `sqlmodel`) | Suficiente para uso local, sin servidor |
| Concurrencia de sondeos | `asyncio` | Permite paralelizar pings a múltiples targets sin bloquear la UI |
| Enumeración de conexiones | `psutil` | Multiplataforma, mantenido, expone conexiones por proceso |
| Traceroute | Wrapper sobre `tracert` nativo de Windows vía `subprocess`, parseado a modelo propio | Evita reimplementar ICMP TTL manualmente en v1; ver TECHNICAL_SPEC.md para plan de reemplazo por implementación propia si se requiere más control |
| UI | `customtkinter` o `PySide6/Qt` (decisión en TECHNICAL_SPEC.md) | Dark mode nativo, sin dependencias pesadas de navegador |
| Visualización | `matplotlib` (embebido) o `plotly` | Gráficos de series de tiempo simples |
| Testing | `pytest` + `pytest-asyncio` | Estándar del proyecto |
| Calidad de código | `ruff` + `black` | Requisito explícito del PRD original |

## 7. Extensibilidad multi-juego

Cada juego implementa una interfaz `GameDiagnosticsModule`:

```
Protocol GameDiagnosticsModule:
    def public_endpoints() -> list[Target]
    def detect_active_server() -> ActiveServerResult | None
    def process_names() -> list[str]
```

`diagnostics/games/league_of_legends.py` es la primera implementación. Agregar Valorant/CS2/etc. en el futuro no debe requerir tocar `analysis/`, `recommendations/`, ni `database/`.

## 8. Manejo de errores (visión arquitectónica — detalle en TECHNICAL_SPEC.md)

Todo resultado de sondeo de red es un **tipo de resultado explícito**, nunca una excepción propagada:

```
DiagnosticOutcome = Success(metrics) | Filtered(reason) | Unreachable(reason) | Timeout()
```

Un host que bloquea ICMP produce `Filtered("icmp_blocked")`, que el motor de recomendación interpreta como "sin datos de latencia para este hop", no como "conexión caída". Esto elimina los falsos positivos exigidos en el PRD.
