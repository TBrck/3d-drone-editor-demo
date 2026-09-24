"""The contract every part module must satisfy.

A "part" here is one manufactured item.  Each part module exposes exactly
one :class:`PartDef`, registered with :func:`register`.  Everything
downstream — the assembly, the BOM, the exporter, the FEA driver and the web
viewer — works only against :class:`PartDef`, never against the geometry
code directly.

Adding a new part therefore means: write one module, decorate one builder,
import it in ``parts/__init__.py``.  Nothing else changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from build123d import Part


@dataclass(frozen=True)
class Annotation:
    """A callout the viewer renders as a hotspot on the 3D model.

    This is where the engineering reasoning lives.  A hiring manager clicking
    a part should learn *why* it looks the way it does, not just what it is.

    ``at_mm`` is a point in the part's own local coordinates; the exporter
    transforms it into assembly coordinates for each instance.
    """

    title: str
    body: str
    at_mm: tuple[float, float, float]
    #: One of "dfm", "load", "interface", "tolerance", "iteration".
    kind: str = "dfm"


@dataclass(frozen=True)
class PartDef:
    """Everything the pipeline needs to know about one manufactured part.

    Attributes
    ----------
    key:
        Stable identifier.  Used as the glTF node name prefix, the manifest
        key and the STEP filename.  ``lower_snake_case``, never renamed once
        published because the web viewer's deep links use it.
    builder:
        Zero-argument callable returning a ``build123d.Part`` positioned in
        the part's own local frame, origin at its natural datum.
    material_key, process_key:
        Keys into :mod:`drone_demo.materials`.
    quantity:
        How many of this part the assembly contains.
    mass_override_g:
        Set only for purchased parts whose CAD is a placeholder solid; the
        vendor mass is used instead of density x volume.
    critical:
        True if the part carries flight loads and must appear in the FEA and
        statics report.
    """

    key: str
    name: str
    builder: Callable[[], Part]
    material_key: str
    process_key: str
    quantity: int = 1
    summary: str = ""
    mass_override_g: float | None = None
    critical: bool = False
    annotations: tuple[Annotation, ...] = field(default_factory=tuple)
    #: Free text shown in the viewer's detail panel, one bullet per entry.
    design_notes: tuple[str, ...] = field(default_factory=tuple)


_REGISTRY: dict[str, PartDef] = {}


def register(part: PartDef) -> PartDef:
    """Add a part to the global registry.

    Raises on a duplicate key, because a silent overwrite would drop a part
    from the BOM without any visible error.
    """
    if part.key in _REGISTRY:
        raise ValueError(f"Duplicate part key {part.key!r}")
    _REGISTRY[part.key] = part
    return part


def get(key: str) -> PartDef:
    try:
        return _REGISTRY[key]
    except KeyError:  # pragma: no cover - programming error
        raise KeyError(f"Unknown part {key!r}. Known: {sorted(_REGISTRY)}") from None


def all_parts() -> tuple[PartDef, ...]:
    """Every registered part, in registration order."""
    return tuple(_REGISTRY.values())
