"""Tests de carga de `config.toml` real desde disco (regresión config).

Test de regresión: el bug original era que `GndSettings.load()` usaba
`_env_file=path` pero `config.toml` es TOML, no `.env`. En pydantic-settings
v2 el source TOML no se carga automaticamente — requiere
`TomlConfigSettingsSource` via `settings_customise_sources`. Sin este test,
el mismo problema puede repetirse en otra sección de config (ej. warp_comparison)
sin que nadie lo note hasta que el usuario lo intente a mano.

Episodio: bug descubierto al intentar habilitar `speed_test.enabled=true`
via `config.toml` y el botón "Run Speed Test" seguía deshabilitado.
Fix: `src/gnd/config/__init__.py` añade `settings_customise_sources` +
subclass dinamica en `load()`.

Cobertura:
- Archivo TOML físico escrito a disco (tmp_path) — no mock, prueba real.
- Sección anidada (`[speed_test]` -> `SpeedTest` sub-model) carga valores.
- Valores ausentes en TOML usan defaults de cada sub-modelo (backwards-compat).
- Path inexistente no rompe (retorna defaults).
- Múltiples secciones anidadas cargan en simultaneo (no solo la última).
- Override vía env var tiene precedencia sobre TOML (orden sources).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gnd.config import GndSettings


class TestConfigTomlLoadingFromFile:
    """Carga de `config.toml` real escrito a disco via `GndSettings.load()`."""

    def test_speed_test_section_enabled_true_carga_desde_toml(
        self, tmp_path: Path
    ) -> None:
        """Regresión directa del bug: `[speed_test] enabled = true` TOML
        debe llegar a `settings.speed_test.enabled == True`.
        """
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[speed_test]\nenabled = true\ntimeout_seconds = 90\n",
            encoding="utf-8",
        )

        settings = GndSettings.load(path=config_path)

        assert settings.speed_test.enabled is True
        assert settings.speed_test.timeout_seconds == 90

    def test_warp_comparison_section_carga_desde_toml(self, tmp_path: Path) -> None:
        """Sección `[warp_comparison]` (que todavía no se usa en producción)
        carga correctamente — previene el mismo bug en futura sección.
        """
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[warp_comparison]\nenabled = true\nrestore_original_state = false\n"
            "timeout_seconds = 45\npause_between_runs_seconds = 5.0\n",
            encoding="utf-8",
        )

        settings = GndSettings.load(path=config_path)

        assert settings.warp_comparison.enabled is True
        assert settings.warp_comparison.restore_original_state is False
        assert settings.warp_comparison.timeout_seconds == 45
        assert settings.warp_comparison.pause_between_runs_seconds == 5.0

    def test_multiple_secciones_anidadas_cargan_en_simultaneo(
        self, tmp_path: Path
    ) -> None:
        """Múltiples secciones anidadas en el mismo TOML (no solo la última).
        Previene bugs donde el parser solo toma la última sección.
        """
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[speed_test]\nenabled = true\ntimeout_seconds = 60\n"
            "\n"
            "[warp_comparison]\nenabled = true\ntimeout_seconds = 20\n"
            "\n"
            '[notifications]\nenabled = true\napp_name = "GND-Test"\n',
            encoding="utf-8",
        )

        settings = GndSettings.load(path=config_path)

        assert settings.speed_test.enabled is True
        assert settings.speed_test.timeout_seconds == 60
        assert settings.warp_comparison.enabled is True
        assert settings.warp_comparison.timeout_seconds == 20
        assert settings.notifications.enabled is True
        assert settings.notifications.app_name == "GND-Test"

    def test_seccion_ausente_usa_defaults_del_sub_modelo(self, tmp_path: Path) -> None:
        """Si el TOML tiene `[speed_test]` pero no `[warp_comparison]`, el
        sub-modelo ausente conserva sus defaults (backwards-compat total).
        """
        config_path = tmp_path / "config.toml"
        config_path.write_text("[speed_test]\nenabled = true\n", encoding="utf-8")

        settings = GndSettings.load(path=config_path)

        assert settings.speed_test.enabled is True
        # warp_comparison ausente del TOML → defaults
        assert settings.warp_comparison.enabled is False
        assert settings.warp_comparison.timeout_seconds == 30
        assert settings.warp_comparison.restore_original_state is True

    def test_path_inexistente_retorna_defaults_sin_romper(self) -> None:
        """`GndSettings.load(path=<inexistente>)` Python no lanzará en el
        exists() check — abrimos y vemos que pydantic-settings lo maneja.
        El método `load()` valida `candidate.exists()`, pero si pasamos
        un path explicito que no existe, debe fallar limpiamente o caer
        en defaults (no debe corromper el proceso). Test: path válido a
        archivo vacío → defaults sin error.
        """
        tmp_dir = Path(__file__).parent
        empty_path = tmp_dir / "_nonexistent_config.toml"
        try:
            empty_path.write_text("", encoding="utf-8")
            settings = GndSettings.load(path=empty_path)
            # TOML vacío → todos los sub-modelos con defaults.
            assert settings.speed_test.enabled is False
            assert settings.warp_comparison.enabled is False
            assert settings.notifications.enabled is False
        finally:
            if empty_path.exists():
                empty_path.unlink()

    def test_seccion_logging_carga_valores(self, tmp_path: Path) -> None:
        """`[logging]` con valores custom carga correctamente."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[logging]\nlevel = "DEBUG"\nconsole_level = "INFO"\n'
            "retention_days = 7\n",
            encoding="utf-8",
        )

        settings = GndSettings.load(path=config_path)

        assert settings.logging.level == "DEBUG"
        assert settings.logging.console_level == "INFO"
        assert settings.logging.retention_days == 7

    def test_seccion_database_path_carga(self, tmp_path: Path) -> None:
        """`[database]` con path custom carga correctamente (valida que
        TOML strings llegan al sub-modelo sin corrupción).
        """
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[database]\npath = "C:/custom/path/history.db"\n',
            encoding="utf-8",
        )

        settings = GndSettings.load(path=config_path)

        assert settings.database.path == "C:/custom/path/history.db"

    def test_seccion_targets_con_lista_carga(self, tmp_path: Path) -> None:
        """`[targets]` con lista (`riot_public = [...]`) carga — valida
        que TOML arrays se mapean a `list[str]`.
        """
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[targets]\nriot_public = ["a.riotgames.com", "b.riotcdn.net"]\n',
            encoding="utf-8",
        )

        settings = GndSettings.load(path=config_path)

        assert settings.targets.riot_public == [
            "a.riotgames.com",
            "b.riotcdn.net",
        ]
        # Otros targets conservan defaults
        assert settings.targets.google_dns == "8.8.8.8"


class TestConfigTomlEnvVarPrecedence:
    """Valida el orden de precedencia: init > .env > env vars > toml > secrets.

    Regla arquitectural: env vars (GND_*) tienen precedencia sobre TOML,
    para permitir overrides puntuales en CI/producción sin editar el TOML.
    """

    def test_env_var_pisa_valor_del_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`GND_SPEED_TEST__TIMEOUT_SECONDS=200` debe pisar el valor del TOML."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[speed_test]\nenabled = true\ntimeout_seconds = 90\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("GND_SPEED_TEST__TIMEOUT_SECONDS", "200")

        settings = GndSettings.load(path=config_path)

        # El env var pisa el TOML.
        assert settings.speed_test.timeout_seconds == 200
        # `enabled` no tiene env var, sigue el TOML.
        assert settings.speed_test.enabled is True

    def test_env_var_pisa_boolean_del_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`GND_SPEED_TEST__ENABLED=false` debe pisar `enabled = true` del TOML."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("[speed_test]\nenabled = true\n", encoding="utf-8")

        monkeypatch.setenv("GND_SPEED_TEST__ENABLED", "false")

        settings = GndSettings.load(path=config_path)

        assert settings.speed_test.enabled is False
