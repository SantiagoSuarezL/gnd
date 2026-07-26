"""Caso de uso RunFullDiagnostics — orquesta una corrida completa.

Application layer de ARCHITECTURE.md §2. Consume los Protocol del
dominio (PingRunner, TracerouteRunner, ConnectionInspector,
DiagnosticsRepository) y los orquesta segun el flujo de ARCHITECTURE.md
§5 (ejecucion completa en un clic).

EP §3 (DI): todas las dependencias entran por constructor. El wiring de
qué implementacion concreta usar (real vs fake) vive en
`composition_root` — ni este caso de uso ni la UI deciden.

El caso de uso NO conoce tkinter, ni sqlite3, ni subprocess. Solo conoce
modelos de dominio y Protocol. Esto lo hace testeable con fakes sin red
ni disco (EP §4).

Flujo (ARCHITECTURE.md §5):
    1. diagnostics/local        -> gateway ping
    2. diagnostics/internet     -> Google, Cloudflare, Quad9
    3. diagnostics/riot          -> publico + deteccion de game server
    4. diagnostics/traceroute   -> para cada target relevante
    5. analysis/baseline         -> compara contra histórico (por provider)
    6. recommendations/engine    -> aplica reglas -> Recommendation
    7. database/repository       -> persiste el run completo
"""
