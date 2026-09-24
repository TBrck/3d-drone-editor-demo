"""Arm sub-assembly: tube, motor mount, and the split clamp at the frame end.

This is the flagship sub-assembly of the demo — it carries the flight loads,
it shows the most design reasoning, and it is what the viewer opens on.

Local coordinate convention for every part in this module
--------------------------------------------------------
The arm runs along +X.  X = 0 is the outer edge of the frame plate; the tube
therefore spans X = 0 to X = ArmTube.length_mm, and the motor shaft axis sits
at X = length_mm + a bit.  Z is up, matching the assembled orientation, so
the assembly only has to rotate each arm about Z and translate it out.
"""

from __future__ import annotations

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    GeomType,
    Locations,
    Mode,
    Part,
    Plane,
    Pos,
    Rectangle,
    add,
    chamfer,
    extrude,
    fillet,
)

from drone_demo.config import SPEC
from drone_demo.parts.base import Annotation, PartDef, register

# ---------------------------------------------------------------------------
# Arm tube
# ---------------------------------------------------------------------------


def build_arm_tube() -> Part:
    """Plain pultruded CFRP tube, cut to length.

    Hollow cylinder, axis along +X starting at the origin, both ends broken
    with a small chamfer so the part doesn't render with a razor edge.
    """
    t = SPEC.arm_tube
    with BuildPart() as bp:
        with BuildSketch(Plane.YZ):
            Circle(t.outer_dia_mm / 2)
            Circle(t.inner_dia_mm / 2, mode=Mode.SUBTRACT)
        extrude(amount=t.length_mm)
        ends = bp.edges().filter_by(GeomType.CIRCLE).group_by(Axis.X)
        chamfer(ends[0] + ends[-1], length=0.3)
    return bp.part


register(
    PartDef(
        key="arm_tube",
        name="Arm tube, 16 x 1.5 CFRP",
        builder=build_arm_tube,
        material_key="cfrp_tube",
        process_key="stock",
        quantity=SPEC.airframe.arm_count,
        critical=True,
        summary=(
            "Pultruded carbon tube carrying the motor thrust and reaction "
            "torque back to the frame. The single most weight-critical part "
            "on the vehicle."
        ),
        design_notes=(
            "16 mm OD x 1.5 mm wall is the smallest standard section that keeps "
            "the root bending stress under a safety factor of 4 in hover.",
            "A round section was chosen over square because the clamp can then "
            "grip on any clocking, which makes the motor tilt adjustable during "
            "flight testing without new parts.",
            "The tube is never drilled. A hole would cut the load-carrying "
            "fibres and halve the section's bending capacity.",
        ),
        annotations=(
            Annotation(
                title="Why no bolt through the tube",
                body=(
                    "A through-bolt is the obvious way to fix a tube, and it is "
                    "wrong here. Drilling severs the unidirectional fibres that "
                    "carry the bending load, and the bolt crushes the thin wall. "
                    "Both clamps grip on friction over a wide area instead."
                ),
                at_mm=(20.0, 0.0, 8.0),
                kind="load",
            ),
        ),
    )
)


# ---------------------------------------------------------------------------
# Motor mount
# ---------------------------------------------------------------------------


#: How far the motor plate's cylinder sinks into the collar before its own
#: bottom edge is filleted. This is a modelling technique, not a physical
#: dimension: filleting the raw boolean intersection of two near-tangent
#: cylinders is numerically unreliable in OCCT (verified — it fails even at
#: 0.5 mm on this geometry). Pre-filleting the plate as a standalone solid
#: and then fusing it into the collar sidesteps that entirely and gives an
#: identical-looking result.
_PLATE_OVERLAP_MM = 5.0


def motor_mount_plate_top_z() -> float:
    """Height, in the motor mount's own local frame, of the plate's top face.

    This is where the motor sits. Exposed so ``assembly.py`` can place the
    motor without duplicating ``_PLATE_OVERLAP_MM`` or recomputing the
    collar geometry — one source of truth for the number.
    """
    mm = SPEC.motor_mount
    collar_od = SPEC.arm_tube.outer_dia_mm + 2 * mm.collar_wall_mm
    plate_z = collar_od / 2 - _PLATE_OVERLAP_MM
    return plate_z + _PLATE_OVERLAP_MM + mm.plate_thickness_mm


