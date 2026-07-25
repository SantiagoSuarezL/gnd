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


class Probes(BaseModel):
    ping_count: int = 20
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


class Ui(BaseModel):
    dark_mode: bool = True


# ---------------------------------------------------------------------------
# Settings raiz
# ---------------------------------------------------------------------------


class GndSettings(BaseSettings):
    targets: Targets = Targets()
    probes: Probes = Probes()
    game_detection: GameDetection = GameDetection()
    thresholds: Thresholds = Thresholds()
    database: Database = Database()
    ui: Ui = Ui()

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

    def validate_now(self) -> None:
        """Fallo rapido: lanza ValidationError si algo esta mal."""
        _ = self.model_dump()


# Singleton de settings (cargado una vez al arrancar, usado globalmente).
_settings: GndSettings | None = None


def get_settings() -> GndSettings:
    global _settings
    if _settings is None:
        _settings = GndSettings.load()
    return _settings


def reload_settings(path: str | Path | None = None) -> GndSettings:
    global _settings
    _settings = GndSettings.load(path)
    return _settings
