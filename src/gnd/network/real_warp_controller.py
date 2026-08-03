"""Adapter real de WarpController usando `warp-cli` subprocess (Fase 12b.4).

Invoca el binario `warp-cli` del sistema (debe estar en PATH). Parseo de
texto plano: `warp-cli status` da `Status update: <Connected|Disconnected|...>`
y `warp-cli settings list` expone `Mode: <warp|proxy|doh|...>` y
`WARP tunnel protocol: <MASQUE|WireGuard>`. No usar `--output-format=json`
(flag inexistente en warp-cli 2026.6.x — bug pre-existente Fase 12b.4,
fixeado post-Fase 13: Regla 12b.4.2).

Modo y protocolo: el usuario puede prender WARP en un modo específico
(ej. "UDP" en la app = `tunnel_protocol=WireGuard`). Para que el
restore_original_state sea fiel, el adapter detecta el protocolo actual
antes de apagar y lo replica vía `warp-cli tunnel protocol set <M>`.
Si el parseo falla (None), el caller (use case) aplica el fail-safe:
NO restaura a "connect ciego", deja WARP como quedó y avisa por log.

Siguiendo Regla de Oro 12b.2.1: import de `subprocess` y `shutil` (para
`which`) DENTRO de `__init__`. Si `warp-cli` no está en PATH, el adapter
se marca `_available=False` y sus métodos devuelven estado degradado + log
— el wiring nunca crashea al arrancar por falta del binario (EP §1.2).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass

from gnd.domain.ports.warp_controller import WarpError, WarpStatus
from gnd.network._subprocess_helpers import subprocess_kwargs

logger = logging.getLogger(__name__)

# Regex para parseo de `warp-cli settings list` (multiline UTF-8).
# Línea ejemplo: `(default)       Mode: Warp` → captura "Warp" (case-insensitive
# pero normalizamos a lowercase para comparación).
_MODE_RE = re.compile(r"^\s*\([^)]*\)\s*Mode:\s*(\w+)", re.MULTILINE)
# Línea ejemplo: `(network policy)        WARP tunnel protocol: MASQUE`
_PROTO_RE = re.compile(
    r"^\s*\([^)]*\)\s*WARP tunnel protocol:\s*(MASQUE|WireGuard)",
    re.MULTILINE,
)
# Regex para parseo de `warp-cli status` texto plano.
# `Status update: Connected` → captura "Connected".
_STATUS_RE = re.compile(r"Status update:\s*(\w+)")


@dataclass
class _WarpSettings:
    """Salida parseada de `warp-cli settings list` (modo + protocolo)."""

    mode: str | None
    tunnel_protocol: str | None


class RealWarpController:
    """Implementación real de WarpController via `warp-cli` subprocess.

    - `warp-cli` debe estar en PATH (instalado via Cloudflare WARP client).
    - Parseo texto plano de `status` y `settings list` (sin JSON, más
      robusto contra cambios menores de output entre versiones del CLI).
    - Timeouts: 10s para status, 30s para connect (túnel puede tardar),
      10s para disconnect, 10s para settings y set-mode/protocol.
    - Captura stderr+stdout; parseo tolerante a cambios menores de output.
    """

    def __init__(
        self,
        *,
        warp_cli_path: str | None = None,
        status_timeout_s: float = 10.0,
        enable_timeout_s: float = 30.0,
        disable_timeout_s: float = 10.0,
        settings_timeout_s: float = 10.0,
        set_setting_timeout_s: float = 10.0,
    ) -> None:
        # Import diferido de subprocess/shutil — Regla 12b.2.1
        self._warp_cli_path = warp_cli_path or shutil.which("warp-cli")
        self._status_timeout_s = status_timeout_s
        self._enable_timeout_s = enable_timeout_s
        self._disable_timeout_s = disable_timeout_s
        self._settings_timeout_s = settings_timeout_s
        self._set_setting_timeout_s = set_setting_timeout_s

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
            status_out = self._run(
                ["status", "--no-paginate"], timeout=self._status_timeout_s
            )
            connection_status = self._parse_status_text(status_out)
            connected = connection_status == "connected"

            # Modo + protocolo: parseo separado de `settings list`. Si falla
            # (None, None), el caller aplica fail-safe (Regla 12b.4.2).
            settings = self._read_settings()

            return WarpStatus(
                connected=connected,
                registration_status="registered",  # no expuesto por CLI texto; asumido
                connection_status=connection_status,
                warp_plus=False,  # no detectable en settings list texto plano
                mode=settings.mode,
                tunnel_protocol=settings.tunnel_protocol,
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

    # --- Modo y protocolo del túnel (para restore fiel — Regla 12b.4.2) ---

    def set_mode(self, mode: str) -> None:
        """Setea el modo general del cliente (warp/proxy/doh/...).

        Ejecuta `warp-cli mode <mode>`. Lanza WarpError si falla.
        """
        if not self._available:
            logger.warning(
                "Intento set_mode(%s) sin warp-cli disponible",
                mode,
                extra={"event": "warp.skip", "reason": "warp_cli_not_found"},
            )
            return
        try:
            self._run(["mode", mode], timeout=self._set_setting_timeout_s)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.exception(
                "Error seteando modo WARP a %s",
                mode,
                extra={"event": "warp.error", "stage": "set_mode", "mode": mode},
            )
            raise WarpError(
                f"warp-cli mode {mode} falló: {exc}", original_error=exc
            ) from exc

    def set_tunnel_protocol(self, protocol: str) -> None:
        """Setea el protocolo del túnel (MASQUE | WireGuard).

        Ejecuta `warp-cli tunnel protocol set <protocol>`. Lanza WarpError
        si falla. WireGuard = lo que el usuario llama "modo UDP"; MASQUE =
        HTTP/3 (default en builds >=2024).
        """
        if not self._available:
            logger.warning(
                "Intento set_tunnel_protocol(%s) sin warp-cli disponible",
                protocol,
                extra={"event": "warp.skip", "reason": "warp_cli_not_found"},
            )
            return
        try:
            self._run(
                ["tunnel", "protocol", "set", protocol],
                timeout=self._set_setting_timeout_s,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.exception(
                "Error seteando protocolo WARP a %s",
                protocol,
                extra={
                    "event": "warp.error",
                    "stage": "set_tunnel_protocol",
                    "protocol": protocol,
                },
            )
            raise WarpError(
                f"warp-cli tunnel protocol set {protocol} falló: {exc}",
                original_error=exc,
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
            **subprocess_kwargs(),
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

    def _parse_status_text(self, status_out: str) -> str:
        """Parsea `warp-cli status` texto plano: `Status update: <X>`.

        Devuelve lowercase: 'connected' | 'disconnected' | 'connecting' |
        'error' (si no matchea, asume 'error' conservadoramente).
        """
        match = _STATUS_RE.search(status_out)
        if match:
            return match.group(1).lower()
        logger.warning(
            "No se pudo parsear status output: %r",
            status_out,
            extra={"event": "warp.parse_fail", "stage": "status", "output": status_out},
        )
        return "error"

    def _read_settings(self) -> _WarpSettings:
        """Lee `warp-cli settings list` y parsea mode + tunnel_protocol.

        Devuelve `_WarpSettings(mode=None, tunnel_protocol=None)` si el parseo
        falla — el caller decide fail-safe (Regla 12b.4.2).
        """
        try:
            settings_out = self._run(
                ["settings", "list", "--no-paginate"],
                timeout=self._settings_timeout_s,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.warning(
                "No se pudo leer warp-cli settings: %s",
                exc,
                extra={"event": "warp.parse_fail", "stage": "settings_read"},
            )
            return _WarpSettings(mode=None, tunnel_protocol=None)

        mode_match = _MODE_RE.search(settings_out)
        proto_match = _PROTO_RE.search(settings_out)
        mode = mode_match.group(1).lower() if mode_match else None
        protocol = proto_match.group(1) if proto_match else None  # case preservado

        if mode is None or protocol is None:
            logger.warning(
                "Parseo settings incompleto: mode=%s protocol=%s",
                mode,
                protocol,
                extra={
                    "event": "warp.parse_fail",
                    "stage": "settings_parse",
                    "mode": mode,
                    "tunnel_protocol": protocol,
                },
            )
        return _WarpSettings(mode=mode, tunnel_protocol=protocol)

    # --- Propiedad para tests / diagnóstico ---
    @property
    def available(self) -> bool:
        """True si warp-cli está disponible en PATH."""
        return self._available
