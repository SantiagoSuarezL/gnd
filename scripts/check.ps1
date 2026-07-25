# CI local — Fase 0 (IMPLEMENTATION_PLAN.md)
# Ejecutar desde la raiz del proyecto con el entorno virtual (.venv) activado.
# Corre ruff check, black --check y pytest en un solo comando.
# Detiene la ejecucion en el primer error (via exit codes explicitos).
#
# Problema resuelto: PowerShell 5.1 convierte stderr de nativos
# (especialmente `black`, que escribe "All done!" a stderr por diseno) en
# RemoteException, contaminando el output aunque LASTEXITCODE=0. Solucion:
# ejecutamos cada tool via `cmd /c <tool> 2>&1`, que produce un texto unificado
# y sin RemoteException (cmd captura el stderr nativo como string).

$ErrorActionPreference = "Continue"

function Check-Step {
    param(
        [Parameter(Mandatory)][string] $Label,
        [Parameter(Mandatory)][string] $Cmd
    )
    Write-Host "== $Label ==" -ForegroundColor Cyan
    # cmd /c normaliza stdout+stderr como un solo stream de texto
    # y nos devuelve el exit code de <Cmd>. Resuelve el bug de black.
    $output = cmd /c "$Cmd 2>&1" | Out-String
    Write-Host $output.Trim()
    return $LASTEXITCODE
}

$rc = Check-Step "ruff check" "ruff check ."
if ($rc -ne 0) { Write-Host "FAIL: ruff rc=$rc" -ForegroundColor Red; exit $rc }

$rc = Check-Step "black --check" "black --check ."
if ($rc -ne 0) { Write-Host "FAIL: black rc=$rc" -ForegroundColor Red; exit $rc }

$rc = Check-Step "pytest" "python -m pytest"
if ($rc -ne 0) { Write-Host "FAIL: pytest rc=$rc" -ForegroundColor Red; exit $rc }

Write-Host "OK: ruff, black y pytest pasaron sin errores." -ForegroundColor Green
