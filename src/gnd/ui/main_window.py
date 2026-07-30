"""MainWindow — ventana principal dark mode con 5 secciones (PRD §7).

Fase 9 (IMPLEMENTATION_PLAN.md): UI oscura, un clic ejecuta todo, sin
bloquear la interfaz durante los sondeos. Usa tkinter (decision 2026-07-25:
stdlib, sin dependencias externas).

Layout:
- Top bar: titulo + boton "Run Diagnostics" + label de estado.
- Notebook (ttk): una pestana por seccion del PRD (5 en total).
- Status bar: progreso + timestamp de la ultima corrida.

Threading:
- El boton lanza `DiagnosticsController.run_async()`.
- Los callbacks del controller (`on_progress`, `on_result`, `on_error`)
  se agendan al main loop via `self.after(0, ...)` — nunca tocan
  widgets directamente desde el worker thread (tkinter no es thread-safe).
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gnd.application.run_full_diagnostics import (
    DiagnosticParams,
    DiagnosticTargets,
    RunFullDiagnostics,
)
from gnd.application.speed_test_comparison import (
    SpeedTestComparisonParams,
    SpeedTestComparisonUseCase,
)
from gnd.application.warp_comparison import WarpComparisonParams, WarpComparisonUseCase
from gnd.config import Notifications
from gnd.config import SpeedTest as SpeedTestSettings
from gnd.config import WarpComparison as WarpComparisonSettings
from gnd.domain.ports.notifier import DesktopNotifier
from gnd.domain.ports.speed_test_controller import SpeedTestController
from gnd.domain.ports.warp_controller import WarpController
from gnd.export import render_run_to_markdown
from gnd.models.diagnostic_run import DiagnosticRun
from gnd.models.speed_test import SpeedTestComparisonResult
from gnd.models.warp_comparison import WarpComparisonResult
from gnd.notifications.run_formatter import build_run_notification
from gnd.reports.scheduler import ReportsScheduler
from gnd.ui.charts_section import ChartsSection
from gnd.ui.controller import DiagnosticsController
from gnd.ui.sections import (
    CurrentStatusSection,
    HistoricalComparisonSection,
    NetworkTestsSection,
    RecommendationsSection,
    RouteAnalysisSection,
)
from gnd.ui.speed_test_comparison_controller import SpeedTestComparisonController
from gnd.ui.speed_test_comparison_section import SpeedTestComparisonSection
from gnd.ui.warp_comparison_controller import WarpComparisonController
from gnd.ui.warp_comparison_section import WarpComparisonSection
from gnd.visualization import SeriesDataSource

logger = logging.getLogger(__name__)


# Paleta dark mode (colores derivados del tema "dark" de VS Code, una
# ref familiar para el usuario. Tecnicamente: tonos medios de gris con
# acento azul para emphasize.)
_BG = "#1e1e1e"
_BG_ALT = "#252526"
_FG = "#d4d4d4"
_FG_DIM = "#808080"
_ACCENT = "#007acc"
_BORDER = "#3c3c3c"


def apply_dark_theme(root: tk.Tk) -> ttk.Style:
    """Aplica un tema dark a ttk via `ttk.Style`.

    tkinter no trae un dark theme oob, pero `ttk.Style` permite
    customizar colores de los widgets ttk (botones, notebook, labels).
    Los widgets `tk.Text` usan colores directos via options (no style),
    por eso se setean explicitamente en `sections.py`.
    """
    root.configure(background=_BG)
    style = ttk.Style(root)
    # Ignoramos el theme por default; partimos de 'clam' que es el
    # mas flexible para customizar (otros themes como 'vista' en
    # Windows no respetan todos los_options).
    style.theme_use("clam")

    style.configure("TFrame", background=_BG, foreground=_FG)
    style.configure("TButton", background=_BG_ALT, foreground=_FG, borderwidth=0)
    style.map(
        "TButton",
        background=[("active", _ACCENT), ("disabled", _BG_ALT)],
        foreground=[("disabled", _FG_DIM)],
    )
    style.configure("TLabel", background=_BG, foreground=_FG)
    style.configure("TNotebook", background=_BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab", background=_BG_ALT, foreground=_FG_DIM, padding=(12, 6)
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", _BG), ("active", _BG_ALT)],
        foreground=[("selected", _FG), ("active", _FG)],
    )
    style.configure("SectionHeader.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
    return style


class MainWindow:
    """Ventana principal. Orquesta la UI y delega trabajo al controller.

    MVC ligero: MainWindow = View+Controller (UI), DiagnosticsController =
    Controller (worker), RunFullDiagnostics = Model/UseCase. La MainWindow
    no conoce implementaciones concretas de los Protocol — solo el caso
    de uso ya construido (composition_root).
    """

    def __init__(
        self,
        *,
        use_case: RunFullDiagnostics,
        targets: DiagnosticTargets,
        params: DiagnosticParams,
        series_source: SeriesDataSource | None = None,
        notifier: DesktopNotifier | None = None,
        notify_settings: Notifications | None = None,
        report_scheduler: ReportsScheduler | None = None,
        warp_controller: WarpController | None = None,
        warp_comparison: WarpComparisonUseCase | None = None,
        warp_settings: WarpComparisonSettings | None = None,
        speed_test_controller: SpeedTestController | None = None,
        speed_test_comparison: SpeedTestComparisonUseCase | None = None,
        speed_test_settings: SpeedTestSettings | None = None,
    ) -> None:
        self._use_case = use_case
        self._targets = targets
        self._params = params
        self._series_source = series_source
        # Fase 12b.1: el botón "Export Markdown" se habilita solo cuando hay
        # un run reciente disponible. None hasta el primer run exitoso.
        self._last_run: DiagnosticRun | None = None
        # Fase 12b.2: notifier de escritorio inyectado ( composition_root
        # pasa ``PlyerDesktopNotifier`` en prod; tests pasan
        # ``FakeDesktopNotifier``). ``None`` = feature desactivada —
        # `_maybe_send_notification` se vuelve no-op si el notifier falta
        # o si ``notify_settings`` no esta seteada con ``enabled=True``.
        # Backwards-compat: callers existentes (tests de 12b.1) llaman
        # ``MainWindow(use_case=..., targets=..., params=...)`` sin estos
        # kwargs — notificaciones deshabilitadas en ese caso.
        self._notifier = notifier
        self._notify_settings = notify_settings
        # Fase 12b.3: scheduler de reportes periodicos. None en tests
        # backwards-compat y cuando ``settings.reports.enabled=False``
        # (composition_root solo construye el scheduler si enabled=True).
        # El scheduler se arranca en ``run()`` y se detiene al cerrar la
        # ventana (WM_DELETE_WINDOW protocol hook).
        self._report_scheduler = report_scheduler
        # Fase 12b.4: comparación WARP on/off. None = feature desactivada
        # (settings.warp_comparison.enabled=False o caller no pasó kwargs).
        # El RealWarpController se construye siempre en composition_root
        # (cheap check de PATH); el WarpComparisonUseCase solo si el usuario
        # habilitó la feature (opt-in). Backwards-compat: callers pre-12b.4
        # siguen funcionando sin estos kwargs.
        self._warp_controller = warp_controller
        self._warp_comparison = warp_comparison
        self._warp_settings = warp_settings
        self._last_warp_result: WarpComparisonResult | None = None
        # Fase 12b.5: speed test bajo demanda. None = feature desactivada
        # (settings.speed_test.enabled=False o caller no pasó kwargs).
        # El RealSpeedTestController se construye siempre en composition_root
        # (cheap check de PATH); el SpeedTestComparisonUseCase solo si el
        # usuario habilitó la feature (opt-in). Backwards-compat: callers
        # pre-12b.5 siguen funcionando sin estos kwargs.
        self._speed_test_controller = speed_test_controller
        self._speed_test_comparison = speed_test_comparison
        self._speed_test_settings = speed_test_settings
        self._last_speed_test_result: SpeedTestComparisonResult | None = None
        self._controller = DiagnosticsController(
            use_case=use_case,
            targets=targets,
            params=params,
            on_progress=self._on_progress,
            on_result=self._on_result,
            on_error=self._on_error,
        )
        # Controller de comparación WARP (solo si use_case está inyectado).
        # Mismo patrón: thread daemon + callbacks al main loop.
        self._warp_controller_thread: WarpComparisonController | None = None
        if warp_comparison is not None and warp_settings is not None:
            self._warp_controller_thread = WarpComparisonController(
                use_case=warp_comparison,
                targets=targets,
                diagnostic_params=params,
                warp_params=WarpComparisonParams(
                    diagnostic_params=params,
                    restore_original_state=warp_settings.restore_original_state,
                ),
                on_progress=self._on_warp_progress,
                on_result=self._on_warp_result,
                on_error=self._on_warp_error,
            )
        # Controller de speed test (solo si use_case está inyectado).
        # Mismo patrón: thread daemon + callbacks al main loop.
        self._speed_test_controller_thread: SpeedTestComparisonController | None = None
        if speed_test_comparison is not None and speed_test_settings is not None:
            self._speed_test_controller_thread = SpeedTestComparisonController(
                use_case=speed_test_comparison,
                targets=targets,
                diagnostic_params=params,
                speed_test_params=SpeedTestComparisonParams(
                    diagnostic_params=params,
                ),
                on_progress=self._on_speed_test_progress,
                on_result=self._on_speed_test_result,
                on_error=self._on_speed_test_error,
            )

        self._root = tk.Tk()
        self._root.title("Game Network Diagnostics")
        self._root.geometry("920x620")
        self._root.minsize(720, 480)
        apply_dark_theme(self._root)

        self._build_layout()

    def _build_layout(self) -> None:
        # Top bar: titulo + boton run + estado
        top = ttk.Frame(self._root, padding=(12, 8))
        top.pack(side="top", fill="x")

        ttk.Label(
            top, text="Game Network Diagnostics", style="SectionHeader.TLabel"
        ).pack(side="left")

        self._run_button = ttk.Button(
            top,
            text="Run Diagnostics",
            command=self._on_click_run,
            style="Accent.TButton",
        )
        self._run_button.pack(side="right", padx=(0, 0))

        # Fase 12b.1: Export Markdown de la última corrida. Disabled hasta
        # que haya un run exitoso (handler habilita en `_apply_run`).
        # Mismo grupo de botones que Run, a la izquierda del run_button.
        self._export_button = ttk.Button(
            top,
            text="Export Markdown",
            command=self._on_click_export_markdown,
            state="disabled",
        )
        self._export_button.pack(side="right", padx=(0, 8))

        # Fase 12b.4: comparación WARP on/off. Disabled si la feature no
        # está habilitada en config (warp_settings.enabled=False) o si
        # warp-cli no está en PATH (warp_controller no disponible). El
        # handler habilita en setup si todo está OK.
        self._warp_button = ttk.Button(
            top,
            text="Run WARP Comparison",
            command=self._on_click_warp_comparison,
            state="disabled",
        )
        self._warp_button.pack(side="right", padx=(0, 8))

        # Fase 12b.5: speed test bajo demanda. Disabled si la feature no
        # está habilitada en config (speed_test_settings.enabled=False) o si
        # speedtest no está en PATH (speed_test_controller no disponible).
        self._speed_test_button = ttk.Button(
            top,
            text="Run Speed Test",
            command=self._on_click_speed_test,
            state="disabled",
        )
        self._speed_test_button.pack(side="right", padx=(0, 8))

        self._status_label = ttk.Label(top, text="Listo.", foreground=_FG_DIM)
        self._status_label.pack(side="right", padx=(0, 16))

        # Notebook con las 5 secciones + Charts + WARP Comparison
        nb = ttk.Notebook(self._root)
        nb.pack(side="top", fill="both", expand=True, padx=8, pady=8)

        self._sec_current = CurrentStatusSection(nb)
        nb.add(self._sec_current, text="Current Status")
        self._sec_tests = NetworkTestsSection(nb)
        nb.add(self._sec_tests, text="Network Tests")
        self._sec_route = RouteAnalysisSection(nb)
        nb.add(self._sec_route, text="Route Analysis")
        self._sec_hist = HistoricalComparisonSection(nb)
        nb.add(self._sec_hist, text="Historical Comparison")
        self._sec_rec = RecommendationsSection(nb)
        nb.add(self._sec_rec, text="Recommendations")
        self._sec_charts = ChartsSection(nb)
        nb.add(self._sec_charts, text="Charts")
        self._sec_warp = WarpComparisonSection(nb)
        nb.add(self._sec_warp, text="WARP Compare")
        self._sec_speed_test = SpeedTestComparisonSection(nb)
        nb.add(self._sec_speed_test, text="Speed Test")
        if self._series_source is not None:
            self._sec_charts.set_source(self._series_source)

        # Inicialmente vacias
        for sec in (
            self._sec_current,
            self._sec_tests,
            self._sec_route,
            self._sec_hist,
            self._sec_rec,
            self._sec_warp,
            self._sec_speed_test,
        ):
            sec.update_state({})

        # Habilitar botón WARP si feature está disponible
        self._update_warp_button_state()
        # Habilitar botón Speed Test si feature está disponible
        self._update_speed_test_button_state()

    # --- Boton callback ---

    def _on_click_run(self) -> None:
        if self._controller.is_running():
            return
        self._run_button.configure(state="disabled")
        self._status_label.configure(text="Ejecutando diagnóstico...")
        self._controller.run_async()

    # --- Controller callbacks (ejecutados desde worker thread) ---
    # Estos metodos se invocan desde el thread del controller, por lo que
    # solo agendamos UI updates via `self._root.after(0, ...)`.

    def _on_progress(self, stage: str) -> None:
        self._root.after(
            0, lambda: self._status_label.configure(text=f"Etapa: {stage}")
        )

    def _on_result(self, run: DiagnosticRun) -> None:
        self._root.after(0, lambda: self._apply_run(run))

    def _on_error(self, msg: str) -> None:
        self._root.after(0, lambda: self._apply_error(msg))

    # --- Aplicacion de resultados en el main loop ---

    def _apply_run(self, run: DiagnosticRun) -> None:
        """Aplica el resultado del run a todas las secciones (main loop)."""
        # Fase 12b.1: guardamos el run para que el botón "Export Markdown"
        # pueda acceder al último sin pedirlo de nuevo al use_case.
        self._last_run = run
        self._export_button.configure(state="normal")

        # Baselines ya computados en Etapa 5 del use_case (execute()) en
        # el worker thread. Los reutilizamos aca (main loop) SIN pedir
        # una nueva conn — Regla de Oro 9.1. Antes de Fase 9 fix, esto
        # llamaba compute_baseline(db) donde db era la conn del worker
        # thread -> nuevo ProgrammingError cross-thread cuando la UI
        # trata de leer. Ahora el use_case expone ``last_baselines``.
        baselines: dict[str, object] = dict(
            getattr(self._use_case, "last_baselines", {}) or {}
        )

        current_state = {
            "recommendation": run.recommendation,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        tests_state = {"probes": run.probes}
        route_state = {"traceroutes": run.traceroutes}
        hist_state = {
            "baselines": baselines,
            "probes": run.probes,
        }
        rec_state = {
            "recommendation": run.recommendation,
            "probes": run.probes,
        }

        self._sec_current.update_state(current_state)
        self._sec_tests.update_state(tests_state)
        self._sec_route.update_state(route_state)
        self._sec_hist.update_state(hist_state)
        self._sec_rec.update_state(rec_state)

        # Charts: auto-refresh para que los nuevos datos del run aparezcan
        # en los gráficos sin que el usuario tenga que tocar "Refresh".
        # El refresh es sync (queries rápidas) y solo si hay source seteada.
        if self._series_source is not None:
            try:
                self._sec_charts.refresh()
            except Exception:  # noqa: BLE001 — no romper la UI por un chart
                logger.exception("Falla refrescando charts tras run")

        self._run_button.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self._status_label.configure(text=f"Listo (últ. corrida: {ts}).")

        # Fase 12b.2: notificación de escritorio (toast) al terminar el run.
        # El filtrado (enabled/notify_only_on_issues) vive en `notify_settings`,
        # el envío en `notifier`. Si el notifier falta (None) o settings no
        # pide notificar, no-op silencioso. No blockea la UI: plyer.notify es
        # blando (<10ms) y corre en el main loop (no en worker thread).
        self._maybe_send_notification(run)

    def _maybe_send_notification(self, run: DiagnosticRun) -> None:
        """Envía una notificación de escritorio al terminar el run (Fase 12b.2).

        Reglas:
        - Si ``notifier`` o ``notify_settings`` es None → no-op (feature
          deshabilitada en config o wiring de test sin notifier).
        - Si ``notify_settings.enabled=False`` → no-op con log skip
          (explicíto, no ruido silencioso — confirma feature off).
        - Llama al formatter para construir la ``DesktopNotification``;
          si devuelve ``None`` (``notify_only_on_issues=True`` +
          verdict EXCELENTE) → no-op con ``event="notification.skip"``.
        - Si el notifier lanza (defensa-in-depth — el adapter ya captura,
          pero por si un adapter buggy lo deja escapar) → captura y
          loguea (EP §1.2: la notif nunca rompe el run/UI).
        """
        if self._notifier is None or self._notify_settings is None:
            return

        if not self._notify_settings.enabled:
            logger.info(
                "Notificación omitida (feature deshabilitada)",
                extra={
                    "event": "notification.skip",
                    "reason": "settings_disabled",
                },
            )
            return

        notification = build_run_notification(
            run,
            notify_only_on_issues=self._notify_settings.notify_only_on_issues,
        )
        if notification is None:
            logger.info(
                "Notificación omitida (verdict EXCELENTE + notify_only_on_issues)",
                extra={
                    "event": "notification.skip",
                    "reason": "verdict_safe_filter",
                    "verdict": run.recommendation.verdict,
                },
            )
            return

        try:
            self._notifier.notify(notification)
        except Exception as exc:  # noqa: BLE001 — defense-in-depth (adapter)
            logger.exception(
                "Notifier levantó excepción (debería captura en adapter)",
                extra={
                    "event": "notification.error",
                    "error": str(exc),
                    "exc_class": type(exc).__name__,
                },
            )

    def _apply_error(self, msg: str) -> None:
        self._run_button.configure(state="normal")
        self._status_label.configure(text=f"Error: {msg}")
        # Fase 12b.1: no habilitamos export ante un run fallido — el
        # `_last_run` queda con el anterior exitoso (o None). Si el usuario
        # quiere exportar el último exitoso, lo puede hacer.
        # Mostrar en seccion Current Status tambien
        self._sec_current.update_state(
            {
                "recommendation": None,
                "_error": msg,
            }
        )

    # --- Export Markdown (Fase 12b.1) ---

    def _on_click_export_markdown(self) -> None:
        """Exporta el último run a Markdown.

        Pide path al user via filedialog, llama al renderer (puro) y
        escribe el archivo. Cualquier falla (IO, path inválido, renderer)
        se loguea con event=export.error y se notifica via messagebox.
        Regla 11.3: eventos export.start / export.finish / export.error
        con `path` en extra. Regla 11.2: si `_last_run` es None (botón
        wurde disabled pero invocado via teclado/acceso programático), es
        no-op silencioso (omitemos el log del caso None — ruido).
        """
        run = self._last_run
        if run is None:
            # No debería ocurrir: el botón está disabled. Pero por guarda,
            # no hacer nada (sin log — sería ruido).
            return

        # Sugerir filename con run_id + timestamp para sobre-escritura
        # implicita entre runs del mismo día.
        suggested = f"gnd_{run.started_at.strftime('%Y%m%d_%H%M%S')}.md"
        path_str = filedialog.asksaveasfilename(
            title="Exportar a Markdown",
            defaultextension=".md",
            initialfile=suggested,
            filetypes=[("Markdown", "*.md"), ("Todos los archivos", "*.*")],
        )
        # Cancel del dialog → string vacío.
        if not path_str:
            return

        path = Path(path_str)
        logger.info(
            "Export Markdown iniciado",
            extra={"event": "export.start", "path": str(path)},
        )
        try:
            content = render_run_to_markdown(run)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.exception(
                "Export Markdown falló (IO)",
                extra={"event": "export.error", "path": str(path)},
            )
            messagebox.showerror(
                "Error al exportar",
                f"No se pudo escribir el archivo:\n{path}\n\n{exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001 — no romper la UI por un export
            logger.exception(
                "Export Markdown falló (renderer)",
                extra={"event": "export.error", "path": str(path)},
            )
            messagebox.showerror(
                "Error al exportar",
                f"Error inesperado generando el reporte:\n\n{exc!r}",
            )
            return

        logger.info(
            "Export Markdown completado",
            extra={"event": "export.finish", "path": str(path)},
        )
        self._status_label.configure(text=f"Exportado: {path.name}")
        messagebox.showinfo(
            "Export completado",
            f"Reporte guardado en:\n{path}",
        )

    # --- WARP Comparison (Fase 12b.4) ---

    def _update_warp_button_state(self) -> None:
        """Habilita el botón WARP si la feature está disponible."""
        if self._warp_controller is None or self._warp_settings is None:
            self._warp_button.configure(state="disabled")
            return
        if not self._warp_settings.enabled:
            self._warp_button.configure(state="disabled")
            return
        if not getattr(self._warp_controller, "available", True):
            # RealWarpController expone `available` (False si warp-cli no está en PATH).
            # Fake no tiene este atributo → getattr default True.
            self._warp_button.configure(state="disabled")
            self._status_label.configure(
                text="warp-cli no encontrado — comparación WARP deshabilitada"
            )
            return
        self._warp_button.configure(state="normal")

    def _update_speed_test_button_state(self) -> None:
        """Habilita el botón Speed Test si la feature está disponible."""
        if self._speed_test_controller is None or self._speed_test_settings is None:
            self._speed_test_button.configure(state="disabled")
            return
        if not self._speed_test_settings.enabled:
            self._speed_test_button.configure(state="disabled")
            return
        if not getattr(self._speed_test_controller, "available", True):
            self._speed_test_button.configure(state="disabled")
            self._status_label.configure(
                text="speedtest no encontrado — speed test deshabilitado"
            )
            return
        self._speed_test_button.configure(state="normal")

    def _on_click_warp_comparison(self) -> None:
        """Lanza la comparación WARP on/off en thread daemon."""
        if self._warp_controller_thread is None:
            return
        if self._warp_controller_thread.is_running():
            return
        if self._controller.is_running():
            messagebox.showwarning(
                "Diagnóstico en curso",
                "Espera a que termine el diagnóstico actual antes de comparar WARP.",
            )
            return
        self._warp_button.configure(state="disabled")
        self._run_button.configure(state="disabled")
        self._status_label.configure(text="Comparando WARP off vs on...")
        self._sec_warp.update_state({"is_running": True})
        self._warp_controller_thread.run_async()

    def _on_warp_progress(self, stage: str) -> None:
        """Callback de progreso de la comparación WARP (thread controller)."""
        self._root.after(
            0,
            lambda: self._status_label.configure(text=f"WARP: {stage}"),
        )

    def _on_warp_result(self, result: WarpComparisonResult) -> None:
        """Callback de resultado de la comparación WARP."""
        self._root.after(0, lambda: self._apply_warp_result(result))

    def _on_warp_error(self, msg: str) -> None:
        """Callback de error de la comparación WARP."""
        self._root.after(0, lambda: self._apply_warp_error(msg))

    def _apply_warp_result(self, result: WarpComparisonResult) -> None:
        """Aplica el resultado de la comparación WARP a la sección (main loop)."""
        self._last_warp_result = result
        self._sec_warp.update_state({"result": result})
        self._run_button.configure(state="normal")
        self._update_warp_button_state()
        verdict_str = result.overall_verdict.upper()
        self._status_label.configure(text=f"WARP compare: {verdict_str}")

    def _apply_warp_error(self, msg: str) -> None:
        """Aplica error de comparación WARP a la sección (main loop)."""
        self._sec_warp.update_state({"_error": msg})
        self._run_button.configure(state="normal")
        self._update_warp_button_state()
        self._status_label.configure(text=f"WARP compare error: {msg}")

    # --- Speed Test (Fase 12b.5) ---

    def _on_click_speed_test(self) -> None:
        """Lanza el speed test en thread daemon."""
        if self._speed_test_controller_thread is None:
            return
        if self._speed_test_controller_thread.is_running():
            return
        if self._controller.is_running():
            messagebox.showwarning(
                "Diagnóstico en curso",
                "Espera a que termine el diagnóstico antes de "
                "ejecutar el speed test.",
            )
            return
        self._speed_test_button.configure(state="disabled")
        self._run_button.configure(state="disabled")
        self._status_label.configure(text="Ejecutando speed test...")
        self._sec_speed_test.update_state({"is_running": True})
        self._speed_test_controller_thread.run_async()

    def _on_speed_test_progress(self, stage: str) -> None:
        """Callback de progreso del speed test (thread controller)."""
        self._root.after(
            0,
            lambda: self._status_label.configure(text=f"Speed test: {stage}"),
        )

    def _on_speed_test_result(self, result: SpeedTestComparisonResult) -> None:
        """Callback de resultado del speed test."""
        self._root.after(0, lambda: self._apply_speed_test_result(result))

    def _on_speed_test_error(self, msg: str) -> None:
        """Callback de error del speed test."""
        self._root.after(0, lambda: self._apply_speed_test_error(msg))

    def _apply_speed_test_result(self, result: SpeedTestComparisonResult) -> None:
        """Aplica el resultado del speed test a la sección (main loop)."""
        self._last_speed_test_result = result
        self._sec_speed_test.update_state({"result": result})
        self._run_button.configure(state="normal")
        self._update_speed_test_button_state()
        verdict_str = result.overall_verdict.upper()
        self._status_label.configure(text=f"Speed test: {verdict_str}")

    def _apply_speed_test_error(self, msg: str) -> None:
        """Aplica error de speed test a la sección (main loop)."""
        self._sec_speed_test.update_state({"_error": msg})
        self._run_button.configure(state="normal")
        self._update_speed_test_button_state()
        self._status_label.configure(text=f"Speed test error: {msg}")

    # --- Loop ---

    def close(self) -> None:
        """Hook de cierre: detiene el scheduler y destruye la ventana.

        Registrado como protocol ``WM_DELETE_WINDOW`` en ``run()`` y
        también invocable programáticamente desde tests / scripts que
        quieran cerrar limpio. EP §1.2: si ``stop`` levanta excepción,
        la captura para no impedir el ``destroy()`` (el scheduler está
        en un hilo daemon — su cancelación fallida no debe blockar el
        shutdown del proceso).
        """
        if self._report_scheduler is not None:
            try:
                self._report_scheduler.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Falla deteniendo scheduler de reportes")
        self._root.destroy()

    def run(self) -> None:
        # Fase 12b.3: arranca el scheduler de reportes si está inyectado
        # (composition_root solo lo pasa cuando settings.reports.enabled=True).
        # El scheduler abre un hilo daemon; no blocka el mainloop de tkinter.
        if self._report_scheduler is not None:
            try:
                self._report_scheduler.start()
                logger.info(
                    "Scheduler de reportes arrancado por MainWindow",
                    extra={"event": "report.scheduler_start"},
                )
            except Exception:  # noqa: BLE001 — EP §1.2: la UI arranca igual
                logger.exception("Falla arrancando scheduler de reportes (UI continúa)")

        # Hook de cierre: detener el scheduler (cancela timer daemon)
        # antes de destruir el root tkinter. Sin esto, el hilo daemon
        # podría intentar escribir tras el mainloop salir — stderr noise.
        self._root.protocol("WM_DELETE_WINDOW", self.close)
        self._root.mainloop()
