"""Tests del helper `subprocess_kwargs` (post-Fase 14.0a, launcher VBS).

Verifica:
- En Windows, devuelve `creationflags=0x08000000` (CREATE_NO_WINDOW).
- En POSIX, devuelve `{}` (no rompe cross-platform).
- Si el caller pasa `extra`, mergea con prioridad para `extra`.
- Aplicar el helper a un subprocess real pasa el flag al `Popen`
  subyacente (test monkeypatch sobre `subprocess.run`).
"""

from __future__ import annotations

import platform

import pytest

from gnd.network._subprocess_helpers import subprocess_kwargs


class TestSubprocessKwargsHelper:
    def test_windows_includes_create_no_window(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Windows"
        )
        kw = subprocess_kwargs()
        assert kw == {"creationflags": 0x08000000}

    def test_posix_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Linux"
        )
        kw = subprocess_kwargs()
        assert kw == {}

    def test_darwin_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Darwin"
        )
        kw = subprocess_kwargs()
        assert kw == {}

    def test_extra_overrides_helper_on_windows(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Windows"
        )
        kw = subprocess_kwargs(extra={"creationflags": 0, "shell": False})
        assert kw["creationflags"] == 0
        assert kw["shell"] is False

    def test_extra_does_not_add_flags_on_posix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Linux"
        )
        kw = subprocess_kwargs(extra={"timeout": 5})
        assert kw == {"timeout": 5}


class TestHelperAppliedToRealSubprocess:
    """Verifica que al pasar **subprocess_kwargs() el flag llega al
    subprocess. Mockeamos ``subprocess.run`` para capturar kwargs."""

    def test_popen_receives_create_no_window_on_windows(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                stdout = ""
                stderr = ""
                returncode = 0

            return _R()

        monkeypatch.setattr("gnd.network.real_ping_runner.subprocess.run", fake_run)
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Windows"
        )

        # Llamamos al _DefaultProcessRunner del RealPingRunner para que
        # use el helper end-to-end.
        from gnd.network.real_ping_runner import _DefaultProcessRunner

        runner = _DefaultProcessRunner()
        runner(["ping", "-n", "1", "127.0.0.1"], timeout_ms=500)

        if platform.system() == "Windows":
            assert captured.get("creationflags") == 0x08000000
        else:
            # En el host de CI no-Windows la plataforma importada arriba
            # manda — el helper no devuelve creationflags, asi que la
            # key ni debe estar.
            assert "creationflags" not in captured

    def test_popen_receives_create_no_window_in_traceroute(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                stdout = ""
                stderr = ""
                returncode = 0

            return _R()

        monkeypatch.setattr(
            "gnd.network.real_traceroute_runner.subprocess.run", fake_run
        )
        monkeypatch.setattr(
            "gnd.network._subprocess_helpers.platform.system", lambda: "Windows"
        )

        from gnd.network.real_traceroute_runner import _DefaultProcessRunner

        runner = _DefaultProcessRunner()
        runner(["tracert", "-d", "127.0.0.1"], total_timeout_s=2.0)

        if platform.system() == "Windows":
            assert captured.get("creationflags") == 0x08000000
