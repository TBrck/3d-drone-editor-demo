"""Single source of truth for every dimension in the airframe.

Design intent
-------------
Nothing anywhere else in this package may contain a hard-coded dimension.
Every part module imports ``SPEC`` (or a sub-spec) from here.  Changing the
wheelbase or the tube diameter here must regenerate a fully consistent
assembly, BOM, drawing set and FEA run without touching any other file.

Units
-----
All lengths are millimetres, all masses grams, all forces newtons, all
stresses megapascals (N/mm^2).  This matches the CAD kernel (OCCT works in
mm) and avoids unit conversion anywhere except the glTF exporter, which
converts to metres because glTF is defined in metres.

Coordinate system
-----------------
Right-handed, Z up, X forward (nose), Y to port.  Origin sits at the
geometric centre of the bottom plate's top face.  Arms are at 45 deg to X
in "X configuration".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Airframe top-level targets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Airframe:
    """Top-level configuration of the vehicle."""

    name: str = "AeroFrame X1"
    revision: str = "A"

    #: Motor-shaft to motor-shaft distance across the diagonal.
    wheelbase_mm: float = 450.0
    #: Number of arms. The geometry generator assumes an even number >= 4.
    arm_count: int = 4
    #: Angle of the first arm measured from +X, CCW about +Z.
    first_arm_angle_deg: float = 45.0

    #: Design all-up mass target, used by the statics report.
    target_auw_g: float = 1500.0
    #: Static thrust of one motor/prop combination at 100 % throttle.
    thrust_per_motor_g: float = 1050.0

    @property
    def arm_radius_mm(self) -> float:
        """Distance from vehicle centre to a motor shaft axis."""
        return self.wheelbase_mm / 2.0

    @property
    def arm_angles_deg(self) -> tuple[float, ...]:
        step = 360.0 / self.arm_count
        return tuple(self.first_arm_angle_deg + i * step for i in range(self.arm_count))


# --------------------------------------------------------------------------
# Sub-assemblies
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmTube:
    """Pultruded carbon fibre tube, cut to length. Purchased stock section."""

    outer_dia_mm: float = 16.0
    wall_mm: float = 1.5
    #: Free length of tube between the frame clamp and the motor mount clamp.
    #: Set so that half_width + length + collar/2 lands on the wheelbase
    #: radius (60 + 150 + 15 = 225 mm). ``test_arm_geometry_closes`` guards
    #: this; change the wheelbase and that test tells you what to put here.
    length_mm: float = 150.0
    #: How deep the tube is captured inside each clamp.
    clamp_engagement_mm: float = 28.0

    @property
    def inner_dia_mm(self) -> float:
        return self.outer_dia_mm - 2.0 * self.wall_mm


@dataclass(frozen=True)
class MotorMount:
    """CNC machined 6061-T6 bracket: tube clamp on one end, motor face on top."""

    #: Motor mounting hole pattern (two crossed pairs), 2216-class motor.
    bolt_pattern_a_mm: float = 16.0
    bolt_pattern_b_mm: float = 19.0
    bolt_dia_mm: float = 3.0
    #: Diameter of the motor's centring boss recess.
    boss_dia_mm: float = 7.0
    boss_depth_mm: float = 1.0

    plate_thickness_mm: float = 4.0
    plate_dia_mm: float = 32.0
    #: Wall thickness of the split collar that grips the tube.
    collar_wall_mm: float = 3.5
    collar_length_mm: float = 30.0
    #: Width of the slit that lets the collar close onto the tube.
    collar_slit_mm: float = 1.6
    #: Clamping screw across the slit.
    clamp_screw_dia_mm: float = 3.0

    #: Machining reliefs — real machined parts need these and hiring managers look.
    fillet_mm: float = 2.0
    edge_chamfer_mm: float = 0.5


@dataclass(frozen=True)
class FramePlate:
    """CFRP laminate plate, CNC routed from 2 mm sheet."""

    thickness_mm: float = 2.0
    #: Half-width of the square body section, before corner cuts.
    half_width_mm: float = 60.0
    corner_chamfer_mm: float = 18.0
    #: Bolt circle radius for the standoffs that join top and bottom plate.
    standoff_circle_mm: float = 104.0
    #: Standoff angles, deliberately non-uniform.
    #:
    #: The battery (148 mm long) spans nearly the full plate width, and the
    #: tray floor beneath it is wider still, so no angle within roughly
    #: +/-29 deg of the X axis is usable at this radius, and the arm clamps
    #: at 45/135/225/315 deg rule out roughly +/-15 deg around each of
    #: those. That leaves exactly two 60 deg-wide clear arcs, centred on 90
    #: and 270 deg. This set — three standoffs spread across each arc —
    #: was verified clean against the clamps, the tray and the battery with
    #: a real boolean-interference sweep (see test_no_interference_
    #: between_instances); it is not a formula and should not be replaced
    #: with one without re-running that check.
    standoff_angles_deg: tuple[float, ...] = (70.0, 90.0, 110.0, 250.0, 270.0, 290.0)
    #: Lightening pockets. Set to 0 to disable.
    lightening_hole_dia_mm: float = 14.0

    @property
    def standoff_count(self) -> int:
        return len(self.standoff_angles_deg)

    @property
    def arm_attach_radius_mm(self) -> float:
        """Distance from the plate centre to the flat chamfered corner face.

        The plate is a square with each corner cut back by
        ``corner_chamfer_mm``; that cut face is where the arm clamp lands,
        centred on the 45 deg diagonal. Both the frame plate's arm bolt
        holes and the assembly's arm placement read this property, so the
        two can never drift apart.
        """
        return (self.half_width_mm - self.corner_chamfer_mm / 2) * math.sqrt(2)


@dataclass(frozen=True)
class ArmClamp:
    """Two-piece split clamp joining the arm tube to the frame plates.

    The two clamp bolts sit outboard of the tube channel, symmetric about
    Y=0, spaced ``bolt_spacing_mm`` apart. ``width_mm`` must clear that
    spacing with room for the hole wall on each side
    (``test_clamp_width_fits_bolts`` guards this): 26 + 2 x 3 mm margin = 32.
    """

    length_mm: float = 34.0
    width_mm: float = 32.0
    #: Thickness of each of the two halves at the tube.
    half_thickness_mm: float = 9.0
    bolt_dia_mm: float = 3.0
    bolt_spacing_mm: float = 26.0
    fillet_mm: float = 1.5
    #: Square pattern of the four tapped bosses on the lower half that pick
    #: up the frame plate. Shared with FramePlate's arm bolt holes so the
    #: two always land on the same points.
    boss_pattern_mm: float = 18.0


@dataclass(frozen=True)
class LandingLeg:
    """FDM printed leg (PA12-CF). Designed as the sacrificial crash element."""

    height_mm: float = 95.0
    #: Outward splay of the foot relative to the tube axis.
    splay_deg: float = 12.0
    strut_width_mm: float = 14.0
    strut_thickness_mm: float = 6.0
    #: Deliberate section reduction: the leg is meant to break here, not the arm.
    fuse_thickness_mm: float = 3.6
    fuse_height_mm: float = 30.0
    #: Printed with a 45 deg lead-in so it needs no support material.
    overhang_relief_deg: float = 45.0


@dataclass(frozen=True)
class LandingFoot:
    """Injection moulded TPU foot, press-fits onto the leg."""

    dia_mm: float = 22.0
    height_mm: float = 14.0
    wall_mm: float = 2.0
    #: Draft angle for mould release — a detail worth calling out in the viewer.
    draft_deg: float = 1.5


@dataclass(frozen=True)
class EscBracket:
    """Sheet metal bracket, 1.5 mm Al 5052, two 90 deg bends."""

    thickness_mm: float = 1.5
    #: Inside bend radius = 1 x thickness for 5052.
    bend_radius_mm: float = 1.5
    base_length_mm: float = 42.0
    base_width_mm: float = 26.0
    flange_height_mm: float = 12.0
    #: Bend relief slot width at the corner of each flange.
    relief_width_mm: float = 2.0
    hole_dia_mm: float = 3.2


@dataclass(frozen=True)
class BatteryTray:
    """Sheet metal tray, 1.5 mm Al 5052, four bends, welded corners omitted."""

    thickness_mm: float = 1.5
    bend_radius_mm: float = 1.5
    length_mm: float = 152.0
    width_mm: float = 54.0
    wall_height_mm: float = 18.0
    strap_slot_width_mm: float = 26.0
    strap_slot_height_mm: float = 4.0


@dataclass(frozen=True)
class Standoff:
    """Turned aluminium standoff, M3 female both ends. Off-the-shelf.

    ``length_mm`` sets the frame box height and must clear the battery
    stack: tray floor (1.5 mm) + battery height (35 mm) = 36.5 mm minimum.
    ``test_no_interference_between_instances`` caught this at the original
    35 mm, which put the battery straight through the top plate.
    """

    length_mm: float = 38.0
    across_flats_mm: float = 6.0
    thread: str = "M3"


@dataclass(frozen=True)
class Motor:
    """Purchased BLDC. Modelled as a representative solid, not a real product."""

    body_dia_mm: float = 27.8
    body_height_mm: float = 22.0
    bell_gap_mm: float = 0.6
    shaft_dia_mm: float = 4.0
    shaft_length_mm: float = 12.0
    mass_g: float = 62.0
    kv: int = 880


@dataclass(frozen=True)
class Propeller:
    """Injection moulded glass-filled nylon prop, modelled as a swept blade."""

    diameter_in: float = 10.0
    pitch_in: float = 4.5
    blade_count: int = 2
    hub_dia_mm: float = 16.0
    hub_thickness_mm: float = 7.0
    root_chord_mm: float = 22.0
    tip_chord_mm: float = 12.0
    #: Blade twist from root to tip, positive = washout.
    twist_deg: float = 14.0

    @property
    def diameter_mm(self) -> float:
        return self.diameter_in * 25.4


@dataclass(frozen=True)
class Battery:
    """4S LiPo, treated as a mass block for CoG and endurance calculations."""

    length_mm: float = 148.0
    width_mm: float = 50.0
    height_mm: float = 35.0
    mass_g: float = 530.0
    capacity_mah: int = 5000
    cells: int = 4
    nominal_v_per_cell: float = 3.7
    #: Fraction of capacity usable before the low-voltage cutoff.
    usable_fraction: float = 0.80


@dataclass(frozen=True)
class Fastener:
    """Generic ISO 4762 socket head cap screw used throughout."""

    thread: str = "M3"
    nominal_dia_mm: float = 3.0
    head_dia_mm: float = 5.5
    head_height_mm: float = 3.0
    #: Clearance hole per ISO 273 medium series.
    clearance_dia_mm: float = 3.4
    #: Property class 8.8 steel.
    proof_load_n: float = 3400.0


# --------------------------------------------------------------------------
# Load cases used by analysis/statics.py and analysis/fea.py
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadCase:
    """One analysis load case.

    ``factor`` multiplies the relevant reference load (thrust or weight).
    ``target_sf`` is the safety factor the design must achieve; the report
    flags anything below it.
    """

    key: str
    title: str
    description: str
    factor: float
    target_sf: float


LOAD_CASES: tuple[LoadCase, ...] = (
    LoadCase(
        key="hover",
        title="Steady hover",
        description="Each motor carries a quarter of the all-up weight.",
        factor=1.0,
        target_sf=4.0,
    ),
    LoadCase(
        key="max_thrust",
        title="Full throttle climb",
        description="All four motors at 100 % static thrust simultaneously.",
        factor=1.0,
        target_sf=2.0,
    ),
    LoadCase(
        key="hard_landing",
        title="Hard landing, 0.5 m drop",
        description=(
            "Vertical drop onto one leg, energy absorbed over the leg's "
            "elastic deflection. Sizes the printed leg and the arm root."
        ),
        factor=1.0,
        target_sf=1.5,
    ),
)


# --------------------------------------------------------------------------
# Build / export settings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportSettings:
    """Tessellation and output settings.

    ``linear_deflection`` is the chord error in mm used when converting BREP
    to triangles.  0.06 mm keeps a 16 mm tube visibly round while staying
    under a few MB for the whole assembly.
    """

    linear_deflection_mm: float = 0.06
    angular_deflection_rad: float = 0.25
    #: glTF is metres and Y-up; the exporter applies this scale and a -90 deg
    #: rotation about X.  Do not bake the rotation into the CAD.
    gltf_scale: float = 0.001
    #: Maximum triangles before the exporter warns.
    triangle_budget: int = 900_000
    #: Explode animation distance multiplier applied to unit explode vectors.
    explode_distance_mm: float = 120.0


@dataclass(frozen=True)
class Spec:
    """The complete machine specification."""

    airframe: Airframe = field(default_factory=Airframe)
    arm_tube: ArmTube = field(default_factory=ArmTube)
    motor_mount: MotorMount = field(default_factory=MotorMount)
    frame_plate: FramePlate = field(default_factory=FramePlate)
    arm_clamp: ArmClamp = field(default_factory=ArmClamp)
    landing_leg: LandingLeg = field(default_factory=LandingLeg)
    landing_foot: LandingFoot = field(default_factory=LandingFoot)
    esc_bracket: EscBracket = field(default_factory=EscBracket)
    battery_tray: BatteryTray = field(default_factory=BatteryTray)
    standoff: Standoff = field(default_factory=Standoff)
    motor: Motor = field(default_factory=Motor)
    propeller: Propeller = field(default_factory=Propeller)
    battery: Battery = field(default_factory=Battery)
    fastener: Fastener = field(default_factory=Fastener)
    export: ExportSettings = field(default_factory=ExportSettings)


#: Import this. Do not instantiate ``Spec`` elsewhere.
SPEC = Spec()
