# CI local — Fase 0 (IMPLEMENTATION_PLAN.md)
# Ejecutar desde la raiz del proyecto con el entorno virtual (.venv) activado:
#     .\.venv\Scripts\Activate.ps1
#     .\scripts\check.ps1
# Corre ruff, vulture, black, pytest y pip-audit en un solo comando.
# Detiene la ejecucion en el primer error (via exit codes explicitos).
#
# Problema resuelto: PowerShell 5.1 convierte stderr de nativos
# (especialmente `black`, que escribe "All done!" a stderr por diseno) en
# RemoteException, contaminando el output aunque LASTEXITCODE=0. Solucion:
# ejecutamos cada tool via `cmd /c <tool> 2>&1`, que produce un texto unificado
# y sin RemoteException (cmd captura el stderr nativo como string).
#
# Invocamos via `python -m <tool>` para robustez: funciona tanto si los
# entry points del .venv estan en el PATH (venv activado) como si python
# resuelve al del venv por el selector por defecto. Si ruff no se
# encuentra, recordatorio: hay que activarlo (`.\.venv\Scripts\Activate.ps1`).

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

$rc = Check-Step "ruff check" "python -m ruff check ."
if ($rc -ne 0) { Write-Host "FAIL: ruff rc=$rc" -ForegroundColor Red; exit $rc }

$rc = Check-Step "vulture (codigo muerto)" "python -m vulture"
# vulture devuelve exit code 1 si encuentra codigo muerto; rc=0 = limpio.
if ($rc -ne 0) {
    Write-Host "FAIL: vulture rc=$rc (codigo muerto detectado arriba). " `
        "Resolver antes de commit (incidente Fase 6: x=1+2+3 sobrev. 8 fases)." `
        -ForegroundColor Red
    exit $rc
}

$rc = Check-Step "black --check" "python -m black --check ."
if ($rc -ne 0) { Write-Host "FAIL: black rc=$rc" -ForegroundColor Red; exit $rc }

$rc = Check-Step "pytest" "python -m pytest -q"
if ($rc -ne 0) { Write-Host "FAIL: pytest rc=$rc" -ForegroundColor Red; exit $rc }

# pip-audit consulta la base publica de CVEs de paquetes Python (PyPA/OSV).
# Exit code 0 = sin vulnerabilidades conocidas; 1 = hay vulnerabilidades;
# 2 = fallo de ejecucion (p.ej. sin red o sin index alcanzable).
$rc = Check-Step "pip-audit" "python -m pip_audit"
if ($rc -ne 0) {
    Write-Host "FAIL: pip-audit rc=$rc (CVE conocidos en dependencias o `nfallo al consultar la base de vulnerabilidades). Actualizar deps o revisar red." -ForegroundColor Red
    exit $rc
}

Write-Host "OK: ruff, vulture, black, pytest y pip-audit pasaron sin errores." -ForegroundColor Green
