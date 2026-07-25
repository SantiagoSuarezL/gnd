# TECHNICAL SPEC — Game Network Diagnostics (GND)

**Versión:** 1.0
**Documentos relacionados:** `PRD.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`

---

## 1. Modelos de dominio (contratos de datos)

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

class ProbeOutcomeKind(Enum):
    SUCCESS = auto()
    FILTERED = auto()      # ICMP bloqueado u host que ignora ping deliberadamente
    UNREACHABLE = auto()   # error de red real (no ruta, RST, etc.)
    TIMEOUT = auto()

@dataclass(frozen=True)
class LatencyStats:
    avg_ms: float
    min_ms: float
    max_ms: float
    jitter_ms: float
    packet_loss_pct: float
    samples: int

@dataclass(frozen=True)
class ProbeResult:
    target_name: str          # "gateway", "google_dns", "riot_game_server", etc.
    target_ip: str
    provider: str              # clave estable para histórico: "local" | "google" | "cloudflare" | "quad9" | "riot_public" | "riot_game_server"
    outcome: ProbeOutcomeKind
    stats: LatencyStats | None  # None si outcome != SUCCESS
    timestamp: datetime

@dataclass(frozen=True)
class TracerouteHop:
    hop_number: int
    ip: str | None            # None si el hop no respondió (no implica error)
    hostname: str | None
    rtt_ms: float | None
    responded: bool

@dataclass(frozen=True)
class TracerouteResult:
    target_provider: str
    hops: list[TracerouteHop]
    culprit_hop_index: int | None  # hop donde se detecta el salto de latencia anómalo

@dataclass(frozen=True)
class ActiveGameServerInfo:
    ip: str
    port: int
    protocol: str              # "udp" | "tcp"
    detected_via: str          # "process_connection_scan" | "live_client_api_confirmed"
    process_name: str

@dataclass(frozen=True)
class HistoricalBaseline:
    provider: str
    period_days: int
    avg_ms: float
    stddev_ms: float
    sample_count: int

@dataclass(frozen=True)
class Recommendation:
    verdict: str                # "safe_to_play" | "playable" | "not_recommended_ranked" | "serious_issue"
    headline: str                # ej. "🔴 Alta latencia detectada"
    explanation: list[str]       # líneas de razonamiento explicable, nunca "caja negra"
    responsible_component: str   # "local" | "isp" | "international_transit" | "riot" | "cloudflare" | "google" | "unknown"
    score: int                   # 0-100

@dataclass(frozen=True)
class DiagnosticRun:
    run_id: str
    started_at: datetime
    finished_at: datetime
    probes: list[ProbeResult]
    traceroutes: list[TracerouteResult]
    active_game_server: ActiveGameServerInfo | None
    recommendation: Recommendation
```

**Regla de diseño:** `outcome != SUCCESS` nunca debe interpretarse aguas abajo como "peor caso". `FILTERED` explícitamente se excluye del cálculo de baseline y del score — no penaliza, simplemente no aporta dato.

---

## 2. Protocolos de red (adapters de infraestructura)

### 2.1 Ping / latencia local e Internet

- Ejecutar vía subprocess sobre el `ping` nativo de Windows (evita requerir privilegios raw-socket) **o** implementación propia con `icmplib` si se necesita mayor control sobre timeout/TTL por muestra.
- Parsear: avg/min/max/jitter (calculado como desviación estándar de RTTs individuales, no solo max-min) y packet loss real (paquetes perdidos / enviados).
- **Manejo de ICMP bloqueado (obligatorio, PRD §Error Handling):** si 100% de los paquetes a un host se pierden PERO el traceroute logra llegar a hops posteriores al target (indicando que el host está vivo pero descarta ICMP), marcar como `FILTERED`, no `UNREACHABLE`. Heurística: comparar con un fallback TCP SYN a un puerto conocido (443) si ICMP falla — si el TCP handshake responde, el host está vivo y solo bloquea ICMP.

### 2.2 Detección de servidor de partida activo (Riot) — componente distintivo del proyecto

**Problema que resuelve:** la IP pública de Riot (ej. `auth.riotgames.com` → `104.16.119.50` via Cloudflare) es infraestructura de login/patch, no la IP del servidor de la partida en curso. Esa IP se asigna dinámicamente por datacenter/matchmaking.

**Arquitectura para v1 (decisión documentada 2026-07-24):**

El enfoque original (enumear conexiones UDP del proceso vía `psutil`) **no funciona en Windows** para obtener la IP remota del game server. Confirmado empiricamente:

- `psutil.Process.net_connections(kind="udp")` devuelve `raddr=()` (tupla vacía) para sockets UDP que SÍ están `connect()`ados a un peer remoto — el kernel de Windows no expone la remote address en la tabla UDP global que psutil/`netstat`/`GetExtendedUdpTable`/`Get-NetUDPEndpoint` leen.
- `LiveClientDataApi` (`https://127.0.0.1:2999/liveclientdata/`) **sí confirma** que hay partida activa y expone datos del jugador, pero **no expone la IP del game server**.
- Por tanto, **no hay forma en espacio de usuario en Windows de obtener la IP del game server sin packet capture (Npcap/WinPcap)**.

