# PRD — Game Network Diagnostics (GND)

**Versión:** 1.0
**Autor:** Santiago
**Estado:** Draft para desarrollo (Opencode)
**Documentos relacionados:** `ARCHITECTURE.md`, `TECHNICAL_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `ENGINEERING_PRINCIPLES.md`

---

## 1. Resumen ejecutivo

GND es un asistente de diagnóstico de red pre-partida y en-partida para jugadores competitivos de League of Legends (arquitectura extensible a otros juegos). No es un "ping tool". Es un sistema que **ejecuta diagnósticos, los compara contra una línea base histórica, y emite un veredicto accionable** en lenguaje humano, del mismo modo en que lo haría un ingeniero de redes revisando la conexión de un usuario.

El diferenciador central del producto es que **entiende la diferencia entre la infraestructura pública de Riot (login/patcher/lobby) y el servidor de partida real**, que se asigna dinámicamente por el matchmaking y es la única IP que importa para el ping competitivo.

---

## 2. Problema

Los jugadores competitivos toman decisiones ("¿entro a ranked ahora o espero?") sin información real sobre el estado de su red. Las herramientas existentes (ping tools genéricos, speed tests) reportan números crudos sin:

- Comparación contra el comportamiento histórico normal de la red del usuario.
- Diferenciación entre problema local, problema de ISP, problema de tránsito internacional, o problema específico de Riot.
- Distinción entre la IP de infraestructura pública de Riot y la IP real del servidor de la partida en curso.
- Una recomendación clara y explicada ("por qué") en vez de una tabla de números.

## 3. Objetivo del producto

Construir una aplicación de escritorio (Windows 11, Python 3.12+) que:

1. Ejecute automáticamente una batería de diagnósticos de red con un solo clic.
2. Detecte la IP real del servidor de partida activo (no solo la IP pública de Riot).
3. Compare los resultados contra una base de datos histórica local (SQLite).
4. Analice los resultados con un motor de reglas (y a futuro, explicación por LLM) para producir un veredicto humano y explicado.
5. Presente todo en una UI simple, oscura, sin fricción.

## 4. No-objetivos (Out of Scope v1)

- No es una herramienta de terceros para "sacarle la IP a otro jugador" (uso indebido explícitamente fuera de alcance y no soportado).
- No hace packet capture profundo (Wireshark-level) en v1 — queda como extensión futura opcional.
- No optimiza ni modifica la configuración de red del usuario (no es un "booster de ping"); solo diagnostica y recomienda.
- No soporta Linux/macOS en v1 (Windows 11 únicamente).
- No implementa multi-juego en v1 — arquitectura modular preparada, pero solo LoL implementado.

## 5. Usuario objetivo

Jugador competitivo individual (Santiago), técnicamente capaz, que quiere entender *por qué* su conexión está mal antes de una partida ranked, no solo *que* está mal.

## 6. Historias de usuario

1. **Como jugador**, quiero presionar un botón y en segundos saber si es seguro entrar a ranked, para no arriesgar una partida con mala conexión.
2. **Como jugador**, quiero saber si el problema es mi red local, mi ISP, o Riot específicamente, para saber si esperar tiene sentido o no.
3. **Como jugador**, quiero que la app sepa distinguir la IP del cliente/lobby de la IP real de mi partida en curso, para que el diagnóstico "en partida" sea preciso y no genérico.
4. **Como jugador**, quiero ver mi historial de latencia por hora/día, para saber cuáles son mis mejores horarios para jugar competitivo.
5. **Como jugador**, quiero que la app nunca crashee por un router que bloquea ICMP, y que interprete eso correctamente (no como "host caído").
6. **Como jugador**, quiero poder comparar mi ruta con y sin Cloudflare WARP activado, para decidir si dejarlo prendido.

## 7. Features (resumen — detalle técnico en TECHNICAL_SPEC.md)

### Must-have (v1)
- Diagnóstico de red local (gateway): latencia avg/min/max, pérdida de paquetes, jitter.
- Diagnóstico de salud de Internet: Google DNS, Cloudflare, Quad9.
- Diagnóstico Riot: infraestructura pública configurable + **detección de servidor de partida activo**.
- Traceroute automático con identificación del hop responsable del incremento de latencia.
- Monitoreo continuo de ruta (estilo WinMTR) con almacenamiento de resultados.
- Base de datos histórica (SQLite) con todos los campos definidos en TECHNICAL_SPEC.md.
- Motor de recomendación basado en reglas (ver sección de reglas en TECHNICAL_SPEC.md).
- UI oscura, mínima, con las 5 secciones: Current Status, Network Tests, Route Analysis, Historical Comparison, Recommendations.
- Manejo de errores robusto: ICMP bloqueado, host inalcanzable, timeouts — nunca debe verse como "excepción no controlada".
- Logging estructurado de cada ejecución.
- Configuración vía archivo de settings (targets, ping count, timeouts, thresholds, dark mode, path de DB).

### Should-have (v1.1)
- Score de calidad de red 0–100.
- Comparación automática con/sin WARP.
- Gráficos: latencia en el tiempo, pérdida histórica, Cloudflare vs Google, latencia Riot histórica, mejores horas para jugar.
- Notificaciones de escritorio.
- Detección de Wi-Fi vs Ethernet e intensidad de señal.
- Medición de tiempo de resolución DNS por separado.

### Nice-to-have (futuro)
- Speed test bajo demanda (nunca automático, nunca bloqueante).
- Exportar a PDF/Markdown.
- Reportes semanales/mensuales automáticos.
- Explicación en lenguaje natural vía LLM (post-análisis, no reemplaza el motor de reglas determinista).
- Soporte multi-juego (Valorant, CS2, Minecraft, Fortnite, Rocket League, Apex).
- Packet capture opcional para detección de servidor más robusta.

## 8. Métricas de éxito

- El usuario puede tomar la decisión "jugar / esperar" en menos de 15 segundos desde que abre la app.
- 0 crashes por hosts que bloquean ICMP en 100 ejecuciones consecutivas.
- La detección de servidor de partida identifica correctamente la IP real (UDP, proceso del juego) en >95% de los casos durante una partida activa.
- El motor de recomendación nunca emite "todo bien" cuando hay >2% de pérdida de paquetes o jitter >30ms sostenido (falsos negativos = 0 tolerados).

## 9. Riesgos y supuestos

- **Riesgo:** Riot puede cambiar su infraestructura de red o bloquear detección vía `psutil`/enumeración de conexiones. Mitigación: arquitectura desacoplada (ver `ARCHITECTURE.md`) que permite reemplazar el detector sin tocar el resto del sistema.
- **Riesgo:** ICMP bloqueado por firewalls/routers intermedios genera falsos "host caído". Mitigación: tratamiento explícito documentado en `TECHNICAL_SPEC.md` §Error Handling.
- **Supuesto:** El usuario ejecuta la app con privilegios suficientes para enumerar conexiones de otros procesos (puede requerir modo administrador en Windows para ciertas APIs).
