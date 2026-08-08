# Roadmap — Game Network Diagnostics (GND)

## Estado Actual

> **Proyecto en pausa (última sesión 2026-08-02):** empaquetado Windows
> completado — `launch_gnd.vbs` (launcher WSH sin cmd) +
> `scripts/install_shortcut.ps1` (acceso directo escritorio) + helper
> `CREATE_NO_WINDOW` (`src/gnd/network/_subprocess_helpers.py`) aplicado
> a los 5 adapters reales (fix terminales cmd visibles desde pythonw.exe).
> Suite: 1007 unit + 17 integration, ruff+black+vulture limpio. 4 commits
> locales SIN pushear. Ver `session_log.md` (Post-Fase 14.0a).
>
> **Fase 14.0a COMPLETADA (2026-07-30):** VOs + Protocols + Fakes
> para detección de IP real del servidor de LoL vía lockfile+LCU.
> `GameflowSession`, `LockfileData`, `LockfileReader`, `LcuClient`
> y sus fakes. `ActiveGameServerInfo` extendido con `precision_tier`
> + `region_tag` (backwards-compat). 50 tests nuevos → 1000 unit.
> Próxima sub-fase: 14.0b (adapter real lockfile). Ver `session_log.md`
> (14.0a) y `lessons_learned.md` Regla 14.0a.1 (DNS regional:
> solo NA1/EUW1 Riot-direct, región_edge pausado al futuro 14.0b).
> Observación abierta (no bloqueante): ponderación DNS genéricos
> bajo VPN en `observations.md`.

