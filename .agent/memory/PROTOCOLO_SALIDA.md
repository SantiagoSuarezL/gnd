# PROTOCOLO DE SALIDA (al cerrar una sesión con trabajo hecho)

Antes de cerrar, asegurate de haber hecho esto — en este orden:

1. **Run de verificación obligatorio** antes de declarar hecho:
   - `pytest tests/ -q` (unit) + `pytest tests/ -m integration -q` si tocaste
     código de red/DB.
   - `ruff check <archivos tocados>` + `black --check <archivos tocados>`.
   - `vulture <archivos tocados> --min-confidence 60` si creaste código
     nuevo (Regla 9.5).
   - Si algo rompe, no declares hecho — fixeá o avisá claramente.

2. **Bug fixeado → test de regresión**: si el bug que fixeaste NO tenía un
   test que lo atrapara antes, agregá el test de regresión ANTES de cerrar.
   Un bug sin test de regresión es un bug que va a volver. El test debe
   reproducir el fallo original (archivo físico a disco, path real, subprocess
   real) — no mock del parser. El bug original estaba oculto justamente porque
   el test existente mockeaba demasiado arriba.

3. **Rotación de memoria** (regla estricta de `session_log.md`):
   - La sesión que hoy está en "ÚLTIMA SESIÓN" se comprime a 1-3 líneas y
     pasa al "HISTORIAL RELEVANTE".
   - El detalle completo se mueve a `session_log_archive.md`.
   - Nunca debe haber más de 1 sesión en detalle completo en `session_log.md`.
   - Si agregaste Reglas de Oro nuevas a `lessons_learned.md` y quedan reglas
     de 3+ fases atrás, las viejas pasan a `lessons_learned_archive.md` y se
     reemplazan por una línea en el índice de archivadas.
   - Si tocaste el stack (`tech_stack.md`) o el `roadmap.md`, actualizá los
     campos correspondientes (fase actual, suite count, archivos nuevos).

4. **¿Feature funcional o solo código?** Si la feature dice "botón se
   habilita al arrancar" o "subprocess se ejecuta": corré el flujo real
   una vez (no mocks). El bug de `config.toml` estuvo oculto 9 fases porque
   nadie probó la carga del archivo físico — solo el código de wiring.
   Si el ambiente no permite probarlo (sin GUI, sin binario), documentá
   claramente qué falta y dejá el test de regresión ready para CI.

5. **Resumen al usuario**: 2-3 líneas de qué quedó hecho + qué validar en
   la próxima sesión (ej. "instalar X para habilitar feature Y"). No más.

**Por qué:** el bug más caro es el que se descubre cuando el usuario ya
corrió la feature en producción. El test de regresión + el run real + la
rotación de memoria son lo único que previene recurrencia. El `config.toml`
falló desde la Fase 0 porque cada sesión asumía "esto ya está probado" —
no lo estaba.

---

## Salvaguarda inamovible: edición de archivos de memoria (PostFase13-s2)

> Incidente 2026-07-30 (sesión 2): durante la rotación de `session_log.md`,
> `Add-Content -Encoding utf8` de PowerShell 5.1 corrompió bytes adyacentes
> con caracteres no-ASCII ya presentes en `session_log_archive.md`. La
> reparación posterior con `[System.IO.File]::ReadAllText` + `IndexOf` +
> truncado borró accidentalmente ~600 líneas de detalle histórico de
> sesiones Fase 2-12b.5 (irrecuperable: `.agent/` está en `.gitignore` por
> diseño, no hay commits/stash que respalden los archivos de memoria).

**Regla Obligatoria — Aplica a TODA edición de archivos bajo
`.agent/memory/`:**

- **NO usar `Add-Content`, `Set-Content`, `Out-File`, ni here-strings de
  PowerShell** sobre archivos `.agent/memory/*.md`. PowerShell 5.1 no
  maneja UTF-8 sin BOM de forma confiable y rompe caracteres no-ASCII
  preexistentes (acentos, eñes, em-dashes).
- **Usar EXCLUSIVAMENTE el tool `edit` (reemplazo puntual) o el tool
  `write` (escritura completa) sobre archivos de memoria.** Ambos
  manejan UTF-8 limpio y preservan contenido preexistente.
- Si necesitás mover contenido entre archivos de memoria (rotación del
  session_log al archive): leer con `read`, añadir con `write` (no
  `Add-Content`).
- Verificar antes de cerrar sesión que `session_log_archive.md`,
  `lessons_learned_archive.md` y `observations_archive.md` no perdieron
  contenido (corrida de `Get-Content $f -Raw | Measure-Object -Character`
  antes y después si hicieron rotación — el delta debe ser aproximado al
  contenido añadido, no un quiebre grande).

**Por qué:** los archivos de memoria son el historial operativo
irrecuperable del proyecto (`.gitignore` por diseño — contenido vivo,
no apto para commits). Cualquier bug de scripting los destruye sin red
de git. Un solo `Add-Content` mal codificado deshace años de notas
arqueológicas. El tool `edit`/`write` es la única vía segura.