**Arquitectura v1 (proxy):**

El detector primario para v1 usa dos señales combinadas:
1. `LiveClientApi.is_game_active()` → `True` = hay partida activa (confirmado funcionando).
2. `targets.riot_public` (hostnames: `auth.riotgames.com`, `lol.secure.dyn.riotcdn.net`) → proxy de salud de la conexión a infraestructura Riot. Si hay partida activa + riot_public saludable → conexión a Riot OK. Si hay partida activa + riot_public degradado → problema específico de Riot.

El código `ActiveGameServerDetector` (psutil) **se mantiene en el repo** (`src/gnd/diagnostics/riot/active_game_server_detector.py`) con la limitación documentada, como base para v1.1 (Npcap) y porque puede funcionar en otros SO si algún día se porta.

**Implementación actual (v1):**

```python
# En detection/riot/active_game_server_detector.py
# NOTA: En Windows, raddr de UDP conectados NO expone remote IP.
# Este detector NUNCA encontrara la IP del game server real en Windows.
# Sirve como placeholder para v1.1 (Npcap) y funciona en otros SO si se porta en el futuro.
```

**Notas críticas de implementación:**

- El tráfico de partida de LoL es **mayormente UDP**, no TCP. El LCU (lobby/champ select) sí es TCP/HTTPS. Un detector que solo mire TCP nunca va a encontrar la IP de partida.
- `proc.net_connections()` puede requerir privilegios elevados en Windows para ver conexiones de otros procesos con detalle completo — documentar y degradar con mensaje claro si `AccessDenied`.
- Confirmación cruzada opcional: consultar `https://127.0.0.1:2999/liveclientdata/activeplayer` (Live Client Data API, expuesta solo durante partida activa, certificado self-signed → requiere `verify=False` o el cert de Riot) para confirmar que hay partida en curso y así decidir *cuándo* disparar el escaneo de conexiones, en vez de hacer polling constante.
- El puerto/token de la LCU API (para lobby, no in-game) se lee del archivo `lockfile` en el directorio de instalación de League — útil para un futuro `analysis/` que quiera saber en qué fase del juego está el usuario (queue, champ select, in-game) sin adivinar.
- Filtrar siempre IPs privadas (RFC1918) y loopback del resultado — son conexiones locales del propio cliente, no del servidor de partida.

**Limitación conocida v1:** En Windows, la IP exacta del servidor de partida **no es obtenible** sin Npcap. El sistema usa `riot_public` como proxy — el motor de recomendación (Fase 5) ya maneja correctamente el caso `active_game_server=None` usando `riot_public` como única señal Riot (Regla 4, Regla 5).

### 2.3 Traceroute

- Windows: wrapper sobre `tracert -d -w <timeout>` vía `subprocess`, parseado a `TracerouteResult`.
- **Detección del hop culpable:** recorrer hops en orden; marcar `culprit_hop_index` en el primer hop donde `rtt_ms` sube más de `threshold_hop_jump_ms` (configurable, default 40ms) respecto al hop anterior, Y ese incremento se mantiene en los hops subsiguientes (para descartar picos de un solo hop que no afectan el resto de la ruta — patrón típico de routers que despriorizan ICMP pero no afectan tráfico real).
- Hops que no responden (`responded=False`) no se tratan como error — es comportamiento común de red, se muestran como "sin datos" en ese tramo.

### 2.4 Monitoreo continuo de ruta (estilo WinMTR)

- Ejecutar N muestras a intervalos regulares (configurable) contra el mismo target, acumulando estadísticas por hop (no solo destino final).
- Persistir cada corrida como una sesión de monitoreo vinculada a un `run_id`, permitiendo reconstruir el comportamiento de la ruta completa en el tiempo, no solo el destino.

---

## 3. Base de datos (SQLite)

