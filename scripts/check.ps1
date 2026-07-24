# CI local — Fase 0 (IMPLEMENTATION_PLAN.md)
# Ejecutar desde la raíz del proyecto con el entorno virtual (.venv) activado.
# Corre ruff check, black --check y pytest en un solo comando.
# Detiene la ejecución en el primer error ($ErrorActionPreference + exit codes).

$ErrorActionPreference = "Stop"

Write-Host "== ruff check ==" -ForegroundColor Cyan
ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== black --check ==" -ForegroundColor Cyan
black --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== pytest ==" -ForegroundColor Cyan
pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "OK: ruff, black y pytest pasaron sin errores." -ForegroundColor Green
