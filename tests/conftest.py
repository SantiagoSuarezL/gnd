"""Configuracion global de pytest.

Provee helpers de fixtures (no pytest fixtures en sentido monkeypatch,
sino utilidades) para cargar los outputs de `ping` y `tracert` grabados
como texto en `tests/fixtures/`, para los tests unitarios de parsing Fase 2
y Fase 7.
"""

from pathlib import Path

PING_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ping_outputs"
TRACERT_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "tracert_outputs"


def load_fixture(name: str) -> str:
    """Lee un fixture de output de `ping` por nombre (sin extension)."""
    return (PING_FIXTURES_DIR / f"{name}.txt").read_text(encoding="utf-8")


def load_tracert_fixture(name: str) -> str:
    """Lee un fixture de output de `tracert` por nombre (sin extension).

    Ver Fase 7, IMPLEMENTATION_PLAN.md: los fixtures se graban con el output
    real de `tracert` (Windows, EN y ES) para tests deterministas sin red.
    """
    return (TRACERT_FIXTURES_DIR / f"{name}.txt").read_text(encoding="utf-8")