```sql
CREATE TABLE diagnostic_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    recommendation_verdict TEXT NOT NULL,
    recommendation_score INTEGER NOT NULL,
    responsible_component TEXT NOT NULL
);

CREATE TABLE probe_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    provider TEXT NOT NULL,           -- 'local' | 'google' | 'cloudflare' | 'quad9' | 'riot_public' | 'riot_game_server'
    target_ip TEXT NOT NULL,
    outcome TEXT NOT NULL,            -- SUCCESS | FILTERED | UNREACHABLE | TIMEOUT
    avg_ms REAL,
    min_ms REAL,
    max_ms REAL,
    jitter_ms REAL,
    packet_loss_pct REAL,
    timestamp TEXT NOT NULL
);

CREATE TABLE traceroute_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    target_provider TEXT NOT NULL,
    culprit_hop_index INTEGER,
    hops_json TEXT NOT NULL           -- serialización de list[TracerouteHop]
);

CREATE TABLE active_game_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id),
    ip TEXT NOT NULL,
    port INTEGER NOT NULL,
    detected_via TEXT NOT NULL
);

CREATE INDEX idx_probe_provider_time ON probe_results(provider, timestamp);
```

**Regla clave:** `riot_public` y `riot_game_server` son providers **distintos** en la tabla. El cálculo de baseline histórico (`analysis/baseline.py`) siempre agrupa `WHERE provider = ?` — nunca se debe promediar la IP fija de infraestructura junto con las IPs dinámicas de partidas reales, o el baseline queda contaminado.

---

## 4. Análisis histórico y Network Score

### 4.1 Cálculo de baseline

```python
def compute_baseline(provider: str, period_days: int = 30) -> HistoricalBaseline:
    samples = repository.get_successful_latencies(provider, period_days)
    return HistoricalBaseline(
        provider=provider,
        period_days=period_days,
        avg_ms=mean(samples),
        stddev_ms=stdev(samples) if len(samples) > 1 else 0.0,
        sample_count=len(samples),
    )
```

**Importante (gap identificado en el spec original):** la comparación no debe ser un simple "actual vs promedio" — debe usar desviación estándar. Un valor solo se marca como anómalo si excede `avg + (k * stddev)`, con `k` configurable (default 2.0). Esto evita falsos positivos por fluctuación normal de red.

### 4.2 Network Score (0–100)

Score ponderado, no una fórmula mágica única:

| Componente | Peso |
|---|---|
| Latencia Riot game server vs baseline | 35% |
| Packet loss (cualquier provider) | 25% |
| Jitter | 20% |
| Salud de Internet general (Google/Cloudflare/Quad9) | 15% |
| Estabilidad de ruta local (gateway) | 5% |

Cada componente se normaliza a 0–100 antes de ponderar. Documentar la fórmula exacta de normalización en el código, no solo en este doc (ver `ENGINEERING_PRINCIPLES.md` — todo número debe ser trazable a una razón).

---

## 5. Motor de recomendación (el corazón del proyecto)

Reglas ordenadas por prioridad de diagnóstico (evaluar de arriba hacia abajo, la primera que matchea determina `responsible_component`):

1. **Gateway local inestable** (packet_loss > threshold O jitter > threshold en provider="local") → `responsible_component = "local"`, verdict = `not_recommended_ranked` o peor.
2. **Todo malo** (Google, Cloudflare Y Quad9 todos degradados) → `responsible_component = "isp"`.
3. **Google y Quad9 OK, Cloudflare degradado** → `responsible_component = "cloudflare"`.
4. **Internet general OK, solo Riot (público o game server) degradado** → `responsible_component = "riot"`.
5. **Riot game server específicamente >2x baseline** (usando el dato de partida real, no el público) → mensaje específico: "tu ruta actual a la partida es Xms más lenta que tu promedio histórico".
6. **Packet loss alto en cualquier provider relevante** → verdict nunca puede ser `safe_to_play`, independiente de la latencia.
7. **Jitter alto sostenido** → verdict máximo `playable`, nunca `safe_to_play` para ranked.

Cada regla debe generar una o más líneas en `explanation: list[str]` — el usuario siempre ve el razonamiento, nunca solo el veredicto (requisito explícito del PRD/proyecto original: "never guess, always explain why").

**Thresholds default (configurables, ver `config/`):**

```toml
[thresholds]
packet_loss_warning_pct = 1.0
packet_loss_critical_pct = 3.0
jitter_warning_ms = 20.0
jitter_critical_ms = 40.0
baseline_deviation_factor = 2.0     # k en avg + k*stddev
hop_jump_threshold_ms = 40.0
```

---

## 6. Configuración

```toml
[targets]
google_dns = "8.8.8.8"
cloudflare = "1.1.1.1"
quad9 = "9.9.9.9"
riot_public = ["auth.riotgames.com", "lol.secure.dyn.riotcdn.net"]  # hostnames, no IPs fijas

[probes]
ping_count = 20
timeout_ms = 1000
traceroute_max_hops = 30

[game_detection]
process_names = ["League of Legends.exe"]
lcu_process_names = ["LeagueClientUx.exe"]
poll_interval_seconds = 5

[database]
path = "%APPDATA%/GND/history.db"

[ui]
dark_mode = true
```

