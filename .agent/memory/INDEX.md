# INDEX — .agent/memory/

> Este archivo se lee SIEMPRE, primero y completo (es chico a propósito).
> Los demás archivos activos se leen completos salvo que este índice diga
> lo contrario. Los archivos `*_archive.md` NUNCA se leen completos — se
> consultan con grep/búsqueda de palabra clave solo si la tarea actual
> toca esa fase vieja.

> **AVISO PERMANENTE — leído antes de cualquier edición de memoria:**
> Editar archivos bajo `.agent/memory/` **SÓLO con el tool `edit`
> (puntual) o `write` (completo)**. NUNCA `Add-Content`/`Set-Content`/
> `Out-File` de PowerShell — corrompen UTF-8 y destruyen contenido
> (incidente 2026-07-30 sesión 2: pérdida irreversible de ~600 líneas
> del session_log_archive). Detalle en `PROTOCOLO_SALIDA.md`.

## Estado del proyecto

**Fase actual:** Proyecto en pausa (última sesión 2026-08-02: empaquetado Windows — `launch_gnd.vbs` + `scripts/install_shortcut.ps1` + acceso directo escritorio + helper `CREATE_NO_WINDOW` en `src/gnd/network/_subprocess_helpers.py` aplicado a los 5 adapters reales). Fase 14.0a COMPLETADA (VOs + Protocols + Fakes para detección de IP real LoL vía lockfile+LCU — detalle en `session_log_archive.md`). 4 commits locales SIN pushear.
**Próxima fase:** 14.0b (adapter real `network/lockfile_discovery.py`).
**Suite:** 1007 unit + 17 integration, ruff+black+vulture limpio (1 flake tkinter 12b.4.2 conocido, pasa aislado).

## Qué leer y cuándo

| Archivo | Se lee | Contiene |
|---|---|---|
| `INDEX.md` (este) | Siempre, primero | Estado + mapa de dónde está cada cosa |
| `session_log.md` | Siempre | Última sesión en detalle + historial comprimido (1 línea/sesión) |
| `lessons_learned.md` | Siempre | Reglas de Oro de Fases 12b.2-12b.3 + índice de lo archivado |
| `tech_stack.md` | Siempre | Stack, arquitectura, 45 Protocolos Críticos (cortos, con referencia) |
| `roadmap.md` | Siempre | Estado de fases + pendientes críticos |
| `observations.md` | Siempre (es chico) | Observaciones de red en curso, no resueltas |
| `session_log_archive.md` | Solo bajo demanda | Detalle de sesiones archivadas; **parcialmente reconstruido** post-incidente 2026-07-30 sesión 2 (~600 líneas perdidas de Fase 2-12b.5, ver aviso al final del propio archivo). Contiene sesión Post-Fase 13 sesión 1 íntegra + Fase 14.0a íntegra. |
| `lessons_learned_archive.md` | Solo bajo demanda | Reglas de Oro completas Fases 1-9 + 12a + 12b.1 |
| `observations_archive.md` | Solo bajo demanda | Observaciones ya resueltas (ej. incidente Vulture) |

**Regla para vos (agente):** si la tarea de hoy es sobre Fase 12b.2-12b.3, con los 6 archivos "Siempre" alcanza. Solo abrí un `*_archive.md` si la tarea toca directamente un módulo de una fase vieja (ej. "tocar el parser de tracert" → grep `lessons_learned_archive.md` por "tracert" o "7.1/7.2").

## Documentación externa del proyecto (docs/, README.md)

Estos son specs, no logs — cambian poco entre sesiones. **No los releas enteros cada vez.**
Ver PROTOCOLO_INICIO.md para el criterio de cuándo sí ameritan lectura completa.
