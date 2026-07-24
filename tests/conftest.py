"""Configuracion global de pytest.

Provee helpers de fixtures (no pytest fixtures en sentido monkeypatch,
sino utilidades) para cargar los outputs de `ping` grabados como texto en
`tests/fixtures/ping_outputs/`, para los tests unitarios de parsingFase 2.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ping_outputs"


def load_fixture(name: str) -> str:
    """Lee un fixture de output de `ping` por nombre (sin extension)."""
    return (FIXTURES_DIR / f"{name}.txt").read_text(encoding="utf-8")
