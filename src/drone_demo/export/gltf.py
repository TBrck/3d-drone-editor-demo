"""Assembly -> a single ``.glb`` the browser can load.

Verified in this environment: ``trimesh.Scene.add_geometry(..., node_name=...)``
round-trips node names through GLB intact, and ``PBRMaterial`` survives the
export. Those two facts are what let the viewer map a click on a triangle
back to a part record.

Two conversions this module owns, and nowhere else does
-------------------------------------------------------
1. **Units.** CAD is millimetres, glTF is metres. Scale by
   ``ExportSettings.gltf_scale`` here.
2. **Up axis.** CAD is Z-up, glTF is Y-up. Apply a -90 deg rotation about X
   here.

Do both by baking them into the scene's root transform, not into the CAD and
not in the viewer. Baking them into the CAD would corrupt the STEP exports;
doing it in the viewer would misplace every annotation.
"""

from __future__ import annotations

import functools
import warnings

import numpy as np
import trimesh

from drone_demo.assembly import Assembly, build_assembly
from drone_demo.config import SPEC
from drone_demo.export.mesh import to_trimesh
from drone_demo.materials import material

#: mm -> m, plus Z-up -> Y-up. Baked into every node's transform here, and
#: nowhere else — see the module docstring for why.
_AXIS_FIX = np.array(
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


@functools.cache
def _part_mesh(part_key: str) -> trimesh.Trimesh:
    """Tessellated mesh for one part type, built once and reused across instances."""
    from drone_demo.parts import get

    part = get(part_key)
    solid = part.builder()
    exp = SPEC.export
    return to_trimesh(solid, exp.linear_deflection_mm, exp.angular_deflection_rad)


def _pbr_material(material_key: str) -> trimesh.visual.material.PBRMaterial:
    mat = material(material_key)
    r = int(mat.colour[1:3], 16) / 255.0
    g = int(mat.colour[3:5], 16) / 255.0
    b = int(mat.colour[5:7], 16) / 255.0
    return trimesh.visual.material.PBRMaterial(
        name=mat.key,
        baseColorFactor=[r, g, b, 1.0],
        metallicFactor=mat.metalness,
        roughnessFactor=mat.roughness,
    )


def build_scene(assembly: Assembly | None = None, explode: float = 0.0) -> trimesh.Scene:
    """Build a ``trimesh.Scene`` of the whole vehicle.

    One node per :class:`~drone_demo.assembly.Instance`, named ``node_id``.
    Geometry is cached per part key and reused across instances — the four
    arms share one tube mesh with four transforms, which cuts the file to
    roughly a third.

    ``explode`` moves every instance along its own ``explode_dir`` by
    ``explode_rank * explode_distance_mm * explode``, matching the formula
    the interactive viewer uses — set to 0 for the assembled state that
    ships as ``drone.glb``.
    """
    if assembly is None:
        assembly = build_assembly()

    scene = trimesh.Scene()
    exp = SPEC.export

    for inst in assembly.instances:
        base_mesh = _part_mesh(inst.part.key)
        mesh = base_mesh.copy()
        mesh.visual = trimesh.visual.TextureVisuals(material=_pbr_material(inst.part.material_key))

        local = np.array(inst.transform)
        if explode > 0.0:
            dist = inst.explode_rank * exp.explode_distance_mm * explode
            dx, dy, dz = inst.explode_dir
            local = local.copy()
            local[0, 3] += dx * dist
            local[1, 3] += dy * dist
            local[2, 3] += dz * dist

        world = _AXIS_FIX @ local * exp.gltf_scale
        world[3, 3] = 1.0  # the scale multiply above also scaled the homogeneous row

        scene.add_geometry(
            mesh,
            node_name=inst.node_id,
            geom_name=f"{inst.part.key}_geom",
            transform=world,
        )

    return scene


def export_glb(out_path: str, assembly: Assembly | None = None) -> dict:
    """Write ``drone.glb`` and return statistics for the manifest.

    Warns loudly if the triangle count exceeds
    ``ExportSettings.triangle_budget`` — a 40 MB glb makes the page useless
    on a phone, and someone opening this link on a phone is a realistic
    scenario worth protecting.
    """
    if assembly is None:
        assembly = build_assembly()

    scene = build_scene(assembly)
    blob = scene.export(file_type="glb")
    with open(out_path, "wb") as f:
        f.write(blob)

    tri_count = sum(len(g.faces) for g in scene.geometry.values())
    if tri_count > SPEC.export.triangle_budget:
        warnings.warn(
            f"scene has {tri_count:,} triangles, over the "
            f"{SPEC.export.triangle_budget:,} budget",
            stacklevel=2,
        )

    bounds = scene.bounds  # metres, post axis-fix and scale
    return {
        "triangles": tri_count,
        "nodes": len(scene.graph.nodes_geometry),
        "bytes": len(blob),
        "bbox_min_m": [float(x) for x in bounds[0]],
        "bbox_max_m": [float(x) for x in bounds[1]],
    }