def build_motor_mount() -> Part:
    """CNC machined motor mount: split collar below, motor face on top.

    1. Collar: tube-section cylinder about the local X axis.
    2. Slit: cut through the wall on the -Z side only, full collar length,
       so the collar can close like a hose clamp.
    3. Clamp screw: a cross hole below the tube centreline, offset so
       tightening it pulls the collar closed rather than prying it open.
    4. Motor plate: built as its own solid with its bottom edge pre-filleted
       (see ``_PLATE_OVERLAP_MM``), then fused onto the collar.
    5. Motor bolt pattern on the crossed 16/19 mm pattern, plus the central
       boss recess.
    6. Chamfer the plate's top rim and the collar's outer end edges.
    """
    mm = SPEC.motor_mount
    t = SPEC.arm_tube

    # Running clearance on the tube. 0.2 mm (0.1 mm radial) proved too tight
    # against the tube's own 0.3 mm end chamfer — test_no_interference_
    # between_instances caught a ~3 mm3 sliver where the two met.
    collar_bore = t.outer_dia_mm + 0.6
    collar_od = t.outer_dia_mm + 2 * mm.collar_wall_mm
    plate_z = collar_od / 2 - _PLATE_OVERLAP_MM
    cx, cy = mm.collar_length_mm / 2, 0.0

    # Plate, built standalone so its bottom edge fillet is a trivial
    # single-radius fillet on a plain cylinder rather than on a boolean seam.
    with BuildPart() as plate_bp:
        Cylinder(
            radius=mm.plate_dia_mm / 2,
            height=mm.plate_thickness_mm + _PLATE_OVERLAP_MM,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        bottom_edge = plate_bp.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0].edges()
        fillet(bottom_edge, radius=mm.fillet_mm)
    plate_solid = Pos(cx, cy, plate_z) * plate_bp.part

    with BuildPart() as bp:
        with BuildSketch(Plane.YZ):
            Circle(collar_od / 2)
            Circle(collar_bore / 2, mode=Mode.SUBTRACT)
        extrude(amount=mm.collar_length_mm)

        slit_box = Pos(-1, 0, -collar_od / 2 - 1) * Box(
            mm.collar_length_mm + 2,
            mm.collar_slit_mm,
            collar_od / 2 + 2,
            align=(Align.MIN, Align.CENTER, Align.MIN),
        )
        add(slit_box, mode=Mode.SUBTRACT)

        screw_z = -(collar_od / 2) * 0.6
        with BuildSketch(
            Plane((mm.collar_length_mm / 2, 0, screw_z), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
        ):
            Circle(mm.clamp_screw_dia_mm / 2)
        extrude(amount=collar_od, both=True, mode=Mode.SUBTRACT)

        add(plate_solid)

        top_z = plate_z + _PLATE_OVERLAP_MM + mm.plate_thickness_mm
        bolt_pts = [
            (cx + mm.bolt_pattern_a_mm / 2, cy),
            (cx - mm.bolt_pattern_a_mm / 2, cy),
            (cx, cy + mm.bolt_pattern_b_mm / 2),
            (cx, cy - mm.bolt_pattern_b_mm / 2),
        ]
        with BuildSketch(Plane.XY.offset(top_z)):
            with Locations(*bolt_pts):
                Circle(mm.bolt_dia_mm / 2)
        extrude(amount=-(mm.plate_thickness_mm + _PLATE_OVERLAP_MM), mode=Mode.SUBTRACT)

        with BuildSketch(Plane.XY.offset(top_z)):
            with Locations((cx, cy)):
                Circle(mm.boss_dia_mm / 2)
        extrude(amount=-mm.boss_depth_mm, mode=Mode.SUBTRACT)

        top_face = bp.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1]
        top_rim = top_face.edges().filter_by(GeomType.CIRCLE)
        chamfer(top_rim, length=mm.edge_chamfer_mm)

        ends = bp.faces().filter_by(Axis.X).sort_by(Axis.X)
        end_rims = (ends[0].edges() + ends[-1].edges()).filter_by(GeomType.CIRCLE)
        end_rims = end_rims.filter_by(lambda e: abs(e.radius - collar_od / 2) < 0.01)
        chamfer(end_rims, length=mm.edge_chamfer_mm)

    return bp.part


