"""Sheet metal brackets and the purchased electrical items.

The two sheet metal parts exist to demonstrate folded-part design: bend
radius, bend relief, hole standoff from the bend line, and a flat pattern
that can be exported as a DXF for the laser.
"""

from __future__ import annotations

import math

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Circle,
    GeomType,
    Locations,
    Mode,
    Part,
    Plane,
    RectangleRounded,
    add,
    extrude,
    fillet,
)

from drone_demo.config import SPEC
from drone_demo.parts.base import Annotation, PartDef, register

#: K-factor for a 90 deg air bend in 5052-H32, used both here and in
#: flat_pattern_length so the drawing and the CAD can never disagree.
_K_FACTOR = 0.38


def _folded_bracket(
    length: float, width: float, flange_h: float, thick: float, bend_r: float, relief_w: float
) -> Part:
    """A base panel with a flange bent up 90 deg at each short (length) end.

    Local frame: base centred on the origin in X/Y, spanning Z=[0, thick],
    flanges rising in +Z from the two ends at X=+-length/2. Shared between
    the ESC bracket and (with different lengths/flange heights) reused
    conceptually by the battery tray's long walls.
    """
    x0 = length / 2
    with BuildPart() as bp:
        Box(length, width, thick, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((-x0 + thick / 2, 0, 0), (x0 - thick / 2, 0, 0)):
            Box(thick, width, flange_h, align=(Align.CENTER, Align.CENTER, Align.MIN))

        inside_edges = bp.edges().filter_by(
            lambda e: e.geom_type == GeomType.LINE
            and abs(e.center().Z - thick) < 0.01
            and (abs(abs(e.center().X) - (x0 - thick)) < 0.01)
        )
        fillet(inside_edges, radius=bend_r)

        for xs in (-1, 1):
            for ys in (-1, 1):
                x_bend = xs * (x0 - thick)
                y_edge = ys * width / 2
                # Box(..., mode=Mode.SUBTRACT) inside an ambient Locations
                # block cuts at the transformed position. The earlier
                # `Pos(...) * Box(...)` form looked equivalent but wasn't:
                # Box() registers with the active BuildPart the instant it's
                # constructed (at the *untransformed* origin), so the Pos
                # multiply and the later add(..., mode=SUBTRACT) both ran on
                # a copy that had already been unioned in — the relief
                # "cut" was actually adding a stray sliver of material at
                # the origin instead of removing anything at the bend.
                with Locations((x_bend, y_edge, 0)):
                    Box(
                        thick + 2,
                        relief_w,
                        flange_h + thick + 2,
                        align=(Align.CENTER, Align.CENTER, Align.MIN),
                        mode=Mode.SUBTRACT,
                    )

    return bp.part


def esc_bracket_hole_positions() -> list[tuple[float, float]]:
    """The four mounting hole (x, y) positions in the bracket's local frame.

    Exposed so ``assembly.py`` can place the mounting screws at the same
    points the holes actually are, instead of a second, independently
    guessed set of numbers.
    """
    eb = SPEC.esc_bracket
    margin = 4.0 + eb.thickness_mm
    hx = eb.base_length_mm / 2 - margin
    hy = eb.base_width_mm / 2 - margin / 2
    return [(-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy)]


def build_esc_bracket() -> Part:
    """1.5 mm Al 5052 bracket holding one ESC against the arm.

    ``_folded_bracket`` gives the base + two end flanges with real bend
    radii and relief slots; this adds the four mounting holes, kept 4 mm
    clear of the bend tangent (bend tangent sits at X = +-(length/2 - thick)).
    """
    eb = SPEC.esc_bracket
    body = _folded_bracket(
        eb.base_length_mm, eb.base_width_mm, eb.flange_height_mm, eb.thickness_mm,
        eb.bend_radius_mm, eb.relief_width_mm,
    )
    with BuildPart() as bp:
        add(body)
        with BuildSketch(Plane.XY.offset(eb.thickness_mm)):
            with Locations(*esc_bracket_hole_positions()):
                Circle(eb.hole_dia_mm / 2)
        extrude(amount=-eb.thickness_mm, mode=Mode.SUBTRACT)
    return bp.part


def flat_pattern_length(leg_a_mm: float, leg_b_mm: float) -> float:
    """Developed length of a single 90 deg bend, K-factor method.

    ``BA = pi/2 * (r + K*t)`` for a 90 degree bend. Returns
    ``leg_a + leg_b + BA`` measured to the bend tangents.
    """
    eb = SPEC.esc_bracket
    bend_allowance = (math.pi / 2) * (eb.bend_radius_mm + _K_FACTOR * eb.thickness_mm)
    return leg_a_mm + leg_b_mm + bend_allowance


register(
    PartDef(
        key="esc_bracket",
        name="ESC bracket, folded 1.5 mm Al",
        builder=build_esc_bracket,
        material_key="al5052",
        process_key="sheet_metal",
        quantity=SPEC.airframe.arm_count,
        summary="Holds one speed controller in the propwash, where it gets cooled for free.",
        design_notes=(
            "Folded, not machined: the part needs stiffness in one plane and "
            "nothing else, and folding costs about a tenth of machining it.",
            "5052-H32, not 6061. 6061 sheet cracks on a 1t inside bend radius; "
            "5052 takes it without trouble.",
            "Bend relief slots at all four bend ends. Without them the corner "
            "material tears on the brake and the part is scrap.",
            "Mounting holes are 4 mm from the bend tangent. Closer and they "
            "deform into ovals as the bend stretches the material around them.",
        ),
        annotations=(
            Annotation(
                title="Cooling by placement",
                body=(
                    "Mounting the ESC directly under the propeller puts it in "
                    "the strongest airflow on the aircraft. That single "
                    "placement decision removes any need for a heatsink."
                ),
                at_mm=(0.0, 0.0, 6.0),
                kind="interface",
            ),
        ),
    )
)


#: End lips are shorter than the long walls — just enough to locate the
#: battery fore-aft, not carry the strap load. A proportion, not an
#: independent physical dimension, so it lives here rather than in config.
_LIP_HEIGHT_FRACTION = 0.4


def _standoff_relief_points() -> list[tuple[float, float]]:
    """(x, y) of every standoff that actually passes through the tray floor.

    Six standoffs spaced 60 deg apart cannot avoid a rectangular tray that
    spans the vehicle's full length — some will always land inside its
    footprint for any angular offset (verified with a real boolean-overlap
    sweep, see FramePlate.standoff_circle_mm). Rather than fight the
    geometry, the tray floor gets a clearance hole wherever a standoff
    genuinely passes through it, which is exactly what a real sheet metal
    tray would do.
    """
    from drone_demo.parts.frame import standoff_angle_deg

    fp = SPEC.frame_plate
    bt = SPEC.battery_tray
    points = []
    for i in range(fp.standoff_count):
        a = math.radians(standoff_angle_deg(i))
        x = fp.standoff_circle_mm / 2 * math.cos(a)
        y = fp.standoff_circle_mm / 2 * math.sin(a)
        if abs(x) < bt.length_mm / 2 and abs(y) < bt.width_mm / 2:
            points.append((x, y))
    return points


def build_battery_tray() -> Part:
    """1.5 mm Al 5052 tray: long walls carry the strap load, end lips locate it.

    Floor centred on the origin, walls bent up on the two long (Y) edges at
    full ``wall_height_mm``, short lips at the two ends at a fraction of that
    height. Same inside-radius-equals-thickness bend rule as the ESC
    bracket. A strap slot through each long wall, radiused floor cutout in
    the middle for weight.
    """
    bt = SPEC.battery_tray
    lip_h = bt.wall_height_mm * _LIP_HEIGHT_FRACTION
    x0, y0 = bt.length_mm / 2, bt.width_mm / 2

    with BuildPart() as bp:
        Box(
            bt.length_mm, bt.width_mm, bt.thickness_mm,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        # long walls, bent up along the two Y edges
        with Locations((0, -y0 + bt.thickness_mm / 2, 0), (0, y0 - bt.thickness_mm / 2, 0)):
            Box(
                bt.length_mm, bt.thickness_mm, bt.wall_height_mm,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )
        # short end lips
        with Locations((-x0 + bt.thickness_mm / 2, 0, 0), (x0 - bt.thickness_mm / 2, 0, 0)):
            Box(
                bt.thickness_mm, bt.width_mm, lip_h,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )

        inside_edges = bp.edges().filter_by(
            lambda e: e.geom_type == GeomType.LINE
            and abs(e.center().Z - bt.thickness_mm) < 0.01
            and (
                abs(abs(e.center().Y) - (y0 - bt.thickness_mm)) < 0.01
                or abs(abs(e.center().X) - (x0 - bt.thickness_mm)) < 0.01
            )
        )
        fillet(inside_edges, radius=bt.bend_radius_mm)

        # Strap slots cut through the two long walls: sketched on a plane
        # normal to Y (the wall's thickness direction), at the wall's
        # mid-height, and pushed through both walls in one extrude(both=True).
        # Plane.XZ.offset(d) lands the sketch at global Y=-d (verified).
        wall_mid_z = bt.thickness_mm + bt.wall_height_mm * 0.5
        for wall_y in (-y0 + bt.thickness_mm / 2, y0 - bt.thickness_mm / 2):
            with BuildSketch(Plane.XZ.offset(-wall_y)):
                with Locations((0.0, wall_mid_z)):
                    RectangleRounded(
                        bt.strap_slot_width_mm, bt.strap_slot_height_mm,
                        radius=bt.strap_slot_height_mm / 2 - 0.1,
                    )
            extrude(amount=bt.thickness_mm, both=True, mode=Mode.SUBTRACT)

        with BuildSketch(Plane.XY.offset(bt.thickness_mm)):
            RectangleRounded(bt.length_mm * 0.5, bt.width_mm * 0.4, radius=6.0)
        extrude(amount=-bt.thickness_mm, mode=Mode.SUBTRACT)

        relief_pts = _standoff_relief_points()
        if relief_pts:
            with BuildSketch(Plane.XY.offset(bt.thickness_mm)):
                with Locations(*relief_pts):
                    Circle(SPEC.standoff.across_flats_mm / 2 + 1.0)
            extrude(amount=-bt.thickness_mm, mode=Mode.SUBTRACT)

    return bp.part


register(
    PartDef(
        key="battery_tray",
        name="Battery tray, folded 1.5 mm Al",
        builder=build_battery_tray,
        material_key="al5052",
        process_key="sheet_metal",
        quantity=1,
        summary="Locates the battery and spreads its inertia load into the bottom plate.",
        design_notes=(
            "The battery is a third of the all-up mass. In a hard landing it "
            "carries several times its own weight, so it is strapped, not "
            "taped, and the strap load goes into a folded wall rather than a "
            "hole in the laminate.",
            "Fore-aft position of the tray is what trims the centre of gravity "
            "onto the rotor centroid. The slots let it move about 12 mm either "
            "way after the payload is fitted.",
        ),
    )
)


def build_motor() -> Part:
    """Representative 2216-class outrunner. Placeholder solid, not a real product.

    Local frame: motor sits face-down on the mount, Z=0 at the mounting
    face, body extending up in +Z, shaft protruding further above the bell.
    A stator drum plus a slightly larger bell (the rotating outer can) with
    the shaft on top — enough to read as a motor at viewer zoom.
    """
    mo = SPEC.motor
    with BuildPart() as bp:
        with BuildSketch(Plane.XY):
            Circle(mo.body_dia_mm / 2 * 0.7)  # base/stator is narrower than the bell
        extrude(amount=mo.body_height_mm * 0.25)
        with BuildSketch(Plane.XY.offset(mo.body_height_mm * 0.25)):
            Circle(mo.body_dia_mm / 2)
        extrude(amount=mo.body_height_mm * 0.75)
        with BuildSketch(Plane.XY.offset(mo.body_height_mm)):
            Circle(mo.shaft_dia_mm / 2)
        extrude(amount=mo.shaft_length_mm)
    return bp.part


register(
    PartDef(
        key="motor",
        name="Motor, 2216 880 kV",
        builder=build_motor,
        material_key="cots",
        process_key="purchased",
        quantity=SPEC.airframe.arm_count,
        mass_override_g=SPEC.motor.mass_g,
        summary="Purchased outrunner. Modelled only to its interface envelope.",
        design_notes=(
            "Drawn from the vendor's interface dimensions, not reverse "
            "engineered. Only the bolt pattern, boss and envelope matter.",
            "880 kV on 4S with a 10 x 4.5 prop gives about 1050 g of static "
            "thrust per motor, which sets the thrust-to-weight figure in the "
            "analysis report.",
        ),
    )
)


def build_battery() -> Part:
    """4S LiPo as a plain rounded block. Mass from the vendor figure.

    Local frame: centred on the origin in X/Y, sitting on the tray with its
    bottom face at Z=0.
    """
    ba = SPEC.battery
    with BuildPart() as bp:
        Box(
            ba.length_mm, ba.width_mm, ba.height_mm,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        edges = bp.edges().filter_by(Axis.Z)
        fillet(edges, radius=3.0)
    return bp.part


register(
    PartDef(
        key="battery",
        name="Battery, 4S 5000 mAh LiPo",
        builder=build_battery,
        material_key="cots",
        process_key="purchased",
        quantity=1,
        mass_override_g=SPEC.battery.mass_g,
        summary="Modelled as a mass block so the centre of gravity calculation is honest.",
        design_notes=(
            "Included in the CAD purely so the reported centre of gravity means "
            "something. Leaving the heaviest single item out of a CoG "
            "calculation makes the result worthless.",
        ),
    )
)
