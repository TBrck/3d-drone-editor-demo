"""Places every part instance in vehicle coordinates.

This module owns all positioning.  Part builders know nothing about where
they end up, which is what lets the same ``motor_mount`` geometry be reused
four times at four different angles.

The output is a flat list of :class:`Instance` objects.  The exporter turns
each one into a glTF node; the mass properties routine sums over them; the
FEA driver picks single instances out of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
from build123d import Location

from drone_demo.config import SPEC
from drone_demo.parts import PartDef, get
from drone_demo.parts.arm import motor_mount_plate_top_z
from drone_demo.parts.electronics import esc_bracket_hole_positions
from drone_demo.parts.frame import standoff_angle_deg

Mat4 = tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class Instance:
    """One placed occurrence of a part.

    Attributes
    ----------
    node_id:
        Unique per instance: ``f"{part.key}__{index}"``.  This string is the
        glTF node name and the manifest key, and the web viewer uses it to
        link a click on geometry back to the part record.  Never change the
        format without changing the viewer.
    transform:
        4x4 row-major matrix, millimetres, mapping part-local to vehicle
        coordinates.  Stored as a nested tuple so ``Instance`` stays hashable
        and JSON-serialisable without a numpy dependency in the manifest.
    group:
        Logical sub-assembly for the viewer's tree and for group isolation.
        One of "arm_0".."arm_3", "frame", "power", "gear".
    explode_dir:
        Unit vector along which this instance moves in the exploded view.
        Chosen so the explosion reads as a disassembly sequence: parts move
        the way a fitter would actually pull them off.
    explode_rank:
        Ordering hint, 0 = stays put.  Higher ranks travel further, so an
        outer part clears the parts beneath it instead of passing through
        them.
    """

    node_id: str
    part: PartDef
    transform: Mat4
    group: str
    explode_dir: tuple[float, float, float] = (0.0, 0.0, 1.0)
    explode_rank: int = 0


@dataclass
class Assembly:
    """The complete vehicle."""

    instances: list[Instance] = field(default_factory=list)

    def by_part(self, key: str) -> list[Instance]:
        """All instances of one part key."""
        return [i for i in self.instances if i.part.key == key]

    def groups(self) -> tuple[str, ...]:
        """Distinct group names, in first-seen order."""
        seen: dict[str, None] = {}
        for inst in self.instances:
            seen.setdefault(inst.group, None)
        return tuple(seen)


# ---------------------------------------------------------------------------
# Transform helpers
#
# Internally these use numpy 4x4 matrices in the standard convention
# (points as column vectors, p' = M @ p). Instance.transform stores the
# result as a plain nested tuple of Python floats so the manifest has no
# numpy dependency; only this module needs numpy.
# ---------------------------------------------------------------------------


def _to_tuple(m: np.ndarray) -> Mat4:
    return tuple(tuple(float(x) for x in row) for row in m)


def translation(x: float, y: float, z: float) -> Mat4:
    """Row-major 4x4 pure translation, millimetres."""
    m = np.eye(4)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return _to_tuple(m)


def rotation_z(angle_deg: float) -> Mat4:
    """Row-major 4x4 rotation about +Z."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return _to_tuple(m)


def rotate_dir_z(v: tuple[float, float, float], angle_deg: float) -> tuple[float, float, float]:
    """Rotate a direction (not a point) about +Z by ``angle_deg``.

    ``explode_dir`` for an arm's parts is authored in arm-local space (X
    along the tube) before ``arm_placement`` swings that whole arm out to
    its actual angle around the vehicle; without this, every arm's "along
    the tube" explode direction stayed pointed along global +X regardless
    of which way the arm actually faces, so only the one arm nearest 0 deg
    exploded outward correctly and the rest exploded sideways across
    themselves instead — the mechanical cause of an "explosion looks
    inconsistent between arms" report.
    """
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = v
    return (c * x - s * y, s * x + c * y, z)