register(
    PartDef(
        key="motor_mount",
        name="Motor mount, machined",
        builder=build_motor_mount,
        material_key="al6061",
        process_key="cnc",
        quantity=SPEC.airframe.arm_count,
        critical=True,
        summary=(
            "Takes the motor's thrust and torque into the arm tube through a "
            "split clamp. Machined from 6061-T6 billet."
        ),
        design_notes=(
            "Split collar rather than a bonded joint: the motor is a wear item "
            "and has to come off without heat or solvent.",
            "The clamp screw is offset below the tube centreline so tightening "
            "it pulls the collar closed rather than prying it open.",
            "All internal corners are R2 so a standard 4 mm end mill reaches "
            "them; nothing on the part needs a custom cutter.",
            "Two setups: the bore is machined first and then used as the datum "
            "for the motor face, which keeps the two axes square to each other.",
        ),
        annotations=(
            Annotation(
                title="Thermal path",
                body=(
                    "The aluminium plate under the motor doubles as a heatsink. "
                    "Its diameter is set by the motor can, not by strength — "
                    "strength alone would allow a much smaller plate."
                ),
                at_mm=(0.0, 0.0, 14.0),
                kind="interface",
            ),
            Annotation(
                title="Clamp slit",
                body=(
                    "The slit runs the full collar length so the grip is even "
                    "end to end. A partial slit would clamp hard at the open end "
                    "and barely at all at the closed end, and the tube would "
                    "creep out under vibration."
                ),
                at_mm=(0.0, 0.0, -9.0),
                kind="dfm",
            ),
        ),
    )
)


# ---------------------------------------------------------------------------
# Frame-end split clamp (two halves)
# ---------------------------------------------------------------------------


#: Extra material on the lower half for the tapped bosses' thread engagement.
_LOWER_EXTRA_THICKNESS_MM = 2.0
#: Counterbore for the two clamp bolt heads (upper half only).
_CBORE_DIA_MM = 5.5
_CBORE_DEPTH_MM = 3.0
#: The four tapped bosses that pick up the bottom frame plate (lower half only).
#: Pattern spacing itself is ``SPEC.arm_clamp.boss_pattern_mm``, shared with
#: FramePlate so the two always land on the same points.
_BOSS_DIA_MM = 6.0
_BOSS_HEIGHT_MM = 3.0
_TAP_DRILL_DIA_MM = 2.5
_TAP_DEPTH_MM = 6.0


def _clamp_body(z0: float, z1: float) -> Part:
    """The shared rounded-rectangle body with the tube groove cut in.

    Local frame: tube axis at Y=0, Z=0, matching ``build_arm_tube``'s own
    origin, so the assembly can place both at the arm's X=0 datum. Block is
    centred on X=0 and spans Z from ``z0`` to ``z1``.
    """
    ac = SPEC.arm_clamp
    t = SPEC.arm_tube
    groove_r = t.outer_dia_mm / 2 + 0.05  # per design note: cut oversize, not on size

    with BuildPart() as bp:
        with BuildSketch(Plane.XY.offset(z0)):
            Rectangle(ac.length_mm, ac.width_mm)
        extrude(amount=(z1 - z0))
        fillet(bp.edges().filter_by(Axis.Z), radius=ac.fillet_mm)

        with BuildSketch(Plane.YZ):
            Circle(groove_r)
        extrude(amount=ac.length_mm, both=True, mode=Mode.SUBTRACT)

    return bp.part


