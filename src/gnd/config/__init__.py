"""Settings de configuracion para GND, validados con Pydantic al arranque.

Ver TECHNICAL_SPEC.md §6 para detalle de campos y valores default.
Carga desde config.toml o variables de entorno. Fallo rapido si mal formado.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

try:
    from pydantic import BaseModel, Field
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    msg = "pydantic[pydantic-settings] >= 2.0 es requerido. pip install -e '.[dev]'"
    raise RuntimeError(msg) from None


# ---------------------------------------------------------------------------
# Sub-modelos
# ---------------------------------------------------------------------------


class Targets(BaseModel):
    google_dns: str = "8.8.8.8"
    cloudflare: str = "1.1.1.1"
    quad9: str = "9.9.9.9"
    riot_public: list[str] = Field(
        default_factory=lambda: [
            "auth.riotgames.com",
            "lol.secure.dyn.riotcdn.net",
        ],
        description=(
            "Hostnames/IPs de infraestructura publica de Riot. "
            "Riot rota su infra (Cloudflare/Akamai); usar hostnames "
            "en vez de IPs fijas. RealPingRunner resuelve DNS inline."
        ),
    )
    # Fase 12a.4: IPv6 opt-in. Si not None, se ejecutan probes v6
    # ademas de los v4. Default None = feature off (backwards compat).
    # Ejemplos: "2606:4700:4700::1111" (Cloudflare DNS IPv6),
    # "2001:4860:4860::8888" (Google DNS IPv6).
    google_dns_ipv6: str | None = None
    cloudflare_ipv6: str | None = None
    quad9_ipv6: str | None = None
    riot_public_ipv6: list[str] = Field(default_factory=list)


class Probes(BaseModel):
    ping_count: int = 8
    timeout_ms: int = 1000
    traceroute_max_hops: int = 30


class GameDetection(BaseModel):
    process_names: list[str] = Field(default_factory=lambda: ["League of Legends.exe"])
    lcu_process_names: list[str] = Field(default_factory=lambda: ["LeagueClientUx.exe"])
    poll_interval_seconds: int = 5


class Thresholds(BaseModel):
    packet_loss_warning_pct: float = 1.0
    packet_loss_critical_pct: float = 3.0
    jitter_warning_ms: float = 20.0
    jitter_critical_ms: float = 40.0
    baseline_deviation_factor: float = 2.0
    hop_jump_threshold_ms: float = 40.0


class Database(BaseModel):
    path: str = "%APPDATA%/GND/history.db"


class Logging(BaseModel):
    # Directorio de logs JSONL (Fase 11). %APPDATA% se expande en runtime
    # (ver gnd.logging.configurer._resolve_logs_dir). Un archivo por dia
    # con nombre `gnd_YYYYMMDD.jsonl`.
    logs_dir: str = "%APPDATA%/GND/logs"
    # Nivel del root logger (str pydantic lo valida contra ENUM implicito
    # por typing, aca usamos str para evitar import logging en este modulo
    # de settings — el caller traduce a int con getattr(logging, level)).
    level: str = "INFO"
    # Nivel del handler de consola (stderr). El archivo captura TODO el
    # nivel del root logger; la consola solo warnings+errores por defecto
    # para no saturear la terminal en uso interactivo.
    console_level: str = "WARNING"
    # Cantidad de archivos rotados a retener (Fase 12a.1). Default 30 dias.
    # El `TimedRotatingFileHandler` rota el JSONL a medianoche y purga los
    # mas viejos que `retention_days` en cada rotacion. Map directo al
    # `backupCount` del stdlib.
    retention_days: int = 30


class Dns(BaseModel):
    """Configuracion de la medicion de tiempo de resolucion DNS (Fase 12a.2).

    TECHNICAL_SPEC.md §8 (gap): medir DNS como metrica independiente del ping
    (que en algunos OS embebe la resolucion DNS en su primer sample si
    el objetivo es un hostname).

    `enabled=False` por default para respetar el principio YAGNI en v1
    (Regla 9.5): el probing del pipeline ya hace resolution DNS en
    RealPingRunner; la medicion separada solo aporta valor cuando se
    quiere debuggear un DNS lento separately. Opt-in via config.toml
    o env `GND_DNS__ENABLED=true`.

    `hosts`: lista de hostnames a resolver. Si vacia (default), la
    etapa usa `targets.riot_public` + el hostname del gateway (cuando
    aplique — IP del gateway no es hostname). Default sensato:
    riot_public (Riot rota hostname, util saber si DNS responde lento).

    `timeout_ms`: limite por host. Un host que excede se reporta como
    TIMEOUT y la corrida continua (EP §1.2).
    """

    enabled: bool = False
    hosts: list[str] = Field(
        default_factory=list,
        description=(
            "Hostnames a resolver para medir tiempo DNS. Si vacio, la "
            "etapa DNS usa targets.riot_public por defecto. Evitar IPs "
            "(no tiene sentido medir DNS sobre una IP literal)."
        ),
    )
    timeout_ms: int = 1000
    # Default: probar IPv4. Si true, tambien probe IPv6 (si el host resuelve).
    include_ipv6: bool = False


class Network(BaseModel):
    """Configuracion de la deteccion de interfaz de red (Fase 12a.3).

    PRD §7 should-have + TECHNICAL_SPEC §8 gap. Snapshot del tipo de
    interfaz activa (Wi-Fi / Ethernet / otros) + SSID + signal dBm cuando
    Wi-Fi. Informacion de contexto local — no entra al motor de
    recomendacion v1, solo se persiste para observabilidad.

    `inspect_interface=False` por default (YAGNI en v1, Regla 9.5) —
    el usuario opt-in via `GND_NETWORK__INSPECT_INTERFACE=true` en
    config.toml o env. Sensible: usuarios con interfaces raras (VPNs,
    bridges) pueden skip.

    `netsh_timeout_ms`: limite del subprocess `netsh wlan show interfaces`
    en Windows. Si el driver WLAN cuelga, no blocka la corrida (EP §1.2).
    """

    inspect_interface: bool = False
    netsh_timeout_ms: int = 3000


# ---------------------------------------------------------------------------
# Settings raiz
# ---------------------------------------------------------------------------


class GndSettings(BaseSettings):
    targets: Targets = Targets()
    probes: Probes = Probes()
    game_detection: GameDetection = GameDetection()
    thresholds: Thresholds = Thresholds()
    database: Database = Database()
    logging: Logging = Logging()
    dns: Dns = Dns()
    network: Network = Network()

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GND_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def load(cls, path: str | Path | None = None) -> GndSettings:
        if path:
            return cls(_env_file=path)
        # busca config.toml en el directorio de trabajo
        candidate = Path.cwd() / "config.toml"
        if candidate.exists():
            return cls(_env_file=str(candidate))
        return cls()


# Singleton de settings (cargado una vez al arrancar, usado globalmente).
_settings: GndSettings | None = None


def get_settings() -> GndSettings:
    global _settings
    if _settings is None:
        _settings = GndSettings.load()
    return _settings
