"""Landing gear: printed leg and moulded foot.

Local convention: the leg's tube clamp sits at the origin with the tube axis
along X; the leg runs down in -Z and splays out in +Y by ``splay_deg``.
"""

from __future__ import annotations

import math

from build123d import (
    Axis,
    BuildPart,
    BuildSketch,
    Circle,
    GeomType,
    Locations,
    Mode,
    Part,
    Plane,
    Rectangle,
    RectangleRounded,
    add,
    extrude,
    fillet,
    loft,
    revolve,
)

from drone_demo.config import SPEC
from drone_demo.parts.base import Annotation, PartDef, register

#: Wrap angle of the C-shaped snap collar. 360 - 200 = 160 deg opening, wide
#: enough to spring over the tube during assembly and narrow enough to hold
#: on once seated.
_COLLAR_WRAP_DEG = 200.0
_COLLAR_LENGTH_X_MM = 16.0
#: Radial clearance so the collar snaps over the tube rather than binding.
_COLLAR_CLEARANCE_MM = 0.3
_SPIGOT_LENGTH_MM = 10.0
#: Corner radius on the loft's rounded-rectangle stations, as a fraction of
#: the smaller station dimension — keeps it proportional as the leg tapers.
_STATION_FILLET_FRACTION = 0.15


def _leg_collar(collar_or: float, collar_ir: float) -> Part:
    """C-shaped snap collar, built by revolving a wall cross-section about X.

    The revolve profile starts at +Z (angle 90 deg) and sweeps
    ``_COLLAR_WRAP_DEG``, which — verified empirically against this exact
    profile placement — leaves solid material centred near -Y/-Z and a gap
    centred near +Z. That puts material where the strut attaches (-Z) and
    the opening where a clip needs it (roughly opposite).
    """
    with BuildPart() as bp:
        with BuildSketch(Plane.XZ):
            with Locations((_COLLAR_LENGTH_X_MM / 2, (collar_ir + collar_or) / 2)):
                Rectangle(_COLLAR_LENGTH_X_MM, collar_or - collar_ir)
        revolve(axis=Axis((0, 0, 0), (1, 0, 0)), revolution_arc=_COLLAR_WRAP_DEG)
    return bp.part


def landing_leg_collar_bore_radius() -> float:
    """Radius of the snap collar's inner (bore) surface, local frame.

    Exposed so :mod:`drone_demo.analysis.fea` can select the restraint
    region (the collar's inner face, per ``FEA_CASES``) without
    recomputing the collar geometry independently.
    """
    return SPEC.arm_tube.outer_dia_mm / 2 + _COLLAR_CLEARANCE_MM


def landing_leg_spigot_tip() -> tuple[float, float, float]:
    """(x, y, z) of the spigot's free end, local frame — where the foot's
    reaction load is applied in the FEA case.
    """
    leg = SPEC.landing_leg
    t = SPEC.arm_tube
    collar_or = t.outer_dia_mm / 2 + 3.0
    collar_ir = t.outer_dia_mm / 2 + _COLLAR_CLEARANCE_MM
    z_top = -(collar_ir + collar_or) / 2
    tan_splay = math.tan(math.radians(leg.splay_deg))
    y_tip = leg.height_mm * tan_splay
    z_tip = z_top - leg.height_mm - _SPIGOT_LENGTH_MM
    return (0.0, y_tip, z_tip)


def build_landing_leg() -> Part:
    """FDM printed leg: snap collar, tapered strut, press-fit spigot.

    The strut is a loft through five rounded-rectangle stations along the
    splayed axis, so the fuse taper is a continuous surface rather than a
    stepped one — the stress concentration lands in the middle of the fuse,
    where it's meant to, not at a sharp step.

    All three sub-shapes are built to genuinely overlap in 3D (not just
    touch) before the union — verified necessary: OCCT's boolean union of
    two solids that are merely tangent can leave two separate solids instead
    of fusing them.
    """
    leg = SPEC.landing_leg
    foot = SPEC.landing_foot
    t = SPEC.arm_tube

    collar_or = t.outer_dia_mm / 2 + 3.0  # 3 mm wall, matches the design note
    collar_ir = t.outer_dia_mm / 2 + _COLLAR_CLEARANCE_MM
    spigot_dia = foot.dia_mm - 2 * foot.wall_mm - 0.15  # interference press fit

    tan_splay = math.tan(math.radians(leg.splay_deg))
    # Strut springs from inside the collar wall band, not merely tangent to
    # its outer surface, so the loft's top station truly overlaps the collar.
    z_top = -(collar_ir + collar_or) / 2

    def y_at(t_frac: float) -> float:
        return t_frac * leg.height_mm * tan_splay

    def z_at(t_frac: float) -> float:
        return z_top - t_frac * leg.height_mm

    fuse_frac = leg.fuse_height_mm / leg.height_mm
    t_fuse_start = 0.5 - fuse_frac / 2
    t_fuse_end = 0.5 + fuse_frac / 2
    stations = (0.0, t_fuse_start, 0.5, t_fuse_end, 1.0)
    thicknesses = (
        leg.strut_thickness_mm,
        leg.strut_thickness_mm,
        leg.fuse_thickness_mm,
        leg.strut_thickness_mm,
        leg.strut_thickness_mm,
    )

    with BuildPart() as strut_bp:
        for t_frac, thick in zip(stations, thicknesses, strict=True):
            with BuildSketch(Plane.XY.offset(z_at(t_frac))):
                with Locations((0.0, y_at(t_frac))):
                    RectangleRounded(
                        leg.strut_width_mm,
                        thick,
                        radius=min(leg.strut_width_mm, thick) * _STATION_FILLET_FRACTION,
                    )
        loft(ruled=False)

    with BuildPart() as bp:
        add(_leg_collar(collar_or, collar_ir))
        add(strut_bp.part)
        with BuildSketch(Plane.XY.offset(z_at(1.0))):
            with Locations((0.0, y_at(1.0))):
                Circle(spigot_dia / 2)
        extrude(amount=-_SPIGOT_LENGTH_MM)

    return bp.part


