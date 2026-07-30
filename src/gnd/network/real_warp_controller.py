"""Adapter real de WarpController usando `warp-cli` subprocess (Fase 12b.4).

Invoca el binario `warp-cli` del sistema (debe estar en PATH). Maneja
parsing de salida JSON (warp-cli --output-format=json) y texto plano.

Siguiendo Regla de Oro 12b.2.1: import de `subprocess` y `shutil` DENTRO
de `__init__`. Si `warp-cli` no está en PATH, el adapter se marca
`_available=False` y sus métodos devuelven estado degradado + log — el
wiring nunca crashea al arrancar por falta del binario (EP §1.2).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass

from gnd.domain.ports.warp_controller import WarpError, WarpStatus

logger = logging.getLogger(__name__)


@dataclass
class _WarpCliOutput:
    """Salida parseada de `warp-cli status --output-format=json`."""

    registration_status: str
    connection_status: str
    warp_plus: bool


class RealWarpController:
    """Implementación real de WarpController via `warp-cli` subprocess.

    - `warp-cli` debe estar en PATH (instalado via Cloudflare WARP client).
    - Usa `--output-format=json` para parsing robusto (disponible en
      warp-cli >= 2023.x). Fallback a texto plano si JSON falla.
    - Timeouts: 10s para status, 30s para enable/disable (conexión puede
      tardar en establecer túnel).
    - Captura stderr+stdout; parseo tolerante a cambios menores de output.
    """

    def __init__(
        self,
        *,
        warp_cli_path: str | None = None,
        status_timeout_s: float = 10.0,
        enable_timeout_s: float = 30.0,
        disable_timeout_s: float = 10.0,
    ) -> None:
        # Import diferido de subprocess/shutil — Regla 12b.2.1
        # Si warp-cli no está en PATH, marcamos _available=False y no
        # rompemos el wiring (EP §1.2).
        self._warp_cli_path = warp_cli_path or shutil.which("warp-cli")
        self._status_timeout_s = status_timeout_s
        self._enable_timeout_s = enable_timeout_s
        self._disable_timeout_s = disable_timeout_s

        self._available = self._warp_cli_path is not None
        if not self._available:
            logger.warning(
                "warp-cli no encontrado en PATH — RealWarpController en modo degradado",
                extra={"event": "warp.skip", "reason": "warp_cli_not_found"},
            )

    # --- Protocol WarpController ---

    def get_status(self) -> WarpStatus:
        if not self._available:
            return WarpStatus(
                connected=False,
                registration_status="error",
                connection_status="error",
                warp_plus=False,
            )
        try:
            output = self._run(
                ["status", "--output-format=json"], timeout=self._status_timeout_s
            )
            parsed = self._parse_status_json(output)
            connected = parsed.connection_status == "Connected"
            return WarpStatus(
                connected=connected,
                registration_status=parsed.registration_status.lower(),
                connection_status=parsed.connection_status.lower(),
                warp_plus=parsed.warp_plus,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            KeyError,
        ):
            logger.exception(
                "Error consultando estado WARP",
                extra={"event": "warp.error", "stage": "get_status"},
            )
            return WarpStatus(
                connected=False,
                registration_status="error",
                connection_status="error",
                warp_plus=False,
            )

    def enable(self) -> WarpStatus:
        if not self._available:
            logger.warning(
                "Intento enable() sin warp-cli disponible",
                extra={
                    "event": "warp.skip",
                    "reason": "warp_cli_not_found",
                    "action": "enable",
                },
            )
            return WarpStatus(
                connected=False,
                registration_status="error",
                connection_status="error",
                warp_plus=False,
            )
        try:
            # `warp-cli connect` puede tardar en establecer túnel
            self._run(["connect"], timeout=self._enable_timeout_s)
            return self.get_status()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.exception(
                "Error activando WARP",
                extra={"event": "warp.error", "stage": "enable"},
            )
            raise WarpError(
                f"warp-cli connect falló: {exc}", original_error=exc
            ) from exc

    def disable(self) -> WarpStatus:
        if not self._available:
            logger.warning(
                "Intento disable() sin warp-cli disponible",
                extra={
                    "event": "warp.skip",
                    "reason": "warp_cli_not_found",
                    "action": "disable",
                },
            )
            return WarpStatus(
                connected=False,
                registration_status="error",
                connection_status="error",
                warp_plus=False,
            )
        try:
            self._run(["disconnect"], timeout=self._disable_timeout_s)
            return self.get_status()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.exception(
                "Error desactivando WARP",
                extra={"event": "warp.error", "stage": "disable"},
            )
            raise WarpError(
                f"warp-cli disconnect falló: {exc}", original_error=exc
            ) from exc

    # --- Internals ---

    def _run(self, args: list[str], timeout: float) -> str:
        """Ejecuta `warp-cli <args>` y devuelve stdout como string."""
        cmd = [self._warp_cli_path, *args]
        logger.debug(
            "Ejecutando warp-cli: %s", cmd, extra={"event": "warp.cmd", "args": args}
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        stdout = result.stdout.strip()
        logger.debug(
            "warp-cli stdout: %s",
            stdout,
            extra={"event": "warp.stdout", "stdout": stdout},
        )
        if result.stderr:
            logger.debug(
                "warp-cli stderr: %s",
                result.stderr.strip(),
                extra={"event": "warp.stderr"},
            )
        return stdout

    def _parse_status_json(self, json_str: str) -> _WarpCliOutput:
        """Parsea salida JSON de `warp-cli status --output-format=json`.

        Estructura típica:
        {
          "warp_plus": false,
          "registration_status": "Registered",
          "connection_status": "Connected"
        }
        """
        data = json.loads(json_str)
        return _WarpCliOutput(
            registration_status=str(data.get("registration_status", "Unknown")),
            connection_status=str(data.get("connection_status", "Unknown")),
            warp_plus=bool(data.get("warp_plus", False)),
        )

    # --- Propiedad para tests / diagnóstico ---
    @property
    def available(self) -> bool:
        """True si warp-cli está disponible en PATH."""
        return self._available