def rotation_x(angle_deg: float) -> Mat4:
    """Row-major 4x4 rotation about +X. Used to flip parts that mount upside down."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1, 1], m[1, 2] = c, -s
    m[2, 1], m[2, 2] = s, c
    return _to_tuple(m)


def compose(*mats: Mat4) -> Mat4:
    """Multiply transforms left to right: ``compose(a, b)`` applies ``a`` then ``b``.

    Pick this convention and hold it. A silently reversed multiplication order
    is the single most likely source of a wrong-looking assembly, and it is
    hard to spot because most parts are near the origin.

    With points as column vectors (p' = M @ p), "apply a then b" means the
    combined matrix is ``b @ a`` — b is the outer (last-applied) matrix.
    """
    result = np.eye(4)
    for m in mats:
        result = np.array(m) @ result
    return _to_tuple(result)


def location_to_mat4(loc: Location) -> Mat4:
    """A build123d ``Location`` as this module's row-major ``Mat4``.

    The inverse of what ``export/cad.py``'s STEP exporter already does the
    other way (``Mat4`` -> ``gp_Trsf`` -> ``Location``, via
    ``trsf.SetValues(*[v for row in transform[:3] for v in row])``) — same
    12 numbers, same row-major layout, just read back out via
    ``gp_Trsf.Value(row, col)`` (OCCT's 1-indexed accessor) instead of set.
    Used for studio-authored parts, whose placement is authored as
    position + rotation (see parts/custom.py's ``_node_location``) rather
    than a hand-built matrix, precisely to avoid a three.js-is-column-major
    vs. this-module-is-row-major mismatch.
    """
    trsf = loc.wrapped.Transformation()
    rows = tuple(
        tuple(trsf.Value(r, c) for c in range(1, 5)) for r in range(1, 4)
    )
    return rows + ((0.0, 0.0, 0.0, 1.0),)


# ---------------------------------------------------------------------------
# Assembly construction
# ---------------------------------------------------------------------------


def build_arm(index: int, angle_deg: float) -> list[Instance]:
    """Every instance belonging to one arm, in vehicle coordinates.

    Built along +X in "arm-local" coordinates first (X=0 at the frame
    attach point, matching every part module's own local frame in
    :mod:`drone_demo.parts.arm`), then placed in the vehicle by translating
    that datum out to the frame's attach radius and rotating once about Z.
    Every part instance below therefore only needs its own small offset
    *within* the arm-local frame; ``_arm_placement`` carries it the rest of
    the way.
    """
    ac = SPEC.arm_clamp
    t = SPEC.arm_tube
    mm = SPEC.motor_mount
    leg = SPEC.landing_leg
    fp = SPEC.frame_plate

    arm_placement = compose(translation(fp.arm_attach_radius_mm, 0.0, 0.0), rotation_z(angle_deg))
    group = f"arm_{index}"
    instances: list[Instance] = []

    def add(part_key: str, local: Mat4, explode_dir=(0.0, 0.0, 1.0), rank=0) -> None:
        # node_id is a placeholder here — build_assembly() renumbers every
        # instance per part_key afterwards, since several parts (the
        # screws especially) are placed more than once per arm and a
        # per-arm index alone would not be unique.
        instances.append(
            Instance(
                node_id=f"{part_key}__pending",
                part=get(part_key),
                transform=compose(local, arm_placement),
                group=group,
                explode_dir=rotate_dir_z(explode_dir, angle_deg),
                explode_rank=rank,
            )
        )

    # --- clamp, at the frame end (arm-local X = 0) --------------------
    add("arm_clamp_upper", translation(0, 0, 0), explode_dir=(0, 0, 1), rank=2)
    add("arm_clamp_lower", translation(0, 0, 0), explode_dir=(0, 0, -1), rank=2)

    # --- tube, running the length of the arm ---------------------------
    add("arm_tube", translation(0, 0, 0), explode_dir=(1, 0, 0), rank=1)

    # --- motor mount, at the tube's far end -----------------------------
    add("motor_mount", translation(t.length_mm, 0, 0), explode_dir=(1, 0, 0), rank=2)

    mount_top_z = motor_mount_plate_top_z()
    motor_x = t.length_mm + mm.collar_length_mm / 2
    add("motor", translation(motor_x, 0, mount_top_z), explode_dir=(0, 0, 1), rank=3)
    add(
        "propeller",
        translation(motor_x, 0, mount_top_z + SPEC.motor.body_height_mm),
        explode_dir=(0, 0, 1),
        rank=4,
    )

    # --- ESC bracket, mid-tube, hanging underneath ----------------------
    esc_x = t.length_mm * 0.45
    esc_z = -t.outer_dia_mm / 2 - SPEC.esc_bracket.thickness_mm
    add(
        "esc_bracket",
        compose(rotation_x(180.0), translation(esc_x, 0, esc_z)),
        explode_dir=(0, 0, -1),
        rank=1,
    )

    # --- landing leg, two-thirds out along the tube, underneath ---------
    leg_x = t.length_mm * 0.66
    add("landing_leg", translation(leg_x, 0, 0), explode_dir=(0, 0, -1), rank=2)

    tan_splay = math.tan(math.radians(leg.splay_deg))
    collar_or = t.outer_dia_mm / 2 + 3.0
    collar_ir = t.outer_dia_mm / 2 + 0.3
    z_top = -(collar_ir + collar_or) / 2
    foot_y = leg.height_mm * tan_splay
    foot_z = z_top - leg.height_mm - 10.0  # 10 mm spigot length, matches landing.py
    add(
        "landing_foot",
        translation(leg_x, foot_y, foot_z),
        explode_dir=(0, 0, -1),
        rank=3,
    )

    # --- fasteners --------------------------------------------------------
    # Motor bolts: the mount's own 16/19 mm crossed pattern, on the plate top.
    for bx, by in (
        (mm.bolt_pattern_a_mm / 2, 0.0),
        (-mm.bolt_pattern_a_mm / 2, 0.0),
        (0.0, mm.bolt_pattern_b_mm / 2),
        (0.0, -mm.bolt_pattern_b_mm / 2),
    ):
        add(
            "screw_m3x8",
            translation(motor_x + bx, by, mount_top_z + SPEC.motor.body_height_mm * 0.25),
            explode_dir=(0, 0, 1),
            rank=5,
        )

    # ESC bolts: two of the bracket's four holes (bracket is flipped, so its
    # local Z=0 face sits at esc_z once placed).
    esc_holes = esc_bracket_hole_positions()
    for hx, hy in (esc_holes[0], esc_holes[3]):
        add(
            "screw_m3x8",
            compose(rotation_x(180.0), translation(esc_x + hx, -hy, esc_z)),
            explode_dir=(0, 0, -1),
            rank=1,
        )

    # Clamp bolts: the two through-bolts closing the split clamp on the tube.
    for sy in (ac.bolt_spacing_mm / 2, -ac.bolt_spacing_mm / 2):
        add(
            "screw_m3x12",
            translation(0, sy, ac.half_thickness_mm),
            explode_dir=(0, 0, 1),
            rank=3,
        )

    # Clamp-to-plate bolts: the lower clamp's four tapped bosses.
    half_pat = ac.boss_pattern_mm / 2
    lower_t = ac.half_thickness_mm + 2.0
    boss_corners = (
        (-half_pat, -half_pat), (half_pat, -half_pat),
        (-half_pat, half_pat), (half_pat, half_pat),
    )
    for bx, by in boss_corners:
        add(
            "screw_m3x12",
            compose(rotation_x(180.0), translation(bx, -by, lower_t + 3.0)),
            explode_dir=(0, 0, -1),
            rank=2,
        )

    # Motor mount collar screw, closing the split collar.
    screw_z = -(mm.collar_wall_mm * 2 + t.outer_dia_mm / 2) * 0.6
    add(
        "screw_m3x12",
        compose(rotation_x(90.0), translation(t.length_mm + mm.collar_length_mm / 2, 0, screw_z)),
        explode_dir=(0, 1, 0),
        rank=2,
    )

    return instances


def build_frame() -> list[Instance]:
    """Plates, standoffs, battery tray, battery and their screws.

    Bottom plate top face is Z = 0 by definition of the vehicle datum, so the
    bottom plate spans Z = -thickness to 0 and the top plate sits at
    Z = standoff length.
    """
    fp = SPEC.frame_plate
    so = SPEC.standoff
    bt = SPEC.battery_tray
    group = "frame"
    instances: list[Instance] = []

    def add(part_key: str, local: Mat4, explode_dir=(0.0, 0.0, 1.0), rank=0) -> None:
        # See the matching note in build_arm — node_id is finalised in
        # build_assembly(), not here.
        instances.append(
            Instance(
                node_id=f"{part_key}__pending",
                part=get(part_key),
                transform=local,
                group=group,
                explode_dir=explode_dir,
                explode_rank=rank,
            )
        )

    add("bottom_plate", translation(0, 0, -fp.thickness_mm), explode_dir=(0, 0, -1), rank=1)
    add("top_plate", translation(0, 0, so.length_mm), explode_dir=(0, 0, 1), rank=1)

    for i in range(fp.standoff_count):
        a = math.radians(standoff_angle_deg(i))
        x = fp.standoff_circle_mm / 2 * math.cos(a)
        y = fp.standoff_circle_mm / 2 * math.sin(a)
        add("standoff", translation(x, y, 0), explode_dir=(0, 0, 1), rank=1)
        add(
            "screw_m3x12",
            translation(x, y, -fp.thickness_mm),
            explode_dir=(0, 0, -1), rank=2,
        )
        add(
            "screw_m3x12",
            compose(rotation_x(180.0), translation(x, y, so.length_mm + fp.thickness_mm)),
            explode_dir=(0, 0, 1), rank=2,
        )

    # Tray floor sits directly on the bottom plate's top face (vehicle Z=0);
    # both battery_tray and battery are built with their own local Z=0 at
    # their own bottom face, so no offset is needed here — verified against
    # test_no_interference_between_instances, which previously caught this
    # placed at -fp.thickness_mm, exactly overlapping the bottom plate.
    add("battery_tray", translation(0, 0, 0), explode_dir=(0, 0, -1), rank=1)
    # +0.1 mm above the tray floor, not flush with it: an exactly coincident
    # face there made OCCT's boolean intersect report a spurious ~46 mm3
    # sliver (caught by test_no_interference_between_instances) — a
    # numerical artefact of the tangent surfaces, not a real clash. A tiny,
    # visually imperceptible clearance gap is the honest fix, matching how
    # a battery actually just rests on the tray rather than being modelled
    # as touching to zero tolerance.
    add(
        "battery",
        translation(0, 0, bt.thickness_mm + 0.1),
        explode_dir=(0, 0, -1), rank=2,
    )

    return instances


def build_custom_parts() -> list[Instance]:
    """Studio-authored parts (``custom_parts.json``), placed in vehicle space.

    Unlike ``build_arm``'s parts, a custom part's placement is an absolute
    vehicle-frame transform — there is no parametric attachment to an arm
    or plate the way ``arm_placement`` carries an arm's parts along with it.
    If the airframe's dimensions change later, a custom part stays exactly
    where it was saved; it will not follow anything. That is a deliberate
    v1 limitation of studio-authored parts, not an oversight.
    """
    from drone_demo.parts.custom import load_custom_part_specs

    instances = []
    for spec in load_custom_part_specs():
        p = spec.get("placement", {})
        loc = Location(
            tuple(p.get("position_mm", (0.0, 0.0, 0.0))),
            tuple(p.get("rotation_deg", (0.0, 0.0, 0.0))),
        )
        instances.append(
            Instance(
                node_id=f"{spec['key']}__pending",
                part=get(spec["key"]),
                transform=location_to_mat4(loc),
                group=p.get("group", "custom"),
                explode_dir=tuple(p.get("explode_dir", (0.0, 0.0, 1.0))),
                explode_rank=p.get("explode_rank", 0),
            )
        )
    return instances


def build_assembly() -> Assembly:
    """Assemble the whole vehicle.

    Deterministic: the same code produces the same instance order every
    run, so the exported ``.glb`` is byte-stable and git diffs stay
    meaningful.

    ``build_arm`` and ``build_frame`` leave every ``node_id`` as
    ``"{part_key}__pending"`` — several parts (screws especially) are
    placed more than once per arm, so a per-arm index alone is not unique.
    This function assigns the final ``f"{part_key}__{i}"`` node ids in one
    pass, in instance-creation order, which is what makes the numbering
    deterministic run to run.
    """
    raw: list[Instance] = []
    for i, angle in enumerate(SPEC.airframe.arm_angles_deg):
        raw.extend(build_arm(i, angle))
    raw.extend(build_frame())
    raw.extend(build_custom_parts())

    counters: dict[str, int] = {}
    instances: list[Instance] = []
    for inst in raw:
        n = counters.get(inst.part.key, 0)
        counters[inst.part.key] = n + 1
        instances.append(replace(inst, node_id=f"{inst.part.key}__{n}"))

    return Assembly(instances=instances)
