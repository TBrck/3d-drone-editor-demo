"""BREP -> triangles. Shared by the glTF exporter and the FEA overlay.

Verified in this environment::

    verts, tris = part.tessellate(tolerance=0.06, angular_tolerance=0.25)
    # verts: list[build123d.Vector]   tris: list[tuple[int, int, int]]

Two things about that output are worth knowing before writing this module:

1. ``tessellate`` emits vertices per face, so the seams between faces carry
   duplicate coincident vertices and the mesh reports as non-watertight.
   Call ``trimesh.Trimesh.merge_vertices()`` afterwards. It typically drops
   30-50 % of the vertices and is what makes the smooth-shading normals come
   out right across a fillet.

2. ``tolerance`` is a chord height in mm and dominates both file size and
   how round a 16 mm tube looks. 0.06 mm is the tuned value; do not lower it
   without checking the triangle count against
   ``ExportSettings.triangle_budget``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import trimesh

if TYPE_CHECKING:  # pragma: no cover
    from build123d import Part


def to_trimesh(part: Part, tolerance_mm: float, angular_tolerance: float) -> trimesh.Trimesh:
    """Tessellate a solid into a merged, welded triangle mesh in millimetres."""
    verts, tris = part.tessellate(tolerance=tolerance_mm, angular_tolerance=angular_tolerance)
    v = np.array([(p.X, p.Y, p.Z) for p in verts], dtype=np.float64)
    f = np.array(tris, dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
    mesh.merge_vertices()
    mesh.fix_normals()
    return mesh


def triangle_count(meshes: dict[str, trimesh.Trimesh]) -> int:
    """Total triangles across the scene. Compared against the budget."""
    return sum(len(m.faces) for m in meshes.values())
