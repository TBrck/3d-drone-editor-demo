"""JSON API for reading and editing ``custom_parts.json``.

Every write here re-validates against the *same* predicates
``tests/test_registry.py`` runs (documented, non-empty, snake_case keys, a
mass override on any "purchased" part) -- that suite runs in CI on every
push (see ``.github/workflows/pages.yml``), so a save that would fail it is
rejected here first, before it ever reaches disk.

Deliberately does not try to hot-patch the running process's part registry
(``drone_demo.parts`` registers everything once, at import time, like every
other part module). ``GET`` always re-reads ``custom_parts.json`` from disk,
so the list is never stale; making a saved change actually appear in the
read-only 3D backdrop or the published site needs a real rebuild, which is
exactly what ``POST /api/rebuild`` (a fresh subprocess) is for.
"""

from __future__ import annotations

import os
import subprocess
import sys

from flask import Blueprint, Response, jsonify, request

from drone_demo.cli import ASSET_DIR
from drone_demo.materials import MATERIALS, PROCESSES
from drone_demo.parts import all_parts
from drone_demo.parts.custom import CUSTOM_PARTS_PATH, build_from_shape_spec, load_custom_part_specs
from drone_demo.studio.auth import login_required

bp = Blueprint("api", __name__, url_prefix="/api")


def _existing_keys(exclude: str | None = None) -> set[str]:
    keys = {p.key for p in all_parts()}
    keys |= {s["key"] for s in load_custom_part_specs()}
    keys.discard(exclude)
    return keys


def _validate(spec: dict, *, editing_key: str | None) -> list[dict[str, str]]:
    """Field-tagged errors, empty if the spec is safe to save.

    Order matches the cost of each check: cheap field checks first, the
    real build123d build (which is what actually costs time) last, so a
    typo'd material key fails in microseconds instead of after a solid has
    already been built.
    """
    errors: list[dict[str, str]] = []

    def fail(field: str, message: str) -> None:
        errors.append({"field": field, "message": message})

    key = spec.get("key", "")
    if not key or "__" in key or key != key.lower():
        fail("key", "must be lower_snake_case and not contain '__'")
    elif key in _existing_keys(exclude=editing_key):
        fail("key", f"{key!r} is already in use")

    if spec.get("material_key") not in MATERIALS:
        fail("material_key", f"must be one of {sorted(MATERIALS)}")
    if spec.get("process_key") not in PROCESSES:
        fail("process_key", f"must be one of {sorted(PROCESSES)}")

    if not spec.get("summary"):
        fail("summary", "required -- every part must carry its reasoning")
    if not spec.get("design_notes"):
        fail("design_notes", "at least one note is required")

    if spec.get("material_key") == "cots" and spec.get("mass_override_g") is None:
        fail(
            "mass_override_g",
            "required when material_key is 'cots' -- a purchased part's CAD "
            "volume is a placeholder, so its mass has to come from a vendor figure",
        )

    if not errors:
        try:
            part = build_from_shape_spec(spec["shape"])
        except (ValueError, KeyError) as e:
            fail("shape", str(e))
        else:
            if not part.is_valid:
                fail("shape", "geometry is not a valid solid")
            elif part.volume <= 0:
                fail("shape", "geometry has zero or negative volume")

    return errors


@bp.route("/parts", methods=["GET"])
@login_required
def list_parts():
    return jsonify(load_custom_part_specs())


@bp.route("/parts", methods=["POST"])
@login_required
def create_part():
    spec = request.get_json(force=True) or {}
    errors = _validate(spec, editing_key=None)
    if errors:
        return jsonify({"errors": errors}), 400

    specs = load_custom_part_specs()
    specs.append(spec)
    _write_specs(specs)
    return jsonify(spec), 201


@bp.route("/parts/<key>", methods=["PUT"])
@login_required
def update_part(key: str):
    spec = request.get_json(force=True) or {}
    spec["key"] = key
    errors = _validate(spec, editing_key=key)
    if errors:
        return jsonify({"errors": errors}), 400

    specs = load_custom_part_specs()
    if not any(s["key"] == key for s in specs):
        return jsonify({"errors": [{"field": "key", "message": f"{key!r} not found"}]}), 404
    specs = [spec if s["key"] == key else s for s in specs]
    _write_specs(specs)
    return jsonify(spec)


@bp.route("/parts/<key>", methods=["DELETE"])
@login_required
def delete_part(key: str):
    specs = load_custom_part_specs()
    remaining = [s for s in specs if s["key"] != key]
    if len(remaining) == len(specs):
        return jsonify({"errors": [{"field": "key", "message": f"{key!r} not found"}]}), 404
    _write_specs(remaining)

    # Best-effort cleanup of stale exported files -- export/cad.py and
    # export/drawings.py only ever write for currently-registered parts,
    # never delete for ones that disappear, so a removed custom part would
    # otherwise leave orphaned, still-committed binaries behind.
    for rel in (
        f"downloads/{key}.step", f"downloads/{key}.stl", f"downloads/{key}_flat.dxf",
        f"drawings/{key}.svg",
    ):
        try:
            os.remove(ASSET_DIR / rel)
        except FileNotFoundError:
            pass

    return "", 204


@bp.route("/preview", methods=["POST"])
@login_required
def preview():
    """A one-off GLB of a shape tree, built and tessellated on the spot.

    This is the studio's live preview, and deliberately shares the same
    build123d interpreter and the same mm -> m, Z-up -> Y-up axis
    convention export/gltf.py uses for the published assembly, rather than
    a separate in-browser CSG engine -- there is exactly one thing that
    turns a shape spec into geometry anywhere in this project, so the
    preview can never disagree with what a rebuild will actually produce.

    Returned in the shape's own local frame (axis-fixed, scaled to metres)
    with no placement offset baked in -- the frontend positions the loaded
    mesh at the current placement fields itself, the same way it positions
    the read-only backdrop's instances, so nudging position/rotation
    doesn't need a round trip back here.
    """
    from drone_demo.config import SPEC
    from drone_demo.export.gltf import _AXIS_FIX
    from drone_demo.export.mesh import to_trimesh

    payload = request.get_json(force=True) or {}
    try:
        part = build_from_shape_spec(payload.get("shape", {}))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400

    exp = SPEC.export
    mesh = to_trimesh(part, exp.linear_deflection_mm, exp.angular_deflection_rad)
    world = _AXIS_FIX * exp.gltf_scale
    world[3, 3] = 1.0  # the scale multiply above also scaled the homogeneous row
    mesh.apply_transform(world)
    glb_bytes = mesh.export(file_type="glb")
    return Response(glb_bytes, mimetype="model/gltf-binary")


@bp.route("/rebuild", methods=["POST"])
@login_required
def rebuild():
    """Regenerate drone.glb/manifest.json (fast path -- geometry only, no FEA)."""
    result = subprocess.run(
        [sys.executable, "-m", "drone_demo", "build"],
        capture_output=True, text=True, timeout=300,
    )
    return jsonify({
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    })


def _write_specs(specs: list[dict]) -> None:
    import json

    CUSTOM_PARTS_PATH.write_text(
        json.dumps({"schema_version": "1.0", "parts": specs}, indent=2) + "\n",
        encoding="utf-8",
    )
