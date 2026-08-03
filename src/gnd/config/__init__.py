"""Settings de configuracion para GND, validados con Pydantic al arranque.

Ver TECHNICAL_SPEC.md §6 para detalle de campos y valores default.
Carga desde config.toml o variables de entorno. Fallo rapido si mal formado.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

try:
    from pydantic import BaseModel, Field
    from pydantic_settings import (
        BaseSettings,
        SettingsConfigDict,
        TomlConfigSettingsSource,
    )
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
    # Fase 13.2b: juego activo para el que se construye el
    # GameDiagnosticsModule. Default "league_of_legends" (backwards-compat
    # total con runs pre-13.2). El composition_root mapea este string a
    # la implementación concreta en diagnostics/games/. Si el usuario
    # quiere diagnosticar Valorant, setea "valorant" (Fase 13.3). Un valor
    # no reconocido crashea al arrancar (fail-fast en config estática, no
    # es runtime de red) — el mapping es exhaustivo en composition_root.
    active_game: str = "league_of_legends"


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


class Notifications(BaseModel):
    """Configuracion de notificaciones de escritorio (Fase 12b.2).

    PRD §7 could-have + IMPLEMENTATION_PLAN.md 12b.2: tras cada corrida, GND
    emite una notificacion nativa del OS (Windows toast / Linux Freedesktop /
    macOS NSUserNotification) con el veredicto + headline del run. La
    lib `plyer` (dependencia introducida en 12b.2) abstrae el backend
    multiplataforma.

    `enabled=False` por default (YAGNI en v1, Regla 9.5) — opt-in via
    `GND_NOTIFICATIONS__ENABLED=true` en config.toml o env. Sensible:
    en CI/headless no hay desktop, y no queremos toasts no solicitados
    en el primer arranque.

    `app_name`: nombre de la app mostrado por el OS en la notif (header
    toast en Windows 10+). Default "GND".

    `timeout_seconds`: cuanto tiempo (s) la toast permanece visible antes
    de auto-cerrar. Default 8 (suficiente para leer headline + score).

    `notify_only_on_issues=False`: si True, suprime las notificaciones
    para runs con verdict "safe_to_play" (verdict EXCELENTE segun
    nomenclatura del motor). Util si el usuario quiere ser notificado
    solo cuando algo mueve. El usuario decide.
    """

    enabled: bool = False
    app_name: str = "GND"
    timeout_seconds: int = 8
    notify_only_on_issues: bool = False


class Reports(BaseModel):
    """Configuracion de reportes periodicos automaticos (Fase 12b.3).

    PRD §7 nice-to-have + IMPLEMENTATION_PLAN.md 12b.3: el scheduler
    genera reportes Markdown agregando los `DiagnosticRun` persistidos
    del ultimo periodo (semanal o mensual), reusando el renderer de
    Export (Fase 12b.1) para los top-K runs destacados. El reporte se
    escribe a `reports_dir` sin intervencion del usuario.

    `enabled=False` por default (YAGNI en v1, Regla 9.5) — opt-in via
    `GND_REPORTS__ENABLED=true` en config.toml o env. Sensible: la
    feature consume un hilo daemon y escribe archivos en disco; no
    activarla sin consentimiento explicito del usuario.

    `period`: "weekly" o "monthly". String mapeado a `ReportPeriod` enum
    en `models/report_config.py` (el wiring traduce string -> enum).

    `top_runs`: cuantos runs con menor score se renderizan completos
    (con `render_run_to_markdown` de 12b.1) dentro del reporte. Default
    3. 0 = solo agregado + lista compacta (util para periodos largos).

    `reports_dir`: directorio donde se escriben los archivos. Default
    `%APPDATA%/GND/reports` (expandido en runtime por el writer).

    `notify_on_generated=True`: emitir toast del OS (reusa 12b.2) cuando
    un reporte se genera. Si el usuario prefiere no ver toasts por
    reportes (los archivos estan en disco), puede desactivarlo.

    `notify_only_on_clean_period=False`: si True, suprime la notif de
    reporte cuando TODOS los runs del periodo fueron `safe_to_play`
    (no hubo issues). Mutual con `notify_on_generated`: si este ultimo
    es False, este flag es ignorado. Mismo filtrado que 12b.2.2 pero
    aplicado sobre el agregado del periodo (no sobre un solo run).
    """

    enabled: bool = False
    period: str = "weekly"  # "weekly" | "monthly" (traducido a ReportPeriod)
    top_runs: int = 3
    reports_dir: str = "%APPDATA%/GND/reports"
    notify_on_generated: bool = True
    notify_only_on_clean_period: bool = False


class WarpComparison(BaseModel):
    """Configuracion de la comparacion con/sin Cloudflare WARP (Fase 12b.4).

    IMPLEMENTATION_PLAN.md 12b.4: ejecuta el diagnostico dos veces, una
    con WARP activado y otra con WARP desactivado, y compara los
    resultados para mostrar al usuario el impacto de WARP en su red.

    Requiere `warp-cli` instalado y en PATH (descargable de
    https://developers.cloudflare.com/warp/). Si no esta disponible, el
    boton de UI se deshabilita y el caso de uso devuelve un resultado
    con `warp_controller_available=False` (Regla 12b.2.1: import
    diferido, el wiring nunca crashea por falta del binario).

    `enabled=False` por default (YAGNI en v1, Regla 9.5) — opt-in via
    `GND_WARP_COMPARISON__ENABLED=true`. El usuario debe haber
    instalado warp-cli antes de habilitar esto.

    `restore_original_state=True`: si WARP estaba activo antes de la
    comparacion, se reactiva al terminar. Si False, WARP queda en el
    estado del segundo run (warp_on). Util para tests/debug.

    `timeout_seconds=30`: timeout para `warp-cli connect` (establecer
    tunel puede tardar). `warp-cli status` usa un timeout menor (10s)
    hardcoded en el adapter real.

    `pause_between_runs_seconds=2`: pequana pausa entre los dos runs
    para que la interfaz de red se estabilice tras un connect/disconnect.
    """

    enabled: bool = False
    restore_original_state: bool = True
    timeout_seconds: int = 30
    pause_between_runs_seconds: float = 2.0


class SpeedTest(BaseModel):
    """Configuracion de speed test bajo demanda (Fase 12b.5).

    PRD §7 could-have: ejecuta `ookla-speedtest` CLI bajo demanda y
    muestra los resultados de ancho de banda (download/upload), latencia,
    jitter y packet loss en una nueva pestaña UI.

    Requiere `ookla-speedtest` instalado y en PATH (descargable de
    https://www.speedtest.net/apps/cli). Si no esta disponible, el
    boton de UI se deshabilita y el caso de uso devuelve un resultado
    con `speed_test_controller_available=False` (Regla 12b.2.1: import
    diferido, el wiring nunca crashea por falta del binario).

    `enabled=False` por default (YAGNI en v1, Regla 9.5) — opt-in via
    `GND_SPEED_TEST__ENABLED=true`. El usuario debe haber instalado
    ookla-speedtest antes de habilitar esto.

    `timeout_seconds=120`: timeout para `speedtest --format=json`. Un
    speed test puede durar 30-90s; el timeout debe ser generoso para
    redes lentas. El adapter real captura `subprocess.TimeoutExpired`
    y lanza `SpeedTestError`.

    El speed test se ejecuta DESPUES del diagnostico (no durante) para
    no interferir con los probes (Regla de Oro 12b.5.1).
    """

    enabled: bool = False
    timeout_seconds: int = 120


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
    notifications: Notifications = Notifications()
    reports: Reports = Reports()
    warp_comparison: WarpComparison = WarpComparison()
    speed_test: SpeedTest = SpeedTest()

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GND_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # pydantic-settings v2 no carga TOML automaticamente: hay que añadir
        # explicitamente `TomlConfigSettingsSource`. El path del toml_file se
        # lee de `settings_cls.model_config['toml_file']` (seteado por
        # `load()` via subclass dinamica — ver `load()` abajo).
        # Orden de precedencia: init kwargs > .env > env vars > toml > secrets.
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> GndSettings:
        if path is None:
            # busca config.toml en el directorio de trabajo
            candidate = Path.cwd() / "config.toml"
            if candidate.exists():
                path = candidate
        if path is None:
            return cls()
        # pydantic-settings v2 rechaza `_toml_file=` como kwarg extra. La forma
        # idiomatica de pasar runtime el path del toml_file es crear una
        # subclass dinamica con el `model_config` pisado — `TomlConfigSettingsSource`
        # lee `model_config.get('toml_file')` al instanciarse.
        cfg = SettingsConfigDict(
            env_prefix="GND_",
            env_nested_delimiter="__",
            extra="ignore",
            toml_file=str(path),
        )
        Dyn = type("GndSettingsLoaded", (cls,), {"model_config": cfg})
        return Dyn()


# Singleton de settings (cargado una vez al arrancar, usado globalmente).
_settings: GndSettings | None = None


def get_settings() -> GndSettings:
    global _settings
    if _settings is None:
        _settings = GndSettings.load()
    return _settings
