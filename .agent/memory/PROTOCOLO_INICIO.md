# PROTOCOLO DE INICIO (pegar al arrancar una sesión nueva)

Antes de arrancar, actualizá tu contexto así — en este orden, parando temprano si ya alcanza:

1. Leé `.agent/memory/INDEX.md` completo (es corto, es el mapa).
2. Leé los archivos marcados "Siempre" en la tabla de INDEX.md:
   `session_log.md`, `lessons_learned.md`, `tech_stack.md`, `roadmap.md`, `observations.md`.
3. NO leas ningún `*_archive.md` todavía. Solo si la tarea que te voy a pedir
   toca directamente un módulo de una fase vieja, buscá (grep/keyword) en el
   archive correspondiente ANTES de tocar ese código — no antes de eso.
3.5. Este repo tiene graphify instalado (grafo de conocimiento del código,
   `graphify-out/graph.json`, hook post-commit/post-checkout activo — se
   reconstruye solo, no hace falta correrlo a mano). Antes de leer o
   grepear archivos de código para entender cómo se conecta algo (qué
   llama a qué, qué depende de qué, dónde vive un concepto), consultá
   primero el grafo en vez de abrir archivos crudos:
   - `graphify query "<pregunta en lenguaje natural>"` para un
     subgrafo acotado a una pregunta.
   - `graphify explain "<NombreDeClaseOFuncion>"` para ver todas las
     conexiones de un nodo puntual.
   - `graphify path "<A>" "<B>"` para trazar cómo se conectan dos cosas.
   - `GRAPH_REPORT.md` (en `graphify-out/`) para una revisión de
     arquitectura general: god nodes, comunidades, conexiones sorprendentes.
   Esto reemplaza grepear/leer archivo por archivo cuando la pregunta es
   sobre relaciones o estructura del código — no reemplaza leer el archivo
   cuando ya sabés cuál es y necesitás el contenido exacto (implementación,
   lógica de negocio, etc.).
4. De `README.md` y `docs/` (PRD.md, ARCHITECTURE.md, TECHNICAL_SPEC.md,
   IMPLEMENTATION_PLAN.md, ENGINEERING_PRINCIPLES.md): NO los releas enteros
   por defecto. Son specs que cambian poco. Regla:
   - Si `roadmap.md` dice que la fase actual es continuación directa de la
     anterior (mismo módulo, sin cambio de arquitectura) → asumí que ya los
     conocés por sesiones previas, no los releas.
   - Si vas a arrancar una fase NUEVA, o si `tech_stack.md`/`roadmap.md`
     mencionan un cambio de arquitectura reciente → releé solo la sección
     relevante de esos docs (grep por el nombre de la fase o el módulo),
     no el archivo entero.
   - Si es la primera vez que trabajás en este repo en esta máquina/sesión
     larga, ahí sí leé todo una vez.
5. Avisame con un resumen de 2-3 líneas de en qué quedamos, no un resumen
   largo — y seguimos con la tarea.

**Por qué:** los 5 archivos "Siempre" ya contienen el resumen comprimido de
todo lo relevante. Los `docs/` son estáticos entre fases; releerlos enteros
cada sesión es gasto de contexto sin informacion nueva la mayoría de las veces.
Graphify cubre la otra mitad: la estructura objetiva del código (qué se
conecta con qué), que ningún resumen narrativo captura y que de otra forma
se reconstruye a fuerza de grep, gastando tokens en cada sesión.

---

## Salvaguarda inamovible: edición de `.agent/memory/*.md` (leer SIEMPRE)

> Incidente 2026-07-30 (sesión 2): `Add-Content` de PowerShell 5.1 corrompió
> `session_log_archive.md` por encoding, y la reparación con
> `[System.IO.File]::ReadAllText`+`IndexOf` borró ~600 líneas de detalle
> histórico de Fase 2-12b.5. Irrecuperable (`.agent/` no está en git).

**Regla:** editar archivos bajo `.agent/memory/` **SÓLO con el tool `edit`
(puntual) o `write` (completo)**. NUNCA `Add-Content`/`Set-Content`/
`Out-File` ni here-strings de PowerShell — corrompen UTF-8 y destruyen
contenido. Detalle completo en `PROTOCOLO_SALIDA.md` (sección Salvaguarda).