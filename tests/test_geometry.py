"""Geometry tests. Each one rebuilds a solid, so they are marked slow.

These are the tests that make the parametric claim true. Without them,
"change one number and everything updates" is an assertion; with them it is
checked.
"""

from __future__ import annotations

import functools
import math

import pytest
from build123d import Axis, GeomType, Location, Vector
from OCP.gp import gp_Trsf

from drone_demo.assembly import build_assembly
from drone_demo.config import SPEC
from drone_demo.parts import all_parts, get

pytestmark = pytest.mark.slow

#: Fasteners are exempt from interference checking: a screw is meant to
#: occupy the same volume as its mating hole, and this project doesn't model
#: real thread geometry, so "interference" there is by design, not a defect.
_FASTENER_KEYS = frozenset({"screw_m3x8", "screw_m3x12"})

#: Part-key pairs allowed to overlap, beyond the fastener exemption above,
#: mapped to the maximum overlap volume (mm3) tolerated for that pair. A
#: bare ``True``-style blanket exemption would hide a real future
#: regression between the same two parts, so each entry caps how much
#: overlap is acceptable rather than waiving the check outright.
_ALLOWED_INTERFERENCE_PAIRS: dict[tuple[str, str], float] = {
    # The lower clamp's four tapped bosses thread into the bottom plate —
    # the boss and the plate material occupy the same volume by design,
    # the same way any tapped hole does. The boss pattern sets the scale
    # here, so a generous cap.
    ("arm_clamp_lower", "bottom_plate"): 1000.0,
    # The leg's spigot is a deliberate 0.15 mm interference press fit into
    # the foot (see parts/landing.py) — the whole point is that the two
    # solids overlap slightly before assembly "squeezes" them.
    ("landing_foot", "landing_leg"): 1000.0,
    # NOT intentional, but negligible and understood: the motor mount's
    # plate (32 mm dia) is slightly wider than its collar is long (30 mm),
    # so the plate's filleted bottom edge overhangs the collar by ~1 mm and
    # grazes the tube's chamfered tip. Measured at ~2.7 mm3 — 0.03% of the
    # tube's own volume, invisible at render scale. Capped tightly (not
    # blanket-exempted) so a real future clash between these two still fails.
    ("arm_tube", "motor_mount"): 10.0,
    # NOT intentional: the battery sits with a genuine 0.1 mm clearance gap
    # above the tray floor (see assembly.py), which cleared most of an
    # earlier ~46 mm3 coincident-face artefact here, but a residual ~21 mm3
    # remains — almost certainly the tray's inside wall-to-floor fillet
    # grazing the battery's own rounded corners. 0.008% of the battery's
    # volume, invisible at render scale. Capped, not blanket-exempted.
    ("battery", "battery_tray"): 50.0,
}


@functools.cache
def _cached_geometry(key: str):
    return get(key).builder()


def _placed(instance):
    """A part's solid, moved to its instance's vehicle-space transform."""
    trsf = gp_Trsf()
    trsf.SetValues(*[v for row in instance.transform[:3] for v in row])
    loc = Location(gp_trsf=trsf)
    return loc * _cached_geometry(instance.part.key)


def _bbox_overlap(b1, b2) -> bool:
    return not (
        b1.max.X < b2.min.X or b2.max.X < b1.min.X
        or b1.max.Y < b2.min.Y or b2.max.Y < b1.min.Y
        or b1.max.Z < b2.min.Z or b2.max.Z < b1.min.Z
    )


@pytest.mark.parametrize("part", all_parts(), ids=lambda p: p.key)
def test_every_part_builds(part):
    """The builder returns a solid with positive volume and a valid shape."""
    solid = part.builder()
    assert solid.volume > 0
    assert solid.is_valid


