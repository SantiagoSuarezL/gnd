"""Capa de orquestacion de diagnostico — ARCHITECTURE.md §2.

No implementa reglas de negocio (== responsabilidad de `analysis/` y
`recommendations/`), solo orquesta los `Protocol` del dominio: ejecuta
pruebas (local, internet, Riot, traceroute, monitoreo continuo) y arma
el `DiagnosticResult` consumido por las capas superiores.

Submodulos:
- `riot`: diagnostico especifico de League of Legends (ActiveGameServerDetector,
  LiveClientApi).
"""

from gnd.diagnostics.riot import ActiveGameServerDetector, LiveClientApi

__all__ = [
    "ActiveGameServerDetector",
    "LiveClientApi",
]