- ✅ **Fase 0** — Setup del proyecto (estructura, pyproject.toml, .venv, CI local, README, config/ Pydantic Settings)
- ✅ **Fase 1** — Modelos de dominio + Protocolos + Fakes in-memory (100% cobertura models/, 57 tests)
- ✅ **Fase 2** — Capa de red real: `RealPingRunner` + parser multiplataforma + fallback TCP SYN. 95 unit + 7 integration. Aprobada tras evidencia empírica Windows. (IP legacy de Riot documentada en lessons_learned_archive.md #2.7)
- ✅ **Fase 3** — Base de datos y persistencia: schema SQLite, `DiagnosticsRepository`, migraciones, round-trip completo.
- ✅ **Fase 4** — Análisis histórico y Network Score: baseline por provider, score ponderado 35/25/20/15/5 con redistribución (ver tech_stack.md #2).
- ✅ **Fase 5** — Motor de recomendación: 7 reglas + 2 constraints, 60 tests del engine.
- ✅ **Fase 6** — Detección de servidor de partida activo (Riot) — **COMPLETADA (alcance v1 ajustado, proxy riot_public documentado en tech_stack.md #12)**
- ✅ **Fase 7** — Traceroute y hop culpable: parser dual EN/ES, `detect_culprit_hop()`. 66 tests nuevos.
- ✅ **Fase 8** — Monitoreo continuo (estilo WinMTR) — **COMPLETADA**. 90 tests nuevos, 426 total.
- ✅ **Fase 9** — UI (5 secciones) — **COMPLETADA**. Fix threading SQLite + performance 129s→14.5s + Historical Comparison real + fix motor de recomendación (anomalías de baseline). 463 unit + 17 integration.
- ✅ **Fase 10** — Visualización (5 gráficos PRD §10) — **COMPLETADA**. matplotlib embebido en tkinter via FigureCanvasTkAgg. 5 gráficos puros: latencia en el tiempo, packet loss histórico, Cloudflare vs Google, latencia Riot histórica, mejores horas. Auto-zoom del eje Y en packet_loss (Regla 10.5). DB temporal en todos los tests/scripts. 497 unit + 17 integration.
- ✅ **Fase 11** — Logging estructurado JSON — **COMPLETADA**. `src/gnd/logging/` (JsonFormatter + RunContextAdapter + configure_logging). FileHandler JSONL diario `logs/gnd_YYYYMMDD.jsonl` + StreamHandler stderr. `RunFullDiagnostics.execute()` emite eventos `run.start`/`run.finish` + `stage.start`/`stage.finish` para 6 etapas con `run_id` inyectado por adapter. `provider` en `extra` de logs de ping/traceroute. Limitaciones v1 documentadas (no rotación medianoche, sin retención). 520 unit + 17 integration, ruff+black+vulture limpio.
- ✅ **Fase 12a** — Features locales post-v1 — **COMPLETADA**. 12a.1 rotación+retención JSONL, 12a.2 DNS timing serial, 12a.3 Wi-Fi/Ethernet (verificado in-vivo Windows), 12a.4 IPv6 opt-in (verificación empírica Windows real). Detalle de decisiones: ver `session_log.md` / `lessons_learned.md` (Reglas 12a.1-12a.4.3). 596 unit + 17 integration, ruff+black+vulture limpio.
- ✅ **Fase 12b** — Comparativa, reportes y automatización — **COMPLETADA**. 12b.1 Export Markdown completada (renderer funcion pura sobre `DiagnosticRun` + botón "Export Markdown" en UI top bar + filedialog + logging eventos export.start/finish/error). 12b.2 Notificaciones de escritorio (plyer) completada: `notifications/` paquete (PlyerDesktopNotifier adapter con import deferido + build_run_notification formatter pura), VO `DesktopNotification`, Protocol `DesktopNotifier` + fake, wiring via `build_notifier()`, integración en `_apply_run` con filtrado `notify_only_on_issues`, logging eventos `notification.start`/`finish`/`error`/`skip`. 12b.3 Reportes semanales/mensuales automáticos completada: `reports/` paquete (compose_period_report función pura + ReportsScheduler con threading.Timer), VO `ReportConfig`, Protocol `RunHistoryReader` + `SqliteRunHistoryReader` (lectura segregada del repo de escritura, bulk reconstruction, half-open range), wiring via `build_report_pipeline()`, integración opcional en MainWindow con `close()` hook para detener el scheduler. 12b.4 Comparación con/sin Cloudflare WARP completada: `warp_controller/` Protocol + `RealWarpController` (warp-cli subprocess, import diferido Regla 12b.2.1) + `FakeWarpController`. `WarpComparisonUseCase` orquesta 2 runs (WARP off → WARP on → restore estado original), computa deltas por provider y veredicto agregado. Config `WarpComparison`, wiring condicional, UI: botón + pestaña WARP Compare. 741 unit + 17 integration, ruff+black+vulture limpio. Detalle en `session_log.md` (Reglas 12b.3.1-12b.3.2, 12b.4.1).

---

## Próximas Fases (pendientes en orden estricto)

- [x] **Fase 12** — Features avanzadas post-v1 — **COMPLETADA Y CERRADA** (12a + 12b validadas in-vivo sesión 4)
  - ✅ **12a.1** TimedRotatingFileHandler (rotación a medianoche + retención)
  - ✅ **12a.2** DNS timing (medición de resolución DNS como métrica independiente)
  - ✅ **12a.3** Wi-Fi/Ethernet (detección de interfaz de red activa)
  - ✅ **12a.4** IPv6 (opt-in: modelos + protocols + fakes + flags en runners + schema migration v3 + persistence + duplicación specs v6 en orquestador + composition_root wiring + tests + verificación empírica Windows real)
    - [x] **12b** Comparativa, reportes y automatización — **CERRADA** (validación in-vivo sesión 4)
      - ✅ **12b.1** Export Markdown (`export/markdown_renderer.py` + botón UI)
      - ✅ **12b.2** Notificaciones de escritorio (plyer)
      - ✅ **12b.3** Reportes semanales/mensuales automáticos (reusa 12b.1)
      - ✅ **12b.4** Comparación con/sin Cloudflare WARP (`warp-cli` subprocess) — **validación in-vivo aprobada 2026-07-30 (sesión 4)**: restore modo+protocolo fiel, columna FAILED funcional, race condition resuelta. Ver `session_log.md` (sesión 4) y Reglas 12b.4.3-4.5.
      - ✅ **12b.5** Speed test bajo demanda (`ookla-speedtest` subprocess) — COMPLETADA. Modelos + Protocol + Fake + Real adapter + UseCase + Controller + Section + config + wiring + UI + 48 tests. 843 unit + 17 integration, ruff+black+vulture limpios.

- [x] **Fase 13** — Extensibilidad multi-juego (`GameDiagnosticsModule` Protocol) — **COMPLETADA**. Protocol + VO `GameEndpoint` (host+provider+family). `LeagueOfLegendsModule` (adapter sobre lógica Riot, reusa `ConnectionInspector`) + `ValorantModule` (provider `valorant_public`, process `VALORANT-Win64-Shipping.exe`). `RunFullDiagnostics` kwarg `game_module` opcional (backwards-compat: None = path Riot hardcodeado). Config `game_detection.active_game`. Builder `build_game_module`. DoD validado (3 tests estáticos blindan que `analysis/`/`recommendations/`/`database/` no mencionan "valorant"). 53 tests nuevos. 896 unit + 17 integration, ruff+black+vulture limpio.

---

## Próximas Fases (pendientes en orden estricto)

- [ ] **Fase 14** — Precisión de medición para LoL: detección de IP real del server de partida vía lockfile+LCU
  - [x] **14.0a** Protocols + VOs + Fakes — **COMPLETADA** (2026-07-30). `models/gameflow_session.py` (VO `GameflowSession`), `models/lockfile_data.py` (VO `LockfileData` + classmethod `parse`), `domain/ports/lockfile_reader.py` (Protocol), `domain/ports/lcu_client.py` (Protocol), + 2 Fakes. `ActiveGameServerInfo` extendido con `precision_tier` + `region_tag` (backwards-compat). 50 tests nuevos → 1000 unit + 17 integration. ruff+black+vulture limpio. Investigación previa + verificación DNS empírica documentada en `lessons_learned.md` Regla 14.0a.1 (DNS regional: solo NA1/EUW1 Riot-direct, resto CF-anycast/NXDOMAIN → tier `regional_edge` pausado al futuro 14.0b). Decisión alcance: solo `exact_ip` (Opción 3) — ver `session_log.md` (14.0a).
  - [ ] **14.0b** Adapter real `network/lockfile_discovery.py` — búsqueda de path configurable + parseo defensivo, degrada silenciosamente con log si LoL no corriendo.
  - [ ] **14.0c** Adapter real `network/lcu_client_http.py` — `urllib.request` stdlib (sin `requests` dep), Basic auth `riot:PASSWORD`, `verify=False` self-signed, timeout 2s, parseo JSON defensivo.
  - [ ] **14.0d** Integración en `LeagueOfLegendsModule.detect_active_server` — cascada: lockfile → LCU → si serverIp → tier=exact_ip, sino fallback inspector actual. Log eventos estructurados.
  - [ ] **14.0e** DB schema v4 (ALTER TABLE `active_game_servers` ADD COLUMN `precision_tier`/`region_tag`, idempotente vía PRAGMA, Regla 39) + `config.lcu_*` (opt-in default False, paths búsqueda, timeout) + `composition_root` `build_game_module` extendido.
  - [ ] **14.0f** Integración en `RunFullDiagnostics` — specs de probe Riot dinámicas por `precision_tier`; provider sigue siendo `riot_game_server` (no rompe baselines). UI + explanation honestos en recommendation engine.
  - [ ] **14.0g** Documentación (TECHNICAL_SPEC.md §2.2 v2 + ARCHITECTURE.md), lesson 14.0a.1 final.
  - [ ] **14.0h** Validación in-vivo (no bloqueante para cerrar 14.0): LoL corriendo con partida activa → confirmar `gameClient.serverIp` aparece y el tier `exact_ip` despacha un ping correcto. Pregunta 4 del plan (TCP SYN a 443 sobre game server UDP) revisitada con evidencia empírica aquí.

---

## Pendientes Críticos Detectados

- [x] **Python 3.12 vs 3.13** — Ya resuelto y fijado en `pyproject.toml` (`requires-python = ">=3.12"`, `target-version = "py312"`). Ver tech_stack.md.
- [x] **Wiring DI (Composition Root)** — Resuelto Fase 2+, ver `composition_root.py`.
- [x] **Configuración Pydantic Settings** — Resuelto Fase 0 (+ fix `config.toml` post-Fase 13 sesión 1 con `TomlConfigSettingsSource`), ver `config/`.
- [ ] **Lockfile League of Legends** — Lectura para LCU API (TECHNICAL_SPEC.md §2.2 nota) — postergado a Fase 14+; no hubo hook real de LCU en Fase 13 (sólo se reusa `ConnectionInspector` existente, no se accede al live client).
- [x] **Retención/limpieza de logs JSONL** (Fase 11 → 12a.1) — Resuelto con `TimedRotatingFileHandler(when='midnight', backupCount=retention_days)`. Rotación a medianoche + retención automática de 30 días.