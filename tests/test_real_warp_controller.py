"""Tests del RealWarpController (Fase 12b.4 + Post-Fase 13 / Regla 12b.4.2).

Mockea `subprocess.run` para capturar los args pasados a `warp-cli` sin
invocar el binario real. Cubre:

- Regresión bug flag `--output-format=json` inexistente en warp-cli
  2026.6.x (post-Fase 13): el adapter ahora usa `status --no-paginate`
  texto plano, no JSON. Bug pre-existente Fase 12b.4 que rompía
  `get_status()` silenciosamente (captura CalledProcessError y devuelve
  status degradado).
- Parseo de `warp-cli settings list` para extraer `mode` y
  `tunnel_protocol` (clave para restore fiel Regla 12b.4.2).
- `set_mode()` y `set_tunnel_protocol()` invocan los subcomandos correctos.
- Modo degradado cuando warp-cli no está en PATH (_available=False).
- WarpError propagado cuando subprocess falla en enable/disable/set_*.

NO usa red real ni warp-cli del sistema — todo vía monkeypatch de
`subprocess.run` y `shutil.which`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import pytest

from gnd.domain.ports.warp_controller import WarpError
from gnd.network.real_warp_controller import RealWarpController


@dataclass
class _FakeCompleted:
    """Stub de subprocess.CompletedProcess para los tests."""

    stdout: str
    stderr: str = ""
    returncode: int = 0


class _SubprocessSpy:
    """Captura las llamadas a subprocess.run y responde según un script.

    `responses` es una lista de (args_match_fn, _FakeCompleted). Cada call
    consume el siguiente match; si se agotan, se graba el call y devuelve
    un stdout vacío (defensivo). El test puede asertar sobre `calls`.
    """

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        # cmd[0] es el path a warp-cli; kwargs puede tener capture_output,
        # text, timeout, check. Solo nos importa cmd[1:] (los args).
        args = cmd[1:]
        self.calls.append(args)
        for i, (matcher, response) in enumerate(self._responses):
            if matcher(args):
                self._responses.pop(i)
                if isinstance(response, Exception):
                    raise response
                return response
        # default: stdout vacío
        return _FakeCompleted(stdout="")


def _match_status(args):
    return args[:2] == ["status", "--no-paginate"]


def _match_settings_list(args):
    return args[:3] == ["settings", "list", "--no-paginate"]


def _match_connect(args):
    return args == ["connect"]


def _match_disconnect(args):
    return args == ["disconnect"]


def _match_mode(args):
    return args[:1] == ["mode"] and len(args) == 2


def _match_tunnel_protocol_set(args):
    return args == ["tunnel", "protocol", "set", "WireGuard"] or args == [
        "tunnel",
        "protocol",
        "set",
        "MASQUE",
    ]


class TestRealWarpControllerStatusParse:
    def test_get_status_usa_status_no_paginate_no_json(self, monkeypatch):
        """Regresión: bug flag `--output-format=json` inexistente en CLI
        2026.6.x. El adapter debe pedir `status --no-paginate`, NO
        `status --output-format=json` (que rompia get_status en silencio)."""
        spy = _SubprocessSpy(
            [
                (
                    _match_status,
                    _FakeCompleted(stdout="Status update: Connected\nNetwork: healthy"),
                ),
                (
                    _match_settings_list,
                    _FakeCompleted(
                        stdout="(default) Mode: Warp\n(network policy) WARP tunnel protocol: WireGuard"
                    ),
                ),
            ]
        )
        monkeypatch.setattr(subprocess, "run", spy)
        # Fuerzo `available=True` con path inventado (shutil.which=False en
        # CI sin warp-cli, mockeado abajo).
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        status = ctrl.get_status()

        assert status.connected is True
        assert status.connection_status == "connected"
        # El primer call debe ser `status --no-paginate`, NO con json.
        assert spy.calls[0] == ["status", "--no-paginate"]
        # No debe haber ningún call con `--output-format=json` en toda la run.
        for call in spy.calls:
            assert (
                "--output-format=json" not in call
            ), f"bug regresión: adapter pasó flag inexistente en call {call}"

    def test_get_status_parsea_disconnected_texto_plano(self, monkeypatch):
        spy = _SubprocessSpy(
            [
                (_match_status, _FakeCompleted(stdout="Status update: Disconnected")),
                (_match_settings_list, _FakeCompleted(stdout="")),
            ]
        )
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        status = ctrl.get_status()
        assert status.connected is False
        assert status.connection_status == "disconnected"


class TestRealWarpControllerSettingsParse:
    def _make_ctrl_with_settings(self, settings_output, monkeypatch):
        spy = _SubprocessSpy(
            [
                (
                    _match_status,
                    _FakeCompleted(stdout="Status update: Connected"),
                ),
                (_match_settings_list, _FakeCompleted(stdout=settings_output)),
            ]
        )
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        return RealWarpController(), spy

    def test_parsea_mode_y_protocol_de_settings_list(self, monkeypatch):
        output = (
            "Merged configuration:\n"
            "(not set)       Compliance Environment: Normal\n"
            "(default)       Mode: Warp\n"
            "(network policy)        WARP tunnel protocol: WireGuard\n"
            "(not set)       MASQUE Protocol Settings:\n"
        )
        ctrl, _ = self._make_ctrl_with_settings(output, monkeypatch)
        status = ctrl.get_status()
        assert status.mode == "warp"
        assert status.tunnel_protocol == "WireGuard"

    def test_parsea_modo_masque_default(self, monkeypatch):
        output = (
            "(default)       Mode: Warp\n"
            "(network policy)        WARP tunnel protocol: MASQUE\n"
        )
        ctrl, _ = self._make_ctrl_with_settings(output, monkeypatch)
        status = ctrl.get_status()
        assert status.mode == "warp"
        assert status.tunnel_protocol == "MASQUE"

    def test_parsea_modo_proxy(self, monkeypatch):
        output = (
            "(override)      Mode: proxy\n"
            "(network policy)        WARP tunnel protocol: WireGuard\n"
        )
        ctrl, _ = self._make_ctrl_with_settings(output, monkeypatch)
        status = ctrl.get_status()
        assert status.mode == "proxy"

    def test_settings_list_falla_devuelve_none_fail_safe(self, monkeypatch):
        """Si `settings list` crashea (CalledProcessError), el adapter
        devuelve mode=None / protocol=None y el caller (use case) aplica
        fail-safe. NO se propaga la excepción."""
        spy = _SubprocessSpy(
            [
                (
                    _match_status,
                    _FakeCompleted(stdout="Status update: Connected"),
                ),
                (
                    _match_settings_list,
                    subprocess.CalledProcessError(
                        returncode=1, cmd=["warp-cli", "settings", "list"]
                    ),
                ),
            ]
        )
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        status = ctrl.get_status()
        assert status.connected is True  # status sí parseó
        assert status.mode is None  # pero settings falló → fail-safe signals
        assert status.tunnel_protocol is None

    def test_settings_list_formato_desconocido_devuelve_none(self, monkeypatch):
        """Si el formato de settings list cambia en futura versión y los
        regex no matchean, mode/protocol = None (fail-safe), no crashea."""
        output = (
            "Some new format v3\n"
            "GeneralMode: warp\n"  # cambió el label
            "TunnelProto: WireGuard\n"
        )
        ctrl, _ = self._make_ctrl_with_settings(output, monkeypatch)
        status = ctrl.get_status()
        assert status.mode is None
        assert status.tunnel_protocol is None


class TestRealWarpControllerSetModeAndProtocol:
    def test_set_mode_invoca_warp_cli_mode_arg(self, monkeypatch):
        spy = _SubprocessSpy([(_match_mode, _FakeCompleted(stdout=""))])
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        ctrl.set_mode("proxy")
        assert spy.calls == [["mode", "proxy"]]

    def test_set_tunnel_protocol_invoca_subcomando_set(self, monkeypatch):
        spy = _SubprocessSpy([(_match_tunnel_protocol_set, _FakeCompleted(stdout=""))])
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        ctrl.set_tunnel_protocol("WireGuard")
        assert spy.calls == [["tunnel", "protocol", "set", "WireGuard"]]

    def test_set_mode_propaga_warp_error_si_subprocess_falla(self, monkeypatch):
        spy = _SubprocessSpy(
            [
                (
                    _match_mode,
                    subprocess.CalledProcessError(
                        returncode=1, cmd=["warp-cli", "mode", "proxy"]
                    ),
                )
            ]
        )
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        with pytest.raises(WarpError):
            ctrl.set_mode("proxy")

    def test_set_tunnel_protocol_propaga_warp_error_si_falla(self, monkeypatch):
        spy = _SubprocessSpy(
            [
                (
                    _match_tunnel_protocol_set,
                    subprocess.CalledProcessError(
                        returncode=1,
                        cmd=["warp-cli", "tunnel", "protocol", "set", "WireGuard"],
                    ),
                )
            ]
        )
        monkeypatch.setattr(subprocess, "run", spy)
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: "/fake/warp-cli",
        )
        ctrl = RealWarpController()

        with pytest.raises(WarpError):
            ctrl.set_tunnel_protocol("WireGuard")


class TestRealWarpControllerUnavailable:
    def test_no_disponible_get_status_devuelve_error_no_lanza(self, monkeypatch):
        """Si warp-cli no está en PATH, _available=False. get_status devuelve
        WarpStatus degradado (no lanza). EP §1.2: wiring nunca crashea."""
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: None,
        )
        ctrl = RealWarpController()
        assert ctrl.available is False

        status = ctrl.get_status()
        assert status.connected is False
        assert status.registration_status == "error"
        assert status.connection_status == "error"

    def test_no_disponible_enable_devuelve_degradado_no_lanza(self, monkeypatch):
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: None,
        )
        ctrl = RealWarpController()
        status = ctrl.enable()
        assert status.connected is False

    def test_no_disponible_set_mode_es_no_op(self, monkeypatch):
        """Si warp-cli no existe, set_mode es no-op silencioso (no raise)."""
        monkeypatch.setattr(
            "gnd.network.real_warp_controller.shutil.which",
            lambda _: None,
        )
        ctrl = RealWarpController()
        # No debe lanzar (no-op con log skip).
        ctrl.set_mode("warp")
