# ENGINEERING PRINCIPLES — Game Network Diagnostics (GND)

**Versión:** 1.0
**Documentos relacionados:** `ARCHITECTURE.md`, `TECHNICAL_SPEC.md`, `IMPLEMENTATION_PLAN.md`

Este documento es la referencia que Opencode debe seguir al escribir o revisar cualquier línea de código de este proyecto. Ante ambigüedad, este documento prevalece sobre preferencias de estilo personales.

---

## 1. Principios no negociables

1. **Ninguna capa de dominio (`models/`, lógica de `analysis/`, `recommendations/`) importa infraestructura directamente** (`sqlite3`, `psutil`, `subprocess`, sockets). Toda dependencia de infraestructura entra por `Protocol` inyectado.
2. **Todo resultado de red es un valor, no una excepción.** Ver `TECHNICAL_SPEC.md` §7. Una excepción no controlada que llegue a la UI se considera un bug, sin excepción.
3. **Ninguna recomendación se emite sin `explanation`.** Un veredicto sin razonamiento explícito es un bug de producto (viola el principio "never guess, always explain why" del proyecto original).
4. **Type hints estrictos en el 100% del código.** `mypy`/`pyright` en modo estricto (o `ruff` con reglas de tipos activadas) sin `# type: ignore` salvo justificación comentada en línea.
5. **Sin God Objects.** Si una clase supera ~200 líneas o tiene más de una razón para cambiar, se divide. Aplica especialmente a `diagnostics/` y `ui/`, que son los módulos con mayor tendencia a acumular responsabilidades.
6. **Inmutabilidad por defecto.** Modelos de dominio como `@dataclass(frozen=True)`. Mutación solo donde sea estrictamente necesario y esté justificado (ej. acumuladores de estadísticas en construcción).

---

## 2. SOLID aplicado a este proyecto (no genérico)

- **S (Single Responsibility):** `diagnostics/riot/public_endpoint_probe.py` y `diagnostics/riot/active_game_server_detector.py` son archivos/clases separados — nunca un único `RiotDiagnostics` monolítico que haga ambas cosas.
- **O (Open/Closed):** agregar un nuevo provider de Internet (ej. un cuarto DNS público) no debe requerir modificar `analysis/` ni `recommendations/` — solo agregar configuración y un nuevo `ProbeResult.provider`.
- **L (Liskov):** cualquier implementación de `PingRunner` (real, fake, grabada de fixture) debe ser intercambiable sin que el código que la consume note la diferencia.
- **I (Interface Segregation):** `ConnectionInspector` (para detección de servidor de partida) es una interfaz separada de `PingRunner` — un componente que solo necesita pinguear no debe depender de la capacidad de enumerar procesos.
- **D (Dependency Inversion):** `Application` (casos de uso) depende de los `Protocol` definidos en `domain/`, nunca de las clases concretas de `network/` o `database/`. La composición/wiring ocurre en un único punto de entrada (`main.py` o `container.py`), no dispersa.

---

## 3. Dependency Injection — patrón concreto

Usar inyección por constructor explícita, sin framework de DI pesado (no se justifica para este tamaño de proyecto):

```python
class RunFullDiagnostics:
    def __init__(
        self,
        ping_runner: PingRunner,
        traceroute_runner: TracerouteRunner,
        connection_inspector: ConnectionInspector,
        repository: DiagnosticsRepository,
        recommendation_engine: RecommendationEngine,
    ) -> None:
        self._ping_runner = ping_runner
        self._traceroute_runner = traceroute_runner
        self._connection_inspector = connection_inspector
        self._repository = repository
        self._recommendation_engine = recommendation_engine
```

El wiring de qué implementación concreta usar (real vs fake) vive en un único `composition_root` — ni la UI ni los casos de uso deciden qué implementación instanciar.

---

## 4. Testing

- **Pytest** como único framework. `pytest-asyncio` para las partes async.
- Tests de dominio y de motor de recomendación: **sin red, sin disco, sin reloj real** (inyectar `datetime` cuando el resultado dependa de tiempo).
- Tests de infraestructura de red: marcados `@pytest.mark.integration`, excluidos de la corrida rápida por defecto.
- **Cobertura objetivo:** ≥90% en `domain/`, `analysis/`, `recommendations/`. No se exige 90% en `ui/` (los tests de UI tienen menor retorno de inversión en un proyecto de este tamaño) ni en wrappers delgados de `subprocess`.
- Todo bug encontrado en producción/uso real se corrige agregando primero el test que lo reproduce, luego el fix.

---

## 5. Logging

- Logging estructurado (JSON) usando `logging` estándar de Python con un `Formatter` propio — no se introduce una dependencia externa de logging para este tamaño de proyecto salvo que se justifique.
- Todo log de una corrida de diagnóstico incluye: `run_id`, timestamp, componente, nivel, y (si aplica) provider afectado.
- Nunca loguear excepciones silenciosamente — todo `except` que capture una excepción de infraestructura debe loguear con `logger.exception(...)` o justificar explícitamente por qué se ignora.

---

## 6. Convenciones de código

- `ruff` como linter único (reemplaza flake8/isort/pylint). Reglas activas mínimas: `E`, `F`, `I` (imports), `UP` (pyupgrade para Python 3.12), `B` (bugbear).
- `black` para formateo, sin configuración custom de line-length salvo necesidad justificada.
- Nombres de módulos y funciones en inglés (consistencia con el ecosistema Python); comentarios y docstrings pueden estar en español si el proyecto es personal, pero deben ser consistentes — no mezclar idioma dentro del mismo archivo.
- Docstrings en funciones públicas de cada capa (`Application`, `Protocol`s de dominio) explicando el contrato, no la implementación.

---

## 7. Checklist de revisión (usar antes de dar por cerrada cualquier fase de `IMPLEMENTATION_PLAN.md`)

- [ ] ¿Alguna capa de dominio importa infraestructura directamente? → si sí, refactorizar.
- [ ] ¿Algún resultado de red puede lanzar una excepción no controlada hacia la UI? → si sí, envolver en el tipo de resultado correspondiente.
- [ ] ¿Toda recomendación tiene `explanation` no vacío? → si no, es un bug.
- [ ] ¿Hay algún archivo/clase que esté claramente haciendo más de una cosa? → dividir.
- [ ] ¿Los tests nuevos cubren tanto el caso feliz como al menos un caso de error/borde? → si no, agregar antes de continuar.
- [ ] ¿`ruff` y `black` pasan sin excepciones no justificadas?