**Nota sobre infraestructura de Riot:** Riot rota su infraestructura pública entre CDNs (Cloudflare, Akamai). Las IPs `104.160.x.x` citadas en versiones anteriores de este documento son legacy y probablemente inalcanzables desde ISP de LATAM. Por eso `riot_public` se configura con **hostnames** en vez de IPs fijas; `RealPingRunner` resuelve DNS inline (ver `real_ping_runner.py:_resolve_target`) antes de pinguear. Si se necesitan IPs concretas (ej. para debugging), se pueden reemplazar temporalmente en `config.toml`, pero el default debe mantenerse como hostnames para adaptarse a cambios de CDN sin tocar código.

Validado con Pydantic `BaseSettings` al arranque; falla rápido y con mensaje claro si el archivo está mal formado (nunca falla silenciosamente).

---

## 7. Manejo de errores — matriz completa

| Situación | Outcome de dominio | Efecto en UI/recomendación |
|---|---|---|
| Host bloquea ICMP pero responde TCP 443 | `FILTERED` | Excluido del score, nota informativa: "este host no responde a ping (normal)" |
| Host no responde a nada | `UNREACHABLE` | Cuenta como degradación, entra al motor de reglas |
| Timeout de sondeo | `TIMEOUT` | Se reintenta 1 vez antes de marcar como tal |
| `psutil.AccessDenied` al escanear proceso | Excepción capturada → resultado `active_game_server=None` con log de advertencia | UI muestra "ejecutar como administrador para detección de partida" |
| Proceso de LoL no está corriendo | `active_game_server=None`, sin error | Se usa solo `riot_public` para el diagnóstico Riot |
| DB corrupta o inaccesible | Excepción de infraestructura capturada en el borde de la capa Application | UI muestra error claro, la corrida en memoria no se pierde (se puede reintentar guardar) |

---

## 8. Gaps identificados respecto al documento original (para que Opus los priorice)

- Diferenciación explícita `riot_public` vs `riot_game_server` en todo el pipeline (antes no existía).
- Uso de UDP (no solo TCP) para detección de conexión de partida.
- Baseline estadístico con desviación estándar, no promedio simple.
- Fallback TCP SYN para diferenciar "ICMP bloqueado" de "host caído" con mayor confianza.
- Medición de tiempo de resolución DNS como métrica independiente (no estaba en el doc original).
- Detección de tipo de interfaz (Wi-Fi vs Ethernet) e intensidad de señal — afecta directamente el diagnóstico de "problema local".
- Soporte IPv6 en traceroute y ping (no mencionado originalmente, relevante si el ISP asigna IPv6).

---

## 9. Roadmap v1.1 — NpcapGameServerDetector (mejora futura, no bloqueante)

**Contexto:** En v1, la IP exacta del servidor de partida **no es obtenible** en Windows sin packet capture. El enfoque v1 usa `LiveClientApi.is_game_active()` + `riot_public` como proxy de salud de conexión a Riot.

**Propuesta v1.1:** `NpcapGameServerDetector` — detector opcional que usa Npcap/WinPcap para capturar paquetes UDP del PID de LoL y extraer la `dst IP` del game server real.

```python
# Futuro: src/gnd/diagnostics/riot/npcap_game_server_detector.py
class NpcapGameServerDetector:
    """Detector real de IP del game server via packet capture.

    Requiere:
    - Npcap instalado (driver kernel) + admin para instalar.
    - Ejecucion elevated (capturar paquetes de otro proceso).
    - Hardware: Ryzen 5 7520U + 8GB RAM — evaluado y pospuesto por:
      * Overhead de captura de paquetes en CPU/memoria limitadas.
      * Complejidad de filtrar solo paquetes UDP del PID de LoL.
      * Trade-off: valor incremental vs. costo operativo en v1.

    No bloqueante para v1 — implementable cuando el usuario priorice
    la IP exacta del game server sobre el proxy riot_public.
    """
    def detect(self, process_name: str = "League of Legends.exe") -> ActiveGameServerInfo | None: ...
```

**Trade-off documentado (2026-07-24):** Se evaluó Npcap y se pospuso a v1.1 por:
- Rendimiento en hardware limitado (Ryzen 5 7520U, 8GB RAM): captura de paquetes UDP a tasa de partida (~50-100pps) consume ~15-20% CPU + memoria adicional.
- Complejidad operacional: requiere instalar driver Npcap + ejecutar app como admin siempre.
- Valor incremental v1: `riot_public` proxy ya permite Regla 4/5 del motor de recomendación funcionar correctamente (motor de Fase 5 probado con `active_game_server=None`).

**Criterio de activación v1.1:** Usuario solicita explícitamente IP exacta del game server + acepta overhead Npcap + admin.