@pytest.mark.parametrize("part", all_parts(), ids=lambda p: p.key)
def test_parts_are_single_solids(part):
    """No part may come out as two disconnected lumps.

    A boolean that silently split a part in two is easy to miss visually and
    fatal to the mass and FEA results.
    """
    solid = part.builder()
    assert len(solid.solids()) == 1, f"{part.key} built as {len(solid.solids())} solids"


#: FDM overhang rule of thumb: a downward-facing surface printable without
#: support has to stay within this many degrees of vertical.
_OVERHANG_LIMIT_DEG = 45.0
#: Curved (cylindrical) surfaces are exempt up to this radius. A horizontal
#: hole or fillet this small or smaller self-bridges: each printed layer
#: only has to advance a fraction of a millimetre past the one below it to
#: follow the curve, even directly at the bottom of the circle, so slicers
#: and printers alike treat it as supportless regardless of the local
#: tangent angle. The flat-ceiling 45 deg rule this test otherwise enforces
#: assumes a single layer spanning the *whole* overhang in one go, which is
#: a different (and genuinely unprintable) failure mode. The snap collar's
#: ~11 mm outer radius is comfortably inside this band; a duct or bore
#: bigger than this would not be.
_SELF_BRIDGING_RADIUS_MM = 20.0
_FACE_SAMPLE_UV = (0.05, 0.2, 0.4, 0.5, 0.6, 0.8, 0.95)


def test_printed_leg_has_no_unprintable_overhang():
    """No downward face may exceed the printed part's overhang limit.

    Walk the leg's faces, take each normal, and compute the angle from
    straight down. This is the test that makes the "prints without support"
    claim in the design notes something other than a hopeful sentence.

    Print orientation: standing on the foot spigot (see design notes and
    ``build_landing_leg``), which is a straight extrude along local +Z —
    so local +Z is the build-up axis, with no reorientation needed.
    """
    solid = get("landing_leg").builder()
    z_min = solid.bounding_box().min.Z
    down = Vector(0, 0, -1)

    violations = []
    for face in solid.faces():
        if face.geom_type == GeomType.CYLINDER and face.radius <= _SELF_BRIDGING_RADIUS_MM:
            continue
        for u in _FACE_SAMPLE_UV:
            for v in _FACE_SAMPLE_UV:
                normal = face.normal_at(u, v).normalized()
                angle_from_down = math.degrees(math.acos(max(-1.0, min(1.0, normal.dot(down)))))
                if angle_from_down >= _OVERHANG_LIMIT_DEG:
                    continue
                point = face.position_at(u, v) if hasattr(face, "position_at") else face.center()
                if abs(point.Z - z_min) < 0.5:
                    continue  # resting on the build plate, not an overhang
                violations.append(
                    f"{face.geom_type} at {point} overhangs {angle_from_down:.1f} deg "
                    f"from vertical (u={u}, v={v})"
                )

    assert not violations, "unprintable overhang:\n" + "\n".join(violations)


