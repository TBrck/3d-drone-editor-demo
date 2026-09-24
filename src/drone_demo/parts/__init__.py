"""Part library.

Importing this package populates the registry in :mod:`.base` as a side
effect of importing each part module.  Any new part module must be added to
the import list below or it will silently vanish from the BOM.
"""

from __future__ import annotations

# Import for side effects: each module registers its PartDef at import time.
from drone_demo.parts import (  # noqa: F401  (side-effect imports)
    arm,
    custom,
    electronics,
    frame,
    hardware,
    landing,
    rotor,
)
from drone_demo.parts.base import Annotation, PartDef, all_parts, get, register

__all__ = ["Annotation", "PartDef", "all_parts", "get", "register"]
