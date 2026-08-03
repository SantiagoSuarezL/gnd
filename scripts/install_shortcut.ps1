<#
.SYNOPSIS
    Crea o actualiza el acceso directo "GND.lnk" en el escritorio del
    usuario actual, apuntando al launcher launch_gnd.vbs con icono de
    Network and Sharing Center (imageres.dll,19).

.DESCRIPTION
    Idempotente: si el .lnk ya existe lo sobreescribe.
    Auto-detecta el repo root relativo al propio script ($PSScriptRoot
    -> Split-Path -Parent), asi que sobrevive a movimientos del repo
    entero sin editar nada.

    Target  : wscript.exe (corrige el VBS en modo GUI, no imprime a consola)
    Args    : ruta absoluta a launch_gnd.vbs (con comillas dobles por espacios)
    WorkDir : repo root (Path.cwd() al arrancar python -m gnd -> config.toml
              encontrado en Path.cwd()/config.toml)
    Icon    : %SystemRoot%\System32\imageres.dll,19

    No requiere admin. No toca el codigo Python. No modifica el venv.

.NOTES
    Ver tech_stack.md -> "Empaquetado y acceso directo" para contexto
    de diseno (decision Opcion C: vbs + venv local vs PyInstaller).
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Repo root = carpeta padre de scripts/. Resolve-Path normaliza la ruta.
$repoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$vbsPath  = Join-Path $repoRoot 'launch_gnd.vbs'

if (-not (Test-Path -LiteralPath $vbsPath)) {
    throw "No se encontro launch_gnd.vbs en: $vbsPath`nEsperado en el root del repo junto a este script."
}

$wscriptExe = Join-Path $env:SystemRoot 'System32\wscript.exe'
if (-not (Test-Path -LiteralPath $wscriptExe)) {
    throw "No se encontro wscript.exe en: $wscriptExe"
}

$imageres = Join-Path $env:SystemRoot 'System32\imageres.dll'
if (-not (Test-Path -LiteralPath $imageres)) {
    throw "No se encontro imageres.dll en: $imageres"
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'GND.lnk'

$wsh = New-Object -ComObject WScript.Shell
try {
    $lnk = $wsh.CreateShortcut($lnkPath)
    $lnk.TargetPath       = $wscriptExe
    # Doble comilla dentro de Arguments para preservar espacios en el
    # path absoluto del .vbs (por si el usuario movio el repo a una
    # carpeta con espacios, ej. "C:\Mis Proyectos\gnd\launch_gnd.vbs").
    $lnk.Arguments        = '"' + $vbsPath + '"'
    $lnk.WorkingDirectory = $repoRoot
    # imageres.dll,19 = Network and Sharing Center (Win10/11), index
    # estable entre versiones de Windows. Verde/azulado, connota red.
    $lnk.IconLocation     = $imageres + ',19'
    $lnk.Description      = 'Game Network Diagnostics'
    # WindowStyle 7 = minimized. wscript.exe no abre ventana propia
    # (es un punente a la GUI host de WSH), pero minimizar nunca hace
    # dano si algun Windows lo abre por razon oscura.
    $lnk.WindowStyle      = 7
    $lnk.Save()
} finally {
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null
}

Write-Host "Acceso directo creado:" -ForegroundColor Green
Write-Host "  $lnkPath" -ForegroundColor Cyan
Write-Host "  Target : $wscriptExe `"$vbsPath`"" -ForegroundColor DarkGray
Write-Host "  Icon   : $imageres,19" -ForegroundColor DarkGray
Write-Host "  WorkDir: $repoRoot" -ForegroundColor DarkGray