register(
    PartDef(
        key="landing_leg",
        name="Landing leg, printed PA12-CF",
        builder=build_landing_leg,
        material_key="pa12cf",
        process_key="fdm",
        quantity=SPEC.airframe.arm_count,
        critical=True,
        summary=(
            "Absorbs the landing energy and is designed to be the first thing "
            "that breaks in a crash."
        ),
        design_notes=(
            "The tapered fuse section is not a weight saving. It fixes where a "
            "hard landing fails: a 4 EUR printed leg, replaceable in an hour, "
            "instead of a carbon arm or a motor bell.",
            "Printed standing on the foot spigot. Layer lines then run across "
            "the bending load rather than along it, which is the difference "
            "between a leg that bends and one that shears at a layer line.",
            "The snap collar means the legs come off without tools between "
            "flights, which is what actually gets done at a test site.",
            "Whole part prints without support: no face overhangs more than "
            "45 degrees, verified geometrically in the test suite.",
        ),
        annotations=(
            Annotation(
                title="Designed to break here",
                body=(
                    "The section is deliberately thinned to about 60 % over "
                    "30 mm. In a 0.5 m drop this section yields first and "
                    "absorbs the energy, protecting the arm root behind it. "
                    "Choosing the failure point is cheaper than trying to "
                    "prevent failure everywhere."
                ),
                at_mm=(0.0, 8.0, -50.0),
                kind="load",
            ),
        ),
    )
)


def build_landing_foot() -> Part:
    """Injection moulded TPU foot: a drafted, hollow cup.

    Local frame: axis along Z, open top (the full ``dia_mm``) at Z=``height_mm``,
    domed bottom at Z=0 — mould pulls upward out of the cavity, so the wall
    narrows going down (``extrude(..., taper=draft_deg)``, verified to taper
    in the extrude direction). Bottom rim gets a 3 mm fillet for the domed
    contact face; that fillet is what turns a flat-bottomed cup into a dome.
    """
    foot = SPEC.landing_foot
    with BuildPart() as bp:
        with BuildSketch(Plane.XY.offset(foot.height_mm)):
            Circle(foot.dia_mm / 2)
        extrude(amount=-foot.height_mm, taper=foot.draft_deg)

        with BuildSketch(Plane.XY.offset(foot.height_mm)):
            Circle(foot.dia_mm / 2 - foot.wall_mm)
        extrude(amount=-(foot.height_mm - foot.wall_mm), taper=foot.draft_deg, mode=Mode.SUBTRACT)

        bottom_face = bp.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0]
        bottom_rim = bottom_face.edges().filter_by(GeomType.CIRCLE)
        fillet(bottom_rim, radius=3.0)

    return bp.part


register(
    PartDef(
        key="landing_foot",
        name="Landing foot, moulded TPU",
        builder=build_landing_foot,
        material_key="tpu",
        process_key="injection",
        quantity=SPEC.airframe.arm_count,
        summary="Soft contact pad. Press fits onto the leg spigot.",
        design_notes=(
            "1.5 degrees of draft on every vertical wall, uniform 2 mm section, "
            "single parting line, no side actions — the cheapest mould that can "
            "make this shape.",
            "0.15 mm interference on the spigot. In TPU that is a press fit "
            "that survives vibration but can still be pulled off by hand.",
        ),
        annotations=(
            Annotation(
                title="Uniform wall",
                body=(
                    "The wall is 2 mm everywhere. A thick spot would cool last, "
                    "shrink, and leave a sink mark and a void; that is the "
                    "single most common moulded-part defect and it is a design "
                    "decision, not a process problem."
                ),
                at_mm=(0.0, 0.0, -7.0),
                kind="dfm",
            ),
        ),
    )
)
