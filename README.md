# Game Network Diagnostics (GND) — Documentación de proyecto

Asistente de diagnóstico de red pre-partida y en-partida para League of Legends (arquitectura extensible a otros juegos). No es un ping tool: interpreta el estado de la red como lo haría un ingeniero de redes senior, y emite un veredicto explicado.

**Target:** Python 3.12+, Windows 11.

---

## Cómo navegar esta documentación

Lee en este orden si es la primera vez que trabajas en el proyecto:

1. **[`PRD.md`](./PRD.md)** — qué se está construyendo y por qué. Problema, usuario, features, no-objetivos, métricas de éxito.
2. **[`ARCHITECTURE.md`](./ARCHITECTURE.md)** — cómo está estructurado el sistema. Capas, módulos, y el modelo de 3 capas de conectividad Riot (Client / LCU / Game Server), que es el elemento distintivo de este proyecto.
3. **[`TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md)** — contratos de datos exactos, protocolos de red, esquema de base de datos, motor de recomendación, thresholds de configuración.
4. **[`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md)** — plan de fases con Definition of Done por fase. Es la guía de ejecución fase por fase.
5. **[`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md)** — estándares de código no negociables (Clean Architecture, SOLID aplicado, DI, testing, checklist de revisión).

## Para trabajar con Opencode en una fase específica

No es necesario cargar los 5 documentos completos para cada tarea. Sugerencia de contexto mínimo por tipo de tarea:

| Tarea | Documentos a cargar |
|---|---|
| Diseñar/discutir un módulo nuevo | `ARCHITECTURE.md` + `ENGINEERING_PRINCIPLES.md` |
| Implementar una fase del plan | `IMPLEMENTATION_PLAN.md` (la fase específica) + `TECHNICAL_SPEC.md` (secciones relevantes) |
| Revisar código existente | `ENGINEERING_PRINCIPLES.md` (checklist §7) |
| Discutir producto/alcance | `PRD.md` |
| Ajustar el motor de recomendación | `TECHNICAL_SPEC.md` §5 |

## El elemento distintivo del proyecto

GND diferencia explícitamente entre:

- La **IP pública de infraestructura Riot** (login/patch, ej. `auth.riotgames.com` → `104.16.119.50` via Cloudflare) — dinámica por CDN, no representa el ping real de partida.
- La **IP del servidor de partida activo** — dinámica, asignada por matchmaking, detectada en tiempo real mediante enumeración de conexiones UDP del proceso del juego (ver `TECHNICAL_SPEC.md` §2.2).

Toda la arquitectura (base de datos, análisis histórico, motor de recomendación) trata estos dos como providers separados para no contaminar el baseline histórico ni las recomendaciones.

## Estado del proyecto

Draft de documentación completo, pendiente de inicio de implementación (Fase 0 de `IMPLEMENTATION_PLAN.md`).

---

## Setup del entorno (Fase 0)

El proyecto usa un entorno virtual `.venv` en la raíz. Ya está excluido de git (ver `.gitignore`).

```powershell
# Windows 11 (entorno target del PRD)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Verificación local (Definition of Done de cada fase)

```powershell
.\scripts\check.ps1
```

Equivale a correr `ruff check .`, `black --check .` y `pytest` en secuencia; detiene la ejecución al primer error.
