"""Paquete export — render de corridas a formatos portables (Fase 12b.1).

Solo Markdown por ahora (12b.1). El modulo ``markdown_renderer`` expone
``render_run_to_markdown(run)`` — funcion pura que toma un ``DiagnosticRun``
y devuelve un string Markdown autoexplicativo, sin IO ni dependencias
externas.

 Futuro: si se anaden mas formatos (PDF, HTML), definir un Protocol
 ``RunRenderer`` con multiples implementaciones. Por ahora YAGNI — solo un
 formato, funcion libre basta (ver docstring de ``markdown_renderer.py``).
"""

from gnd.export.markdown_renderer import render_run_to_markdown

__all__ = ["render_run_to_markdown"]
