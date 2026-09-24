"""Central frame: top plate, bottom plate, standoffs.

Local convention: plates lie in the XY plane, centred on the origin, growing
in +Z from Z = 0.  The assembly stacks them apart in Z.
"""

from __future__ import annotations

import math

from build123d import (
    BuildLine,
    BuildPart,
    BuildSketch,
    Circle,
    Locations,
    Mode,
    Part,
    Plane,
    Polyline,
    RectangleRounded,
    RegularPolygon,
    extrude,
    make_face,
)

from drone_demo.config import SPEC
from drone_demo.parts.base import Annotation, PartDef, register


def _octagon_points(half_width: float, chamfer: float) -> list[tuple[float, float]]:
    """Vertices of a square with all four corners cut back by ``chamfer``."""
    w = half_width
    c = chamfer
    return [
        (w - c, w), (w, w - c),
        (w, -(w - c)), (w - c, -w),
        (-(w - c), -w), (-w, -(w - c)),
        (-w, w - c), (-(w - c), w),
    ]


def standoff_angle_deg(index: int) -> float:
    """Angle of the ``index``-th standoff — see ``FramePlate.standoff_angles_deg``.

    Exposed so ``assembly.py`` places the physical standoffs at exactly
    these angles; the plate's holes and the parts can never drift apart.
    """
    return SPEC.frame_plate.standoff_angles_deg[index]


def _plate(is_top: bool) -> Part:
    """Shared outline for both CFRP plates, built in local frame Z=[0, thickness].

    The octagonal outline, the standoff bolt circle and the four arm bolt
    groups are common to both; ``is_top`` only changes the central feature.
    """
    fp = SPEC.frame_plate
    ac = SPEC.arm_clamp

    with BuildPart() as bp:
        with BuildSketch(Plane.XY):
            with BuildLine():
                Polyline(*_octagon_points(fp.half_width_mm, fp.corner_chamfer_mm), close=True)
            make_face()
        extrude(amount=fp.thickness_mm)

        standoff_pts = [
            (
                fp.standoff_circle_mm / 2 * math.cos(math.radians(standoff_angle_deg(i))),
                fp.standoff_circle_mm / 2 * math.sin(math.radians(standoff_angle_deg(i))),
            )
            for i in range(fp.standoff_count)
        ]
        with BuildSketch(Plane.XY.offset(fp.thickness_mm)):
            with Locations(*standoff_pts):
                Circle(SPEC.fastener.clearance_dia_mm / 2)
        extrude(amount=-fp.thickness_mm, mode=Mode.SUBTRACT)

        half_pat = ac.boss_pattern_mm / 2
        arm_holes: list[tuple[float, float]] = []
        for angle_deg in SPEC.airframe.arm_angles_deg:
            a = math.radians(angle_deg)
            cos_a, sin_a = math.cos(a), math.sin(a)
            cx = fp.arm_attach_radius_mm * cos_a
            cy = fp.arm_attach_radius_mm * sin_a
            # Boss pattern is defined in the clamp's local (X along arm, Y
            # across); rotate each corner by the same angle the arm itself
            # is rotated by in assembly.py, so the holes land under the bosses.
            for lx in (-half_pat, half_pat):
                for ly in (-half_pat, half_pat):
                    arm_holes.append((cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a))
        with BuildSketch(Plane.XY.offset(fp.thickness_mm)):
            with Locations(*arm_holes):
                Circle(SPEC.fastener.clearance_dia_mm / 2)
        extrude(amount=-fp.thickness_mm, mode=Mode.SUBTRACT)

        if is_top:
            with BuildSketch(Plane.XY.offset(fp.thickness_mm)):
                RectangleRounded(24.0, 12.0, radius=3.0)
            extrude(amount=-fp.thickness_mm, mode=Mode.SUBTRACT)

            if fp.lightening_hole_dia_mm > 0:
                # Placed at 0/180 deg: 90 deg clear of every arm
                # (45/135/225/315 deg) and outside the standoff pattern,
                # which clusters near 90/270 deg (FramePlate.standoff_angles_deg)
                # to dodge the battery on the X axis — the two constraints
                # happen to leave exactly this axis free.
                light_radius = fp.standoff_circle_mm / 2 - 10.0
                light_pts = [
                    (
                        light_radius * math.cos(math.radians(a)),
                        light_radius * math.sin(math.radians(a)),
                    )
                    for a in (0.0, 180.0)
                ]
                with BuildSketch(Plane.XY.offset(fp.thickness_mm)):
                    with Locations(*light_pts):
                        Circle(fp.lightening_hole_dia_mm / 2)
                extrude(amount=-fp.thickness_mm, mode=Mode.SUBTRACT)
        else:
            bt = SPEC.battery_tray
            strap_x = bt.length_mm / 2 - 20.0
            strap_pts = [(sx, 0.0) for sx in (-strap_x, strap_x)]
            with BuildSketch(Plane.XY.offset(fp.thickness_mm)):
                with Locations(*strap_pts):
                    RectangleRounded(
                        bt.strap_slot_height_mm, bt.strap_slot_width_mm, radius=1.5
                    )
            extrude(amount=-fp.thickness_mm, mode=Mode.SUBTRACT)

    return bp.part


