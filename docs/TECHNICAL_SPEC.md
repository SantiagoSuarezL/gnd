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

**Problema que resuelve:** la IP pública de Riot (ej. `104.160.136.3`) es infraestructura de login/patch, no la IP del servidor de la partida en curso. Esa IP se asigna dinámicamente por datacenter/matchmaking.

**Implementación:**

```python
import psutil

LOL_PROCESS_NAMES = {"League of Legends.exe"}
LCU_PROCESS_NAMES = {"LeagueClientUx.exe", "LeagueClient.exe"}

def detect_active_game_server(
    process_names: set[str] = LOL_PROCESS_NAMES,
) -> ActiveGameServerInfo | None:
    for proc in psutil.process_iter(["name", "pid"]):
        if proc.info["name"] not in process_names:
            continue
        try:
            connections = proc.net_connections(kind="udp")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        for conn in connections:
            if conn.raddr and not _is_private_ip(conn.raddr.ip):
                return ActiveGameServerInfo(
                    ip=conn.raddr.ip,
                    port=conn.raddr.port,
                    protocol="udp",
                    detected_via="process_connection_scan",
                    process_name=proc.info["name"],
                )
    return None
```

**Notas críticas de implementación:**

- El tráfico de partida de LoL es **mayormente UDP**, no TCP. El LCU (lobby/champ select) sí es TCP/HTTPS. Un detector que solo mire TCP nunca va a encontrar la IP de partida.
- `proc.net_connections()` puede requerir privilegios elevados en Windows para ver conexiones de otros procesos con detalle completo — documentar y degradar con mensaje claro si `AccessDenied`.
- Confirmación cruzada opcional: consultar `https://127.0.0.1:2999/liveclientdata/activeplayer` (Live Client Data API, expuesta solo durante partida activa, certificado self-signed → requiere `verify=False` o el cert de Riot) para confirmar que hay partida en curso y así decidir *cuándo* disparar el escaneo de conexiones, en vez de hacer polling constante.
- El puerto/token de la LCU API (para lobby, no in-game) se lee del archivo `lockfile` en el directorio de instalación de League — útil para un futuro `analysis/` que quiera saber en qué fase del juego está el usuario (queue, champ select, in-game) sin adivinar.
- Filtrar siempre IPs privadas (RFC1918) y loopback del resultado — son conexiones locales del propio cliente, no del servidor de partida.

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
riot_public = ["104.160.136.3"]     # configurable, no hardcoded

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
