"""Studio-authored parts: simple primitives + booleans, driven by JSON.

Every hand-written part module in this package pairs one builder function
with one ``register(PartDef(...))`` call, importable for its side effect.
This module does the same thing for a *list* of parts loaded from
``custom_parts.json`` instead of a single hardcoded builder — the parts &
assembly studio (``python -m drone_demo studio``) writes that file, but
nothing here cares whether an entry came from the studio's UI or a hand
edit: both go through the exact same ``build_from_shape_spec`` interpreter,
which is the whole point (see docs/plans for the "studio and code should
produce the same result" requirement this satisfies).

Scope is deliberately narrow: box/cylinder/sphere plus union/subtract/
intersect and rigid transforms. Anything needing a fillet, a loft, a
chamfer or a sweep stays a hand-written ``BuildPart`` function in one of the
sibling modules -- this interpreter does not attempt to replace that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build123d import Align, Box, Cylinder, Location, Part, Sphere

from drone_demo.parts.base import PartDef, register

#: Bumped if the shape-tree JSON shape changes incompatibly. Mirrors
#: manifest.py's meta.schema_version gating pattern.
SCHEMA_VERSION_MAJOR = "1"

CUSTOM_PARTS_PATH = Path(__file__).resolve().parent.parent / "custom_parts.json"

_PRIMITIVE_BUILDERS = {
    "box": lambda n: Box(
        n["length_mm"], n["width_mm"], n["height_mm"],
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ),
    "cylinder": lambda n: Cylinder(
        n["radius_mm"], n["height_mm"],
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ),
    "sphere": lambda n: Sphere(
        n["radius_mm"],
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ),
}

#: Each combiner takes (accumulated_shape, next_child_shape) -> new_shape.
_BOOLEAN_OPS = {
    "union": lambda a, b: a + b,
    "subtract": lambda a, b: a - b,
    "intersect": lambda a, b: a & b,
}


def _node_location(node: dict[str, Any]) -> Location:
    """The optional rigid transform on any shape-tree node.

    Intrinsic XYZ Euler order, degrees -- build123d's ``Location(position,
    orientation)`` default, which matches three.js's default ``Euler``
    order ``'XYZ'``. This is deliberate: the studio never serialises a raw
    matrix (three.js is column-major, this project's other matrices are
    row-major -- see assembly.py's compose() docstring for why that mismatch
    is worth avoiding), it only ever sends position + rotation, and this is
    the one place both sides agree on what those numbers mean.
    """
    t = node.get("transform") or {}
    position = tuple(t.get("translate_mm", (0.0, 0.0, 0.0)))
    rotation = tuple(t.get("rotate_deg", (0.0, 0.0, 0.0)))
    return Location(position, rotation)


def build_from_shape_spec(node: dict[str, Any]) -> Part:
    """Recursively interpret one shape-tree node into a build123d ``Part``.

    Raises ``ValueError`` (not a silent bad result) whenever a boolean op
    doesn't produce exactly one solid -- an empty result from a boolean
    with no real overlap, or a split result from shapes that only touch
    rather than genuinely intersect in 3D. This project has already hit
    the "merely tangent, not overlapping" version of this failure by hand
    in parts/landing.py and parts/rotor.py; this is the same rule, just
    enforced automatically here instead of relying on the author noticing.
    """
    op = node.get("op")
    if op in _PRIMITIVE_BUILDERS:
        shape = _PRIMITIVE_BUILDERS[op](node)
    elif op in _BOOLEAN_OPS:
        children = node.get("children") or []
        if len(children) < 2:
            raise ValueError(f"{op!r} needs at least 2 children, got {len(children)}")
        shape = build_from_shape_spec(children[0])
        for child in children[1:]:
            before_volume = shape.volume
            combined = _BOOLEAN_OPS[op](shape, build_from_shape_spec(child))
            solids = combined.solids() if combined is not None else []
            if len(solids) == 0:
                raise ValueError(
                    f"{op!r} produced no material -- the shapes do not overlap. "
                    "Booleans need genuine 3D overlap, not just touching faces "
                    "(see parts/landing.py for the same rule elsewhere in this "
                    "codebase)."
                )
            if len(solids) > 1:
                raise ValueError(
                    f"{op!r} produced {len(solids)} disjoint solids instead of "
                    "one -- the shapes are tangent rather than truly overlapping. "
                    "Move one of them so it genuinely overlaps the other, even "
                    "by a fraction of a millimetre."
                )
            if op == "subtract" and combined.volume == before_volume:
                raise ValueError(
                    "subtract removed nothing -- the cutting shape doesn't "
                    "overlap the base. Check its position."
                )
            shape = combined
    else:
        raise ValueError(f"unknown shape op {op!r}")

    return _node_location(node) * shape


def load_custom_part_specs(path: Path = CUSTOM_PARTS_PATH) -> list[dict[str, Any]]:
    """Every studio-authored part definition, or ``[]`` if none exist yet.

    A missing file is not an error -- it just means no custom parts have
    been created yet, the same way an empty ``custom_parts.json`` would be.
    """
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    major = str(data.get("schema_version", "0")).split(".")[0]
    if major != SCHEMA_VERSION_MAJOR:
        raise ValueError(
            f"{path} schema {data.get('schema_version')!r} is not supported "
            f"(expected major version {SCHEMA_VERSION_MAJOR!r})"
        )
    return data.get("parts", [])


def _register_from_json() -> None:
    for spec in load_custom_part_specs():
        register(
            PartDef(
                key=spec["key"],
                name=spec["name"],
                builder=lambda spec=spec: build_from_shape_spec(spec["shape"]),
                material_key=spec["material_key"],
                process_key=spec["process_key"],
                quantity=spec.get("quantity", 1),
                summary=spec.get("summary", ""),
                mass_override_g=spec.get("mass_override_g"),
                critical=spec.get("critical", False),
                design_notes=tuple(spec.get("design_notes", ())),
            )
        )


_register_from_json()
