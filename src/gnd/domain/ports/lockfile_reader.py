"""Puerto ``LockfileReader`` — descubre y parsea el lockfile de LoL.

Fase 14.0a. TECHNICAL_SPEC.md §2.2. El cliente ``LeagueClientUx.exe``
escribe un archivo ``lockfile`` (5 campos separados por ``:``) en su
directorio de instalación. Para autenticar contra la LCU API local
necesitamos ``port`` + ``password`` de ese archivo.

Interface Segregation (ENGINEERING_PRINCIPLES.md §2.I): el puerto NO
expone ``read_path(str)`` porque "saber dónde buscar el lockfile" es
responsabilidad del adapter, no del caller del dominio. El caller
pide "dame las credenciales" y el adapter resuelve búsqueda + parseo
+ validación. Esto permite que el adapter real (sub-fase 14.0b)
cambie estrategia de discovery (registry Windows, path config,
glob en directorio default) sin tocar el dominio.

EP §1.2 (igual que todos los puertos del dominio): el adapter NUNCA
lanza excepciones al caller. Si el lockfile no existe (LoL no
corriendo), si el path config es inválido, o si el contenido no
parsea, el adapter devuelve ``None`` con log estructurado
(``event="lockfile.read.skip"`` + ``reason=...``). El caller decide
el fallback — en 14.0d eso es caer al ``ConnectionInspector`` viejo.

Implementaciones:
- ``network/lockfile_discovery.py`` (sub-fase 14.0b): adapter real
  con búsqueda en paths configurables + parsing defensivo.
- ``domain/fakes/fake_lockfile_reader.py`` (14.0a): programable para
  tests del cascada en ``LeagueOfLegendsModule.detect_active_server``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gnd.models.lockfile_data import LockfileData


@runtime_checkable
class LockfileReader(Protocol):
    """Descubre y parsea el ``lockfile`` del cliente de LoL.

    Contrato:
    - No lanza excepciones (EP §1.2). Cualquier fallo
      (file not found, parse error, permission denied) se traduce a
      ``None`` con log estructurado en el adapter.
    - Devuelve ``LockfileData`` ya validado si el archivo existe y
      parsea — el caller nunca recibe un VO degenerado.
    - No cachea: cada llamada relee el archivo (el cliente puede
      reiniciarse entre dos corridas, cambiando port/password).
      Performance no es crítica — se llama una vez por diagnóstico.
    """

    def read(self) -> LockfileData | None:
        """Lee el ``lockfile`` y devuelve credenciales, o ``None`` si no disponible.

        Razones típicas para ``None``:
        - LoL no corriendo (archivo no existe).
        - Path de búsqueda configurado pero inexistente.
        - Archivo existe pero no parsea (formato cambiando en un patch).
        - Permisos insuficientes para leer el path.
        """
        ...
