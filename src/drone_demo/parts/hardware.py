"""Fasteners.

Modelled with plain cylindrical shanks, no helical thread. A modelled thread
on 60-odd screws would dominate the triangle budget and change nothing a
viewer can see. The drawings and BOM carry the thread callout instead.
"""

from __future__ import annotations

from functools import partial

from build123d import (
    Align,
    BuildPart,
    BuildSketch,
    Cylinder,
    Mode,
    Part,
    Plane,
    RegularPolygon,
    extrude,
)

from drone_demo.config import SPEC
from drone_demo.parts.base import Annotation, PartDef, register


def build_screw(length_mm: float) -> Part:
    """ISO 4762 socket head cap screw, ``length_mm`` under the head.

    Head bearing face at Z=0, head rising in +Z, shank running ``length_mm``
    in -Z. Hex socket is cosmetic (one shallow extrusion) — no thread.
    """
    f = SPEC.fastener
    socket_af = f.nominal_dia_mm * 0.6  # across-flats, roughly to scale
    socket_depth = f.head_height_mm * 0.5

    with BuildPart() as bp:
        Cylinder(
            radius=f.head_dia_mm / 2, height=f.head_height_mm,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        Cylinder(
            radius=f.nominal_dia_mm / 2, height=length_mm,
            align=(Align.CENTER, Align.CENTER, Align.MAX),
        )
        with BuildSketch(Plane.XY.offset(f.head_height_mm)):
            RegularPolygon(radius=socket_af / 2, side_count=6, major_radius=False)
        extrude(amount=-socket_depth, mode=Mode.SUBTRACT)

    return bp.part


_ARMS = SPEC.airframe.arm_count

register(
    PartDef(
        key="screw_m3x8",
        name="Screw, M3 x 8 SHCS",
        builder=partial(build_screw, 8.0),
        material_key="steel_a2",
        process_key="purchased",
        # 4 per motor, 2 per ESC bracket.
        quantity=_ARMS * 6,
        summary="Motor and bracket fixings.",
        design_notes=(
            "One thread size across the whole airframe. A field repair then "
            "needs one driver and one spares box, which matters far more than "
            "the few grams an optimised fastener schedule would save.",
        ),
    )
)

register(
    PartDef(
        key="screw_m3x12",
        name="Screw, M3 x 12 SHCS",
        builder=partial(build_screw, 12.0),
        material_key="steel_a2",
        process_key="purchased",
        # 2 per arm clamp, 4 per arm into the plates, 1 per motor mount collar.
        quantity=_ARMS * 7 + SPEC.frame_plate.standoff_count * 2,
        critical=True,
        summary="Structural fixings: arm clamps, plate stack, standoffs.",
        design_notes=(
            "A2-70 stainless, not the steel the cheap kits ship. Corrosion "
            "resistance matters on a vehicle that gets flown in wet grass.",
            "Torqued to 1.2 Nm with thread lock. Under-torque is the failure "
            "mode here, not over-torque: a loose clamp lets the tube creep.",
        ),
        annotations=(
            Annotation(
                title="Preload is the design variable",
                body=(
                    "These bolts are never loaded in shear by design. Their job "
                    "is to generate clamp force so the joint carries load by "
                    "friction. Assembly torque is a specified engineering "
                    "quantity here, not a fitter's judgement."
                ),
                at_mm=(0.0, 0.0, 0.0),
                kind="tolerance",
            ),
        ),
    )
)