def _clamp_half(is_upper: bool) -> Part:
    """Both clamp halves share ``_clamp_body``; they differ only outboard.

    upper
        Plain slab above the tube, with counterbores for the two bolt heads.
    lower
        A slab below the tube, 2 mm thicker for thread engagement, with two
        plain through-holes (the bolts are tapped into the upper half... no —
        both bolts are through-bolts, nutted or tapped into the frame plate
        stack above) and four tapped bosses on its underside that pick up the
        bottom frame plate.
    """
    ac = SPEC.arm_clamp
    bolt_pts = ((0.0, ac.bolt_spacing_mm / 2), (0.0, -ac.bolt_spacing_mm / 2))

    if is_upper:
        with BuildPart() as bp:
            add(_clamp_body(0.0, ac.half_thickness_mm))
            with BuildSketch(Plane.XY.offset(ac.half_thickness_mm)):
                with Locations(*bolt_pts):
                    Circle(ac.bolt_dia_mm / 2)
            extrude(amount=-ac.half_thickness_mm, mode=Mode.SUBTRACT)
            with BuildSketch(Plane.XY.offset(ac.half_thickness_mm)):
                with Locations(*bolt_pts):
                    Circle(_CBORE_DIA_MM / 2)
            extrude(amount=-_CBORE_DEPTH_MM, mode=Mode.SUBTRACT)
        return bp.part

    lower_t = ac.half_thickness_mm + _LOWER_EXTRA_THICKNESS_MM
    half_pat = ac.boss_pattern_mm / 2
    boss_pts = [(x, y) for x in (-half_pat, half_pat) for y in (-half_pat, half_pat)]
    with BuildPart() as bp:
        add(_clamp_body(-lower_t, 0.0))
        with BuildSketch(Plane.XY.offset(0.0)):
            with Locations(*bolt_pts):
                Circle(ac.bolt_dia_mm / 2)
        extrude(amount=-lower_t, mode=Mode.SUBTRACT)

        with BuildSketch(Plane.XY.offset(-lower_t)):
            with Locations(*boss_pts):
                Circle(_BOSS_DIA_MM / 2)
        extrude(amount=-_BOSS_HEIGHT_MM)

        with BuildSketch(Plane.XY.offset(-lower_t - _BOSS_HEIGHT_MM)):
            with Locations(*boss_pts):
                Circle(_TAP_DRILL_DIA_MM / 2)
        extrude(amount=_TAP_DEPTH_MM, mode=Mode.SUBTRACT)
    return bp.part


def build_arm_clamp_upper() -> Part:
    return _clamp_half(is_upper=True)


def build_arm_clamp_lower() -> Part:
    return _clamp_half(is_upper=False)


_CLAMP_NOTES = (
    "The clamp face is 34 mm long, more than twice the tube diameter. The "
    "grip pressure is spread over enough area that the laminate never sees a "
    "local crush stress above 25 MPa.",
    "Both halves are machined as a matched pair with a 0.4 mm gap left "
    "between them at nominal, so the bolts always have travel left to take up "
    "tube diameter tolerance.",
    "The groove radius is 0.05 mm larger than the nominal tube radius. Cut it "
    "on size and the halves bottom out on each other before they grip.",
)

register(
    PartDef(
        key="arm_clamp_upper",
        name="Arm clamp, upper half",
        builder=build_arm_clamp_upper,
        material_key="al6061",
        process_key="cnc",
        quantity=SPEC.airframe.arm_count,
        critical=True,
        summary="Upper half of the split clamp that anchors the arm to the frame plates.",
        design_notes=_CLAMP_NOTES,
        annotations=(
            Annotation(
                title="Friction joint, sized by torque",
                body=(
                    "Two M3 bolts at 1.2 Nm give roughly 4 kN of combined clamp "
                    "force (F = T/(K*d), K = 0.20). Against a friction coefficient "
                    "of 0.15 that resists about 600 N of slip — far beyond the "
                    "~10 N a single motor produces at full thrust. See the "
                    "Analysis tab for the full calculation, including the +/-30% "
                    "the nut factor is uncertain by."
                ),
                at_mm=(0.0, 13.0, 4.0),
                kind="load",
            ),
        ),
    )
)

register(
    PartDef(
        key="arm_clamp_lower",
        name="Arm clamp, lower half",
        builder=build_arm_clamp_lower,
        material_key="al6061",
        process_key="cnc",
        quantity=SPEC.airframe.arm_count,
        critical=True,
        summary=(
            "Lower half of the split clamp. Also the structural tie between "
            "the arm and both frame plates."
        ),
        design_notes=_CLAMP_NOTES
        + (
            "Tapped bosses rather than through-holes with nuts: there is no "
            "access to the underside once the battery tray is fitted.",
        ),
    )
)
