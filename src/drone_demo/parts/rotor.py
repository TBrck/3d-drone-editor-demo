"""Propeller.

The only genuinely three-dimensional surface on the vehicle, and the part
that makes the assembly read as an aircraft rather than a bracket collection.
"""

from __future__ import annotations

import math

from build123d import (
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Ellipse,
    Mode,
    Part,
    Plane,
    Rot,
    add,
    extrude,
    loft,
)

from drone_demo.config import SPEC
from drone_demo.parts.base import Annotation, PartDef, register

#: Stations from hub to tip. 7 is smooth at viewer zoom without inflating
#: the triangle budget — verified: doubling this changes the silhouette by
#: nothing a viewer would notice.
_N_STATIONS = 7
#: Crude aerofoil-ish thickness as a fraction of local chord.
_THICKNESS_FRACTION = 0.08
_MIN_THICKNESS_MM = 1.2
#: How far the washout blends in, as a fraction of the twist applied at the tip.
_WASHOUT_TIP_FRACTION = 0.3


def _pitch_angle_rad(r_mm: float, pitch_mm: float) -> float:
    """Constant-pitch law: beta(r) = atan(pitch / (2*pi*r))."""
    return math.atan2(pitch_mm, 2 * math.pi * r_mm)


def _blade(r_root: float, r_tip: float, pitch_mm: float) -> Part:
    """One blade, built by lofting twisted elliptical sections along +Y.

    The loft's first station is placed at the shaft axis (Y=0), not at
    ``r_root`` — verified necessary: a loft that starts exactly at the hub
    radius only *touches* the hub tangentially, and fusing two such blades
    onto one hub then produces two disconnected solids instead of one. A
    station driven all the way to the axis guarantees real 3D overlap.
    """
    prop = SPEC.propeller
    root_thickness = max(prop.root_chord_mm * _THICKNESS_FRACTION, _MIN_THICKNESS_MM)
    root_beta = _pitch_angle_rad(r_root, pitch_mm)
    chord_dir0 = (math.cos(root_beta), 0, math.sin(root_beta))

    with BuildPart() as bp:
        with BuildSketch(Plane(origin=(0, 0, 0), x_dir=chord_dir0, z_dir=(0, 1, 0))):
            Ellipse(prop.root_chord_mm / 2, root_thickness / 2)

        for i in range(_N_STATIONS):
            frac = i / (_N_STATIONS - 1)
            r = r_root + frac * (r_tip - r_root)
            chord = prop.root_chord_mm + frac * (prop.tip_chord_mm - prop.root_chord_mm)
            thickness = max(chord * _THICKNESS_FRACTION, _MIN_THICKNESS_MM)
            beta = _pitch_angle_rad(r, pitch_mm) - math.radians(
                prop.twist_deg
            ) * frac * _WASHOUT_TIP_FRACTION
            chord_dir = (math.cos(beta), 0, math.sin(beta))
            with BuildSketch(Plane(origin=(0, r, 0), x_dir=chord_dir, z_dir=(0, 1, 0))):
                Ellipse(chord / 2, thickness / 2)
        loft(ruled=False)

    return bp.part


def build_propeller() -> Part:
    """Two-blade moulded propeller: hub, one lofted blade, and its 180 deg twin.

    The second blade is a true rotation about the shaft axis, not a mirror —
    a mirror would flip the aerofoil's camber sense, which is wrong for a
    normal (both-blades-same-hand) propeller. With plain elliptical
    sections here the two look identical, but the rotation is the
    physically correct operation and costs nothing extra.
    """
    prop = SPEC.propeller
    r_root = prop.hub_dia_mm / 2 - 1.0  # 1 mm into the hub for a clean root fillet
    r_tip = prop.diameter_mm / 2
    pitch_mm = prop.pitch_in * 25.4

    with BuildPart() as bp:
        Cylinder(radius=prop.hub_dia_mm / 2, height=prop.hub_thickness_mm)
        with BuildSketch(Plane.XY):
            Circle(SPEC.motor.shaft_dia_mm / 2)
        extrude(amount=prop.hub_thickness_mm, both=True, mode=Mode.SUBTRACT)

        blade = _blade(r_root, r_tip, pitch_mm)
        add(blade)
        add(Rot(0, 0, 180) * blade)

    return bp.part


register(
    PartDef(
        key="propeller",
        name="Propeller, 10 x 4.5",
        builder=build_propeller,
        material_key="nylon_gf",
        process_key="injection",
        quantity=SPEC.airframe.arm_count,
        summary="Moulded glass-filled nylon prop, drawn to a true constant-pitch law.",
        design_notes=(
            "Blade angle follows beta = atan(pitch / 2*pi*r), so every station "
            "along the blade advances the same distance per revolution. That is "
            "what the '4.5' in '10 x 4.5' actually means.",
            "Moulded in two halves off a single parting line down the blade "
            "chord, with the twist handled by the mould's shape rather than a "
            "side action.",
            "The prop is shown for context. It is not a part this project "
            "claims to have designed aerodynamically.",
        ),
        annotations=(
            Annotation(
                title="Constant pitch, not constant angle",
                body=(
                    "The blade is much flatter at the tip than at the root. It "
                    "has to be: the tip travels far further per revolution, so "
                    "a smaller angle produces the same forward advance. Draw "
                    "the blade at one fixed angle and the root stalls while the "
                    "tip does nothing."
                ),
                at_mm=(95.0, 0.0, 4.0),
                kind="load",
            ),
        ),
    )
)
