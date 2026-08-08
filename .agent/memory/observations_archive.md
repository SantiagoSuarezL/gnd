# Observaciones — ARCHIVO (resueltas)

> No se lee automáticamente. Solo consulta bajo demanda.

---

## [2026-07-25] Incidente de detección: `x = 1 + 2 + 3` sobrevivió 8 fases

**Qué era:** asignación top-level trivial al final de `src/gnd/network/real_ping_runner.py:352`. Scope módulo-top-level, sin side-effects, sin lectura posterior.

**Por qué no se detectó antes:** introducida en `cf619f1 feat(phase6)`. `ruff F841` solo aplica a locales dentro de funciones — una asignación top-level en un módulo es legal. Black la respetaba (bien formateada). Pytest no la detecta porque no afecta comportamiento.

**Verificación posterior:** Vulture 2.16 agregado como dep dev + whitelist en `[tool.vulture]`. Confirmado: reintroducir la variable → Vulture la reporta (60% confidence). Integrado en `scripts/check.ps1` después de ruff y antes de black/pytest.

**Código muerto REAL adicional detectado por Vulture en la auditoría de Fase 9:**
1. `_dict_to_hop()` en `sqlite_diagnostics_repository.py:118` — helper sin caller.
2. `validate_now()` en `config/__init__.py:100` — sin caller (validación ocurre vía Pydantic).
3. `reload_settings()` en `config/__init__.py:116` — hot-reload sin caller.
4. `Ui.dark_mode` + submodelo `Ui` — declarado pero no consumido (UI es dark fijo).
5. `completed` property en `tracert_parser.py:75` — nadie lee `parsed.completed`.

Todos eliminados.

**Conclusión:** incidente banal (cálculo mental no borrado), no sistemático. Regla de código resultante: ver `lessons_learned.md` Regla de Oro 9.5.