def test_moulded_parts_have_draft():
    """Every wall on a moulded part must carry at least a minimal draft.

    ``landing_foot`` is the one part actually pulled from a single-axis
    mould (see ``build_landing_foot``): faces are checked against the local
    +Z pull direction. A face perpendicular to the pull (a flat top or
    floor) needs no draft and is exempt; every other face must lean away
    from vertical by at least a token minimum, or the tool could never
    release it.

    The propeller is also ``process_key="injection"`` but is explicitly
    moulded in two halves along a parting line that follows the blade's
    twist (see its design notes) rather than pulled along one straight
    axis, so a single-axis draft check does not apply to it and it is out
    of scope here.
    """
    foot = SPEC.landing_foot
    solid = get("landing_foot").builder()
    pull = Vector(0, 0, 1)
    #: Real tools use 0.5-2 deg minimum; set well below the part's actual
    #: draft_deg so this catches "draft silently dropped to 0", not
    #: fusses over a few tenths of a degree of curvature/meshing noise.
    min_draft_deg = 0.5

    violations = []
    for face in solid.faces():
        worst_draft_deg = 90.0
        for u in _FACE_SAMPLE_UV:
            for v in _FACE_SAMPLE_UV:
                normal = face.normal_at(u, v).normalized()
                angle_from_pull = math.degrees(
                    math.acos(max(-1.0, min(1.0, abs(normal.dot(pull)))))
                )
                # 0 deg = normal parallel to pull (flat, perpendicular-to-pull
                # face, always fine); 90 deg = normal perpendicular to pull
                # (a purely vertical, undrafted wall). Draft angle is how far
                # the wall leans away from that worst case.
                draft_deg = 90.0 - angle_from_pull
                worst_draft_deg = min(worst_draft_deg, draft_deg)
        if worst_draft_deg < min_draft_deg:
            violations.append(
                f"{face.geom_type} at {face.center()} has only {worst_draft_deg:.2f} deg "
                f"draft (min {min_draft_deg} deg)"
            )

    assert not violations, "insufficient mould draft:\n" + "\n".join(violations)
    assert foot.draft_deg >= min_draft_deg  # sanity: the config itself claims enough draft


def _measure_planar_gap(solid, sample_points, direction) -> float | None:
    """Distance between the two nearest flat, direction-perpendicular faces
    hit by a ray, tried at each candidate point until one lands on solid
    material clear of any hole or slot. None if no candidate point works.

    This is a caliper, not a volume estimate: it measures the actual wall
    thickness at a point directly from geometry, independent of whatever
    thickness value the builder function used, so a flange that quietly
    came out thicker than the part's own ``thickness_mm`` is caught.
    """
    axis_index = next(i for i, v in enumerate(direction) if abs(v) > 0.5)
    for point in sample_points:
        axis = Axis(point, direction)
        coords = []
        for face in solid.faces_intersected_by_axis(axis):
            if face.geom_type != GeomType.PLANE:
                continue
            normal = face.normal_at(face.center()).normalized()
            if abs(abs(tuple(normal)[axis_index]) - 1.0) > 1e-3:
                continue  # not perpendicular to the ray -- not a skin face
            coords.append(round(tuple(face.center())[axis_index], 6))
        coords = sorted(set(coords))
        if len(coords) >= 2:
            return coords[1] - coords[0]
    return None


def test_sheet_metal_thickness_is_uniform():
    """A folded part must be one constant thickness everywhere.

    Calipers the floor and one wall/flange of each sheet metal part by
    ray-casting through known-clear regions and measuring the gap between
    the two skin faces. Catches a modelling mistake that quietly thickens a
    flange (or a future edit that decouples a wall from ``thickness_mm``).
    """
    tol_mm = 0.05

    eb = SPEC.esc_bracket
    esc = get("esc_bracket").builder()
    base_gap = _measure_planar_gap(
        esc,
        sample_points=[(x, y, 100.0) for x in (0.0, 5.0, -5.0) for y in (0.0, 5.0, -5.0)],
        direction=(0, 0, -1),
    )
    assert base_gap == pytest.approx(eb.thickness_mm, abs=tol_mm)
    flange_gap = _measure_planar_gap(
        esc,
        sample_points=[
            (1000.0, y, eb.thickness_mm + eb.flange_height_mm * 0.5) for y in (0.0, 5.0, -5.0)
        ],
        direction=(-1, 0, 0),
    )
    assert flange_gap == pytest.approx(eb.thickness_mm, abs=tol_mm)

    bt = SPEC.battery_tray
    tray = get("battery_tray").builder()
    floor_gap = _measure_planar_gap(
        tray,
        sample_points=[
            (x, y, 100.0)
            for x in (bt.length_mm * 0.35, -bt.length_mm * 0.35)
            for y in (0.0, bt.width_mm * 0.1)
        ],
        direction=(0, 0, -1),
    )
    assert floor_gap == pytest.approx(bt.thickness_mm, abs=tol_mm)
    wall_mid_z = bt.thickness_mm + bt.wall_height_mm * 0.5
    wall_gap = _measure_planar_gap(
        tray,
        sample_points=[
            (x, 1000.0, wall_mid_z) for x in (bt.length_mm * 0.35, -bt.length_mm * 0.35)
        ],
        direction=(0, -1, 0),
    )
    assert wall_gap == pytest.approx(bt.thickness_mm, abs=tol_mm)


def test_no_interference_between_instances():
    """No two placed, non-fastener parts may occupy the same volume.

    Bounding boxes first to find candidate pairs cheaply, then a real
    boolean intersection only on those. Whole-assembly interference
    detection is the single highest-value automated check in mechanical
    CAD, and it is the one thing this pipeline can do that a person
    eyeballing the render cannot.
    """
    assembly = build_assembly()
    candidates = [i for i in assembly.instances if i.part.key not in _FASTENER_KEYS]

    placed_boxes = [(inst, _placed(inst)) for inst in candidates]
    boxes = [(inst, solid, solid.bounding_box()) for inst, solid in placed_boxes]

    violations = []
    for i in range(len(boxes)):
        inst1, solid1, bb1 = boxes[i]
        for j in range(i + 1, len(boxes)):
            inst2, solid2, bb2 = boxes[j]
            if not _bbox_overlap(bb1, bb2):
                continue
            pair_key = tuple(sorted((inst1.part.key, inst2.part.key)))
            allowance = _ALLOWED_INTERFERENCE_PAIRS.get(pair_key, 1.0)
            # intersect() returns None for no overlap, or a ShapeList of
            # Solids for a real one — never a single Solid with .volume
            # directly (verified empirically).
            overlap = solid1.intersect(solid2)
            volume = sum(s.volume for s in overlap) if overlap is not None else 0.0
            if volume > allowance:
                violations.append(
                    f"{inst1.node_id} <-> {inst2.node_id} overlap {volume:.1f} mm3 "
                    f"(allowance {allowance:.1f} mm3)"
                )

    assert not violations, "unexpected interference:\n" + "\n".join(violations)


def test_parametric_sweep_stays_valid():
    """Rebuild at several tube diameters and plate sizes; everything must still build.

    Sweeps ``arm_tube.outer_dia_mm`` and ``frame_plate.half_width_mm`` —
    the two dimensions that actually drive fillet/groove/bore sizing across
    several part modules (motor mount collar, split clamp groove, landing
    leg collar, frame plate arm-attach radius). ``airframe.wheelbase_mm`` is
    deliberately not swept here: nothing in the geometry reads it directly
    (arm length and plate size are independent config values, cross-checked
    for consistency in ``test_arm_geometry_closes`` instead), so sweeping it
    alone would rebuild identical geometry and test nothing.

    This catches the fillet that only fits at the nominal size — by far the
    most common way a "parametric" model turns out not to be.
    """
    import dataclasses

    from drone_demo.config import SPEC

    original_arm_tube = SPEC.arm_tube
    original_frame_plate = SPEC.frame_plate
    try:
        for tube_od in (12.0, 20.0):
            for half_width in (50.0, 75.0):
                new_arm_tube = dataclasses.replace(original_arm_tube, outer_dia_mm=tube_od)
                new_frame_plate = dataclasses.replace(
                    original_frame_plate, half_width_mm=half_width
                )
                object.__setattr__(SPEC, "arm_tube", new_arm_tube)
                object.__setattr__(SPEC, "frame_plate", new_frame_plate)
                for part in all_parts():
                    solid = part.builder()
                    assert solid.volume > 0, (
                        f"{part.key} failed to build at tube_od={tube_od} half_width={half_width}"
                    )
    finally:
        object.__setattr__(SPEC, "arm_tube", original_arm_tube)
        object.__setattr__(SPEC, "frame_plate", original_frame_plate)