def build_top_plate() -> Part:
    return _plate(is_top=True)


def build_bottom_plate() -> Part:
    return _plate(is_top=False)


register(
    PartDef(
        key="top_plate",
        name="Top plate, 2 mm CFRP",
        builder=build_top_plate,
        material_key="cfrp_plate",
        process_key="composite_cut",
        quantity=1,
        critical=True,
        summary="Upper shear panel of the frame box. Routed from 2 mm woven laminate.",
        design_notes=(
            "The two plates and the six standoffs form a box that carries the "
            "arm reaction moments as a couple: tension in one plate, "
            "compression in the other. Neither plate is loaded in bending.",
            "Lightening pockets are placed only where the shear flow is low — "
            "between the standoffs, never on the line between an arm clamp and "
            "the frame centre.",
            "No countersunk holes. Countersinking a 2 mm laminate removes half "
            "the thickness at exactly the point the bolt loads it; a washer "
            "spreading the head load is lighter and much stronger.",
        ),
        annotations=(
            Annotation(
                title="Why two thin plates, not one thick one",
                body=(
                    "Separating the plates by 35 mm makes the frame roughly 300 "
                    "times stiffer in torsion than the same mass of material in "
                    "a single plate. Stiffness here is what keeps the flight "
                    "controller's gyro reading the airframe and not a "
                    "structural vibration mode."
                ),
                at_mm=(0.0, 0.0, 2.0),
                kind="load",
            ),
        ),
    )
)

register(
    PartDef(
        key="bottom_plate",
        name="Bottom plate, 2 mm CFRP",
        builder=build_bottom_plate,
        material_key="cfrp_plate",
        process_key="composite_cut",
        quantity=1,
        critical=True,
        summary="Lower shear panel. Also the mounting face for the battery tray.",
        design_notes=(
            "Kept solid under the battery so the strap load spreads into the "
            "panel instead of tearing out at a hole edge.",
            "Strap slots have a 3 mm radius at each end. A square-ended slot in "
            "a laminate is a delamination starter.",
        ),
    )
)


def build_standoff() -> Part:
    """Turned aluminium standoff, hex section, tapped M3 both ends.

    Axis along +Z, spanning local Z=[0, length_mm], with a 2.5 mm tapping
    drill bored 8 mm deep into each end. Modelled as a plain bore — a
    cosmetic helical thread would multiply the triangle count for no visual
    gain at viewer zoom.
    """
    so = SPEC.standoff
    tap_dia = 2.5
    tap_depth = 8.0
    with BuildPart() as bp:
        with BuildSketch(Plane.XY):
            RegularPolygon(radius=so.across_flats_mm / 2, side_count=6, major_radius=False)
        extrude(amount=so.length_mm)

        with BuildSketch(Plane.XY):
            Circle(tap_dia / 2)
        extrude(amount=tap_depth, mode=Mode.SUBTRACT)

        with BuildSketch(Plane.XY.offset(so.length_mm)):
            Circle(tap_dia / 2)
        extrude(amount=-tap_depth, mode=Mode.SUBTRACT)
    return bp.part


register(
    PartDef(
        key="standoff",
        name="Standoff, M3 x 35 hex",
        builder=build_standoff,
        material_key="al6061",
        process_key="purchased",
        quantity=SPEC.frame_plate.standoff_count,
        critical=True,
        summary="Sets the frame box height and carries the compression between the plates.",
        design_notes=(
            "Catalogue part. Six of them rather than four: the extra pair sits "
            "on the pitch axis where the frame box would otherwise be free to "
            "parallelogram.",
            "Hex section so it can be held while the bolts are torqued.",
        ),
    )
)
