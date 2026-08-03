' launch_gnd.vbs — Launcher de GND sin terminal visible.
'
' Detecta el repo root relativo a este archivo (.vbs), activa el
' venv local via pythonw.exe (no abre consola) y corre `python -m gnd`
' con WorkingDirectory = repo root (asi config.toml en Path.cwd()
' sigue funcionando, ver src/gnd/config/__init__.py:354-356).
'
' Robusto a movimientos del repo: deriva todo relativo al .vbs.
' Si el venv o pythonw.exe no existen, muestra un MsgBox claro
' (silent failure es lo peor que le puede pasar a un launcher).
'
' Ver docs en tech_stack.md → "Empaquetado y acceso directo".

Option Explicit

Dim fso, repoFolder, pythonwExe
Set fso = CreateObject("Scripting.FileSystemObject")
repoFolder = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwExe = repoFolder & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonwExe) Then
    MsgBox "No se encontro el interprete de Python del venv:" & vbCrLf & _
           pythonwExe & vbCrLf & vbCrLf & _
           "Asegurate de que el venv este creado en .venv\ del repo " & _
           "(ej. py -3.12 -m venv .venv && .venv\Scripts\pip install -e .)", _
           vbCritical, "GND - Error de configuracion"
    WScript.Quit 1
End If

Dim wsh
Set wsh = CreateObject("WScript.Shell")
wsh.CurrentDirectory = repoFolder

' `wsh.Run` directo (sin wrapper `cmd /c cd /d`): aunque teóricamente
' no garantiza heredar `CurrentDirectory` al proceso hijo, en la práctica
' WSH sí lo hereda cuando el WindowStyle es 0 y el proceso es windowless
' (pythonw.exe). El wrapper `cmd /c cd /d` que probamos antes rompía la
' invisibilidad: `cmd.exe` spawn su propio `conhost.exe` que se ve como
' terminal parpadeante aunque WindowStyle=0, y propaga visibilidad a
' pythonw.exe hijo. Sin wrapper, pythonw.exe corre invisible.
'
' `config.toml` se carga via `Path.cwd() / "config.toml"`
' (config/__init__.py:354-356) — al setear `wsh.CurrentDirectory` arriba,
' el CWD del Shell (y por tanto del proceso heredado) ya es `repoFolder`.
' Chr(34) = comilla doble para escapar paths con espacios.
wsh.Run Chr(34) & pythonwExe & Chr(34) & " -m gnd", 0, False
