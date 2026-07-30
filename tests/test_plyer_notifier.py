"""Tests del adapter PlyerDesktopNotifier (Fase 12b.2).

Cobertura:
- Construcción exitosa: plyer disponible, ``_available=True``.
- ``notify`` exitoso: plyer.notification.notify mockeado — verifica kwargs.
- plyer no instalado: ImportError capturado, ``_available=False``, notify
  posterior se vuelve no-op (no lanza).
- Backend sin soporte (NotImplementedError): notify captura y loguea,
  no propaga.
- Otros errores (OSError/RuntimeError): mismo patrón.
- app_name y timeout propagados a plyer.
- Eventos estructurados: notification.start / notification.finish /
  notification.error / notification.skip emitidos (cap assert via
  caplog + verificar keys en extra).
"""

from __future__ import annotations

import logging

import gnd.notifications.plyer_notifier as pn_mod
from gnd.models.notification import DesktopNotification

# ── Tests de notify (con plyer real ya importable en el env) ───────────


class TestNotifyExitoso:
    def test_notify_llama_plyer_con_title_y_message(self, monkeypatch) -> None:
        # plyer esta instalado en el env de tests (pyproject). Verificamos
        # que el adapter lo usa — patcheando el facade real ``notify``.
        from plyer import notification as real_pn

        calls: list[dict] = []

        def _fake_notify(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(real_pn, "notify", _fake_notify)
        notifier = pn_mod.PlyerDesktopNotifier(app_name="GND-test", timeout_seconds=5)
        n = DesktopNotification(title="GND — OK", message="Todo bien")
        notifier.notify(n)
        assert calls
        assert calls[0]["title"] == "GND — OK"
        assert calls[0]["message"] == "Todo bien"
        assert calls[0]["app_name"] == "GND-test"
        assert calls[0]["timeout"] == 5

    def test_notify_devuelve_none_sin_lanzar(self, monkeypatch) -> None:
        from plyer import notification as real_pn

        def _fake_notify(**kwargs):
            pass

        monkeypatch.setattr(real_pn, "notify", _fake_notify)
        notifier = pn_mod.PlyerDesktopNotifier()
        result = notifier.notify(DesktopNotification(title="t", message="m"))
        assert result is None


# ── Tests de captura de excepciones de plyer ──────────────────────────


class TestCapturaErroresPlyer:
    def test_notimplementederror_capturado_no_propaga(self, monkeypatch) -> None:
        """plyer levanta NotImplementedError si no encuentra backend."""
        from plyer import notification as real_pn

        def _raising_notify(**kwargs):
            raise NotImplementedError("No backend")

        monkeypatch.setattr(real_pn, "notify", _raising_notify)
        notifier = pn_mod.PlyerDesktopNotifier()
        # No debe lanzar.
        notifier.notify(DesktopNotification(title="t", message="m"))

    def test_runtime_error_capturado_no_propaga(self, monkeypatch) -> None:
        from plyer import notification as real_pn

        def _raising_notify(**kwargs):
            raise RuntimeError("backend failed")

        monkeypatch.setattr(real_pn, "notify", _raising_notify)
        notifier = pn_mod.PlyerDesktopNotifier()
        notifier.notify(DesktopNotification(title="t", message="m"))

    def test_oserror_capturado_no_propaga(self, monkeypatch) -> None:
        from plyer import notification as real_pn

        def _raising_notify(**kwargs):
            raise OSError("system")

        monkeypatch.setattr(real_pn, "notify", _raising_notify)
        notifier = pn_mod.PlyerDesktopNotifier()
        notifier.notify(DesktopNotification(title="t", message="m"))

    def test_exception_generica_capturada_no_propaga(self, monkeypatch) -> None:
        from plyer import notification as real_pn

        class _Custom(Exception):
            pass

        def _raising_notify(**kwargs):
            raise _Custom("boom")

        monkeypatch.setattr(real_pn, "notify", _raising_notify)
        notifier = pn_mod.PlyerDesktopNotifier()
        notifier.notify(DesktopNotification(title="t", message="m"))


# ── Tests de eventos estructurados (Regla 11.3) ───────────────────────


class TestEventosEstructurados:
    def test_notify_exitoso_emite_start_y_finish(self, monkeypatch, caplog) -> None:
        from plyer import notification as real_pn

        def _fake_notify(**kwargs):
            pass

        monkeypatch.setattr(real_pn, "notify", _fake_notify)
        caplog.set_level(logging.INFO, logger="gnd.notifications.plyer_notifier")
        notifier = pn_mod.PlyerDesktopNotifier()
        notifier.notify(DesktopNotification(title="t", message="m"))

        events = [
            r.__dict__.get("event") for r in caplog.records if hasattr(r, "event")
        ]
        assert "notification.start" in events
        assert "notification.finish" in events

    def test_notify_fallido_emite_start_y_error(self, monkeypatch, caplog) -> None:
        from plyer import notification as real_pn

        def _raising(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(real_pn, "notify", _raising)
        caplog.set_level(logging.INFO, logger="gnd.notifications.plyer_notifier")
        notifier = pn_mod.PlyerDesktopNotifier()
        notifier.notify(DesktopNotification(title="t", message="m"))

        events = [
            r.__dict__.get("event") for r in caplog.records if hasattr(r, "event")
        ]
        assert "notification.start" in events
        assert "notification.error" in events
        # finish no emitido si fallo.
        assert "notification.finish" not in events


# ── Tests de plyer no disponible en runtime ───────────────────────────


class TestPlyerNoDisponible:
    def test_adapter_marca_available_false_si_import_falla(
        self, monkeypatch, caplog
    ) -> None:
        # Simular import fallido cachando builtins.__import__ en el scope
        # del modulo adapter.
        import builtins

        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name == "plyer":
                raise ImportError("mocked: plyer not available")
            return real_import(name, *args, **kwargs)

        # Sincronizamos: quitamos plyer del cache de modulos para forzar
        # re-import.
        import sys

        monkeypatch.setattr(builtins, "__import__", _blocking_import)
        sys.modules.pop("plyer", None)
        sys.modules.pop("plyer.notification", None)
        try:
            caplog.set_level(logging.WARNING, logger="gnd.notifications.plyer_notifier")
            notifier = pn_mod.PlyerDesktopNotifier()
            assert notifier._available is False
            assert notifier._pn is None
        finally:
            # Restauramos: plyer ya esta en pyproject, proximos tests lo
            # necesitan. Solo volvemos a importar explicito.
            monkeypatch.setattr(builtins, "__import__", real_import)
            # Re-import plyer para no romper otros tests.
            import importlib

            importlib.invalidate_caches()
            import plyer  # noqa: F401

    def test_notify_sin_plyer_es_noop_y_emite_skip(self, monkeypatch, caplog) -> None:
        import builtins

        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name == "plyer":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        import sys

        monkeypatch.setattr(builtins, "__import__", _blocking_import)
        sys.modules.pop("plyer", None)
        sys.modules.pop("plyer.notification", None)
        try:
            notifier = pn_mod.PlyerDesktopNotifier()
            caplog.set_level(logging.INFO, logger="gnd.notifications.plyer_notifier")
            # No debe lanzar.
            notifier.notify(DesktopNotification(title="t", message="m"))
            events = [
                r.__dict__.get("event") for r in caplog.records if hasattr(r, "event")
            ]
            assert "notification.skip" in events
        finally:
            monkeypatch.setattr(builtins, "__import__", real_import)
            import importlib

            importlib.invalidate_caches()
            import plyer  # noqa: F401


# ── Test de admisión al Protocol con runtime_checkable ────────────────


class TestProtocolCompliance:
    def test_plyer_notifier_satisface_protocol(self, monkeypatch) -> None:
        from plyer import notification as real_pn

        monkeypatch.setattr(real_pn, "notify", lambda **kwargs: None)
        from gnd.domain.ports.notifier import DesktopNotifier

        notifier = pn_mod.PlyerDesktopNotifier()
        assert isinstance(notifier, DesktopNotifier)
