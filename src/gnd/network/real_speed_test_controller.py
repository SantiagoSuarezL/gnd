"""Adapter real de SpeedTestController usando `ookla-speedtest` subprocess
(Fase 12b.5).

Invoca el binario `speedtest` del sistema (Ookla Speedtest CLI). Usa
`--format=json` para parsing robusto.

Siguiendo Regla de Oro 12b.2.1: import de `subprocess` y `shutil` DENTRO
de `__init__`. Si `speedtest` no está en PATH, el adapter se marca
`_available=False` y su método `run()` lanza `SpeedTestError` — el wiring
no crashea al arrancar por falta del binario (EP §1.2).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from gnd.domain.ports.speed_test_controller import SpeedTestError
from gnd.models.speed_test import SpeedTestResult
from gnd.network._subprocess_helpers import subprocess_kwargs

logger = logging.getLogger(__name__)


class RealSpeedTestController:
    """Implementación real de SpeedTestController via `ookla-speedtest`.

    - `speedtest` debe estar en PATH (instalado via Ookla Speedtest CLI).
    - Usa `--format=json` para parsing robusto.
    - Timeout configurable (default 120s — un speed test puede durar 30-90s).
    - Captura stderr+stdout; parseo tolerante a cambios menores de output.

    Regla de Oro 12b.2.1: import de subprocess/shutil DENTRO de __init__.
    Si speedtest no está en PATH, marcamos _available=False y run() lanza
    SpeedTestError. El wiring no crashea al arrancar (EP §1.2).
    """

    def __init__(
        self,
        *,
        speedtest_path: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self._speedtest_path = speedtest_path or shutil.which("speedtest")
        self._timeout_s = timeout_s

        self._available = self._speedtest_path is not None
        if not self._available:
            logger.warning(
                "speedtest (ookla-speedtest) no encontrado en PATH — "
                "RealSpeedTestController en modo degradado",
                extra={"event": "speed_test.skip", "reason": "speedtest_not_found"},
            )

    @property
    def available(self) -> bool:
        """True si speedtest está disponible en PATH."""
        return self._available

    def run(self) -> SpeedTestResult:
        """Ejecuta un speed test completo y devuelve las métricas.

        Lanza ``SpeedTestError`` si falla (timeout, binario no encontrado,
        parsing inválido).
        """
        if not self._available:
            raise SpeedTestError(
                "speedtest (ookla-speedtest) no encontrado en PATH. "
                "Instálalo desde https://www.speedtest.net/apps/cli"
            )

        try:
            output = self._run(["--format=json", "--accept-license", "--accept-gdpr"])
            return self._parse_result(output)
        except subprocess.TimeoutExpired as exc:
            logger.exception(
                "Speed test timeout",
                extra={
                    "event": "speed_test.error",
                    "stage": "run",
                    "timeout_s": self._timeout_s,
                },
            )
            raise SpeedTestError(
                f"Speed test timeout ({self._timeout_s}s)", original_error=exc
            ) from exc
        except subprocess.CalledProcessError as exc:
            logger.exception(
                "Speed test falló (subprocess)",
                extra={"event": "speed_test.error", "stage": "run"},
            )
            raise SpeedTestError(
                f"speedtest subprocess falló: {exc}", original_error=exc
            ) from exc
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.exception(
                "Error parseando salida de speedtest",
                extra={"event": "speed_test.error", "stage": "parse"},
            )
            raise SpeedTestError(
                f"Error parseando salida de speedtest: {exc}", original_error=exc
            ) from exc

    def _run(self, args: list[str]) -> str:
        """Ejecuta `speedtest <args>` y devuelve stdout como string."""
        cmd = [self._speedtest_path, *args]
        logger.debug(
            "Ejecutando speedtest: %s",
            cmd,
            extra={"event": "speed_test.cmd", "args": args},
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
            check=True,
            **subprocess_kwargs(),
        )
        stdout = result.stdout.strip()
        logger.debug(
            "speedtest stdout length: %d",
            len(stdout),
            extra={"event": "speed_test.stdout"},
        )
        if result.stderr:
            logger.debug(
                "speedtest stderr: %s",
                result.stderr.strip()[:500],
                extra={"event": "speed_test.stderr"},
            )
        return stdout

    def _parse_result(self, json_str: str) -> SpeedTestResult:
        """Parsea salida JSON de `speedtest --format=json`.

        Estructura típica (Ookla Speedtest CLI v1.x):
        {
            "type": "result",
            "timestamp": "...",
            "ping": {"latency": 15.0, "jitter": 2.0, "packet_loss": 0.0},
            "download": {"bandwidth": 12500000, "bytes": ..., "elapsed": ...},
            "upload": {"bandwidth": 6250000, "bytes": ..., "elapsed": ...},
            "isp": "Test ISP",
            "server": {"name": "Test Server", "country": "Country"},
            ...
        }

        Nota: `bandwidth` viene en bytes/s (no Mbps). Se convierte a Mbps
        multiplicando por 8 / 1_000_000.
        """
        data = json.loads(json_str)

        ping_data = data.get("ping", {})
        download_data = data.get("download", {})
        upload_data = data.get("upload", {})
        server_data = data.get("server", {})

        latency_ms = float(ping_data.get("latency", 0.0))
        jitter_ms = float(ping_data.get("jitter", 0.0))
        packet_loss_pct = float(ping_data.get("packet_loss", 0.0))

        # bandwidth está en bytes/s; convertir a Mbps (x8 / 1e6)
        download_bytes_per_s = float(download_data.get("bandwidth", 0.0))
        upload_bytes_per_s = float(upload_data.get("bandwidth", 0.0))
        download_mbps = round(download_bytes_per_s * 8 / 1_000_000, 2)
        upload_mbps = round(upload_bytes_per_s * 8 / 1_000_000, 2)

        return SpeedTestResult(
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
            download_mbps=download_mbps,
            upload_mbps=upload_mbps,
            packet_loss_pct=packet_loss_pct,
            server_name=str(server_data.get("name", "Unknown")),
            server_country=str(server_data.get("country", "Unknown")),
            isp=str(data.get("isp", "Unknown")),
        )
