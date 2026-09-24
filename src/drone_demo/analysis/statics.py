"""Closed-form checks on the load path.

These are the calculations that would go on a design review slide: they are
quick, they are checkable by hand, and they are what sizes the parts. The FEA
in :mod:`.fea` exists to confirm them, not to replace them.

Every function returns a :class:`Check` carrying the applied value, the
allowable, the resulting safety factor, and the formula as a string. The
formula string is rendered in the web report so a reader can follow the
reasoning rather than being asked to trust a number.

Units throughout: mm, N, MPa (= N/mm^2) — the same system as
:mod:`drone_demo.config`, chosen so no conversion factor is ever silently
missing. Frequencies and power convert to SI (m, kg, s) locally, where noted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from drone_demo.config import LOAD_CASES, SPEC
from drone_demo.materials import material

_G = 9.80665  # m/s^2
#: Assembly torque used on every M3x12 structural bolt (matches the design
#: note in parts/arm.py — both must be changed together).
_ASSEMBLY_TORQUE_NM = 1.2
#: Nut factor for lightly lubricated steel into aluminium. Uncertain by
#: roughly +/-30%; every check that uses it says so in its note.
_NUT_FACTOR_K = 0.20
#: Friction coefficient, aluminium clamp on cured CFRP tube.
_FRICTION_MU = 0.15


@dataclass(frozen=True)
class Check:
    """One sizing calculation."""

    key: str
    title: str
    #: Human-readable formula, e.g. "sigma = M*c/I".
    formula: str
    #: Inputs, as name -> (value, unit), rendered as a table under the formula.
    inputs: dict[str, tuple[float, str]]
    applied: float
    allowable: float
    unit: str
    target_sf: float
    note: str = ""

    @property
    def safety_factor(self) -> float:
        return self.allowable / self.applied if self.applied > 0 else math.inf

    @property
    def passes(self) -> bool:
        return self.safety_factor >= self.target_sf


@dataclass(frozen=True)
class PerformanceReport:
    """Vehicle-level flight performance figures."""

    all_up_mass_g: float
    total_thrust_g: float
    thrust_to_weight: float
    #: Fraction of full thrust needed to hold a hover.
    hover_throttle: float
    #: Rough hover endurance from the usable battery energy, minutes.
    hover_endurance_min: float
    #: Disc loading, N/m^2 — the number that predicts how gusty-air stable it is.
    disc_loading_n_m2: float


def _load_case(key: str):
    for lc in LOAD_CASES:
        if lc.key == key:
            return lc
    raise KeyError(f"Unknown load case {key!r}")


def _thrust_per_motor_n(load_case_key: str, all_up_mass_g: float) -> float:
    """The reference thrust each motor carries under the named load case, in N.

    Hover and max-thrust are sized from different bases: hover is a quarter
    of whatever the vehicle actually masses (from the CAD), max-thrust is
    the motor's rated static thrust regardless of vehicle mass. Using the
    CAD-derived mass for hover — not the config target — is what lets this
    check catch a design that has grown heavier than intended.
    """
    if load_case_key == "hover":
        grams = all_up_mass_g / SPEC.airframe.arm_count
    elif load_case_key == "max_thrust":
        grams = SPEC.airframe.thrust_per_motor_g
    else:
        raise ValueError(f"{load_case_key!r} has no simple per-motor thrust basis")
    return grams / 1000.0 * _G


def performance() -> PerformanceReport:
    """Thrust-to-weight, hover throttle, endurance and disc loading.

    Endurance uses actuator-disk (momentum) theory rather than an assumed
    motor power rating, since none is given: ideal hover power per rotor is
    ``T^1.5 / sqrt(2*rho*A)``, divided by a figure of merit of 0.7 to account
    for real losses (tip losses, swirl, profile drag) that ideal momentum
    theory ignores. That FM is a generic small-multirotor figure, not
    measured for this propeller, so treat the endurance number as good to
    perhaps +/-20% — stated in the report, not left implicit.
    """
    from drone_demo.analysis.mass_properties import mass_report

    mass = mass_report()
    auw_g = mass.total_mass_g
    total_thrust_g = SPEC.airframe.thrust_per_motor_g * SPEC.airframe.arm_count
    thrust_to_weight = total_thrust_g / auw_g
    hover_throttle = auw_g / total_thrust_g

    rho = 1.225  # kg/m^3, sea level standard
    figure_of_merit = 0.7
    r_m = (SPEC.propeller.diameter_mm / 1000.0) / 2.0
    disc_area_m2 = math.pi * r_m**2
    hover_thrust_per_motor_n = (auw_g / SPEC.airframe.arm_count) / 1000.0 * _G

    p_ideal_w = hover_thrust_per_motor_n**1.5 / math.sqrt(2 * rho * disc_area_m2)
    p_hover_w = SPEC.airframe.arm_count * p_ideal_w / figure_of_merit

    pack_v = SPEC.battery.cells * SPEC.battery.nominal_v_per_cell
    usable_wh = SPEC.battery.capacity_mah / 1000.0 * pack_v * SPEC.battery.usable_fraction
    hover_endurance_min = usable_wh / p_hover_w * 60.0

    total_disc_area_m2 = SPEC.airframe.arm_count * disc_area_m2
    weight_n = auw_g / 1000.0 * _G
    disc_loading = weight_n / total_disc_area_m2

    return PerformanceReport(
        all_up_mass_g=auw_g,
        total_thrust_g=total_thrust_g,
        thrust_to_weight=thrust_to_weight,
        hover_throttle=hover_throttle,
        hover_endurance_min=hover_endurance_min,
        disc_loading_n_m2=disc_loading,
    )


def arm_root_bending(load_case: str) -> Check:
    """Bending stress in the arm tube at the clamp face.

    Cantilever: thrust ``F`` at the motor, root at the clamp face, so
    ``M = F * L``. Thin-walled tube: ``I = pi/64 * (D^4 - d^4)``,
    ``sigma = M * (D/2) / I``.

    ``L`` is the free tube length plus half the motor mount collar — the
    clamp does not restrain the tube perfectly at its face, and pretending
    it does under-predicts the moment.
    """
    from drone_demo.analysis.mass_properties import mass_report

    lc = _load_case(load_case)
    t = SPEC.arm_tube
    mat = material("cfrp_tube")
    auw_g = mass_report().total_mass_g

    f_n = _thrust_per_motor_n(load_case, auw_g)
    length_mm = t.length_mm + SPEC.motor_mount.collar_length_mm / 2.0
    moment = f_n * length_mm
    i_mm4 = (math.pi / 64) * (t.outer_dia_mm**4 - t.inner_dia_mm**4)
    sigma = moment * (t.outer_dia_mm / 2) / i_mm4

    return Check(
        key=f"arm_root_bending_{load_case}",
        title=f"Arm tube root bending — {lc.title}",
        formula="sigma = M*c/I,  M = F*L,  I = pi/64*(D^4-d^4)",
        inputs={
            "F": (f_n, "N"), "L": (length_mm, "mm"),
            "D": (t.outer_dia_mm, "mm"), "d": (t.inner_dia_mm, "mm"),
        },
        applied=sigma,
        allowable=mat.yield_mpa,
        unit="MPa",
        target_sf=lc.target_sf,
        note=(
            "Allowable is the CFRP's ultimate axial strength, not a yield "
            "point — the material is brittle, so there is no useful yield."
        ),
    )


def arm_tip_deflection(load_case: str) -> Check:
    """Tip deflection of the arm under thrust: ``delta = F*L^3 / (3*E*I)``.

    Deflection, not stress, is what usually governs a drone arm: a flexible
    arm couples the motor into the airframe's bending mode and the flight
    controller ends up chasing a structural resonance it cannot fix in
    software. Allowable is L/150 — a stiffness criterion, not a strength one.
    """
    from drone_demo.analysis.mass_properties import mass_report

    lc = _load_case(load_case)
    t = SPEC.arm_tube
    mat = material("cfrp_tube")
    auw_g = mass_report().total_mass_g

    f_n = _thrust_per_motor_n(load_case, auw_g)
    length_mm = t.length_mm + SPEC.motor_mount.collar_length_mm / 2.0
    i_mm4 = (math.pi / 64) * (t.outer_dia_mm**4 - t.inner_dia_mm**4)
    delta = f_n * length_mm**3 / (3 * mat.youngs_modulus_mpa * i_mm4)
    allowable = length_mm / 150.0

    return Check(
        key=f"arm_tip_deflection_{load_case}",
        title=f"Arm tip deflection — {lc.title}",
        formula="delta = F*L^3 / (3*E*I)",
        inputs={
            "F": (f_n, "N"), "L": (length_mm, "mm"),
            "E": (mat.youngs_modulus_mpa, "MPa"), "I": (i_mm4, "mm^4"),
        },
        applied=delta,
        allowable=allowable,
        unit="mm",
        target_sf=1.5,
        note="Allowable set at span/150, a stiffness (serviceability) limit, not a strength one.",
    )


def arm_first_mode_hz() -> Check:
    """First bending natural frequency of the arm as a tip-mass cantilever.

    ``f = 1/(2*pi) * sqrt(k/m_eff)`` with ``k = 3*E*I/L^3`` and
    ``m_eff = m_motor + m_prop + 0.23*m_tube`` (the 0.23 factor is the
    standard Rayleigh correction for a cantilever's own distributed mass).

    The allowable is a floor: the mode must clear the blade-pass frequency
    at hover RPM with margin, or the propeller's own rotation excites the
    arm directly. RPM is estimated from kv and pack voltage at the hover
    throttle fraction — approximate, since real RPM depends on load too, and
    the note says so.
    """
    from drone_demo.analysis.mass_properties import part_mass

    t = SPEC.arm_tube
    mat = material("cfrp_tube")
    mm = SPEC.motor_mount
    length_mm = t.length_mm + mm.collar_length_mm / 2.0
    i_mm4 = (math.pi / 64) * (t.outer_dia_mm**4 - t.inner_dia_mm**4)

    m_motor_g = SPEC.motor.mass_g
    m_prop_g = part_mass("propeller").unit_mass_g
    m_tube_g = part_mass("arm_tube").unit_mass_g
    m_eff_kg = (m_motor_g + m_prop_g + 0.23 * m_tube_g) / 1000.0

    k_n_per_mm = 3 * mat.youngs_modulus_mpa * i_mm4 / length_mm**3
    k_n_per_m = k_n_per_mm * 1000.0
    f_hz = (1 / (2 * math.pi)) * math.sqrt(k_n_per_m / m_eff_kg)

    perf = performance()
    pack_v = SPEC.battery.cells * SPEC.battery.nominal_v_per_cell
    rpm_hover = SPEC.motor.kv * pack_v * perf.hover_throttle
    blade_pass_hz = (rpm_hover / 60.0) * SPEC.propeller.blade_count

    return Check(
        key="arm_first_mode_hz",
        title="Arm first bending mode vs. blade pass",
        formula="f = 1/(2*pi) * sqrt(k/m_eff),  k = 3*E*I/L^3",
        inputs={
            "E": (mat.youngs_modulus_mpa, "MPa"), "I": (i_mm4, "mm^4"),
            "L": (length_mm, "mm"), "m_eff": (m_eff_kg * 1000, "g"),
        },
        applied=blade_pass_hz * 3,  # required floor, plotted as "applied" so SF = f_mode/floor
        allowable=f_hz,
        unit="Hz",
        target_sf=1.0,
        note=(
            f"Estimated hover RPM ({rpm_hover:.0f}) comes from kv x pack voltage x hover "
            "throttle, a rough approximation — real RPM depends on load too. Target is "
            "3x blade-pass frequency clear of the structural mode."
        ),
    )


def clamp_slip(load_case: str) -> Check:
    """Does the tube slip in the split clamp?

    Bolt preload from assembly torque: ``F_preload = T / (K * d)``. Two
    bolts clamp the tube; friction capacity is ``mu * (2 * F_preload)``,
    checked against the motor thrust directly as a conservative proxy for
    the load the joint must hold without slipping.

    The nut factor K is uncertain by roughly +/-30% — this check has to be
    confirmed by test, and the note says so plainly.
    """
    from drone_demo.analysis.mass_properties import mass_report

    lc = _load_case(load_case)
    auw_g = mass_report().total_mass_g
    f_thrust_n = _thrust_per_motor_n(load_case, auw_g)

    d_m = SPEC.fastener.nominal_dia_mm / 1000.0
    f_preload_n = _ASSEMBLY_TORQUE_NM / (_NUT_FACTOR_K * d_m)
    n_total_n = 2 * f_preload_n
    f_friction_n = _FRICTION_MU * n_total_n

    return Check(
        key=f"clamp_slip_{load_case}",
        title=f"Clamp friction vs. slip — {lc.title}",
        formula="F_preload = T/(K*d),  F_friction = mu * (2*F_preload)",
        inputs={
            "T": (_ASSEMBLY_TORQUE_NM, "N*m"), "K": (_NUT_FACTOR_K, "-"),
            "d": (SPEC.fastener.nominal_dia_mm, "mm"), "mu": (_FRICTION_MU, "-"),
        },
        applied=f_thrust_n,
        allowable=f_friction_n,
        unit="N",
        target_sf=lc.target_sf,
        note=(
            "The nut factor K is uncertain by roughly +/-30% for a lightly lubricated "
            "joint. This check should be confirmed by a pull-test on the real assembly, "
            "not trusted on the calculation alone."
        ),
    )


def landing_leg_impact() -> Check:
    """Bending stress in the printed leg after a 0.5 m drop onto one leg.

    Energy method: ``m*g*h`` goes into the leg's elastic strain energy,
    ``0.5*k*delta^2``, with ``k = 3*E*I/L^3`` for the fuse section. Solving
    for delta gives the equivalent static deflection, hence force, hence
    bending stress at the fuse.

    The printed material's allowable is knocked down to 60% of the datasheet
    figure for layer adhesion — using an isotropic datasheet value straight
    for a printed part is the classic way to get a confident, wrong answer.

    This check is *expected* to show the lowest safety factor on the
    vehicle. That is the design intent from :mod:`drone_demo.parts.landing`
    — the leg is the sacrificial part — not an oversight.
    """
    from drone_demo.analysis.mass_properties import mass_report

    leg = SPEC.landing_leg
    mat = material("pa12cf")
    drop_h_mm = 500.0
    layer_adhesion_factor = 0.60

    auw_g = mass_report().total_mass_g
    mass_kg = auw_g / 1000.0
    # m(kg)*g(m/s^2)*h(mm) = N*mm directly: the /1000 (mm->m for h) and the
    # *1000 (J->N*mm for the result) cancel, so no explicit conversion here.
    energy_n_mm = mass_kg * _G * drop_h_mm

    fuse_w = leg.strut_width_mm
    fuse_t = leg.fuse_thickness_mm
    i_fuse_mm4 = fuse_w * fuse_t**3 / 12.0
    # Use the leg's overall height as the effective cantilever length — the
    # fuse dominates the compliance, but treating the whole leg as uniform
    # section at the fuse stiffness is a deliberately conservative simplification.
    length_mm = leg.height_mm
    k_n_per_mm = 3 * mat.youngs_modulus_mpa * i_fuse_mm4 / length_mm**3

    delta_mm = math.sqrt(2 * energy_n_mm / k_n_per_mm)
    force_n = k_n_per_mm * delta_mm
    moment_n_mm = force_n * length_mm
    sigma = moment_n_mm * (fuse_t / 2) / i_fuse_mm4
    allowable = mat.yield_mpa * layer_adhesion_factor

    note = (
        "Allowable is 60% of the PA12-CF datasheet strength to account for layer "
        "adhesion in the print direction. This is expected to be the lowest safety "
        "factor on the vehicle — the leg is deliberately the part designed to break."
    )
    if delta_mm > length_mm:
        # The linear elastic energy method predicts a deflection larger than
        # the leg itself, which is physically meaningless — small-deflection
        # beam theory has broken down well before this point. The honest
        # reading is not "the stress is exactly this many MPa" but "a 0.5 m
        # drop is far beyond what this leg absorbs elastically; it yields
        # and takes the energy through plastic deformation instead," which
        # is the intended crash behaviour, just not one this linear model
        # can quantify accurately.
        note += (
            f" The predicted elastic deflection ({delta_mm:.0f} mm) exceeds the leg's "
            f"own length ({length_mm:.0f} mm), so small-deflection beam theory has broken "
            "down — the numeric stress above is not meaningful past this point. The honest "
            "conclusion is qualitative: this drop height is well beyond what the leg "
            "absorbs elastically, and it yields, which is exactly the intended crash "
            "behaviour, just not one a linear model can quantify."
        )

    return Check(
        key="landing_leg_impact",
        title="Landing leg, 0.5 m drop onto one leg",
        formula="delta = sqrt(2*m*g*h/k),  k = 3*E*I/L^3,  sigma = F*L*c/I",
        inputs={
            "m": (auw_g, "g"), "h": (drop_h_mm, "mm"),
            "w_fuse": (fuse_w, "mm"), "t_fuse": (fuse_t, "mm"),
        },
        applied=sigma,
        allowable=allowable,
        unit="MPa",
        target_sf=_load_case("hard_landing").target_sf,
        note=note,
    )


def motor_bolt_shear() -> Check:
    """Shear in the four M3 motor bolts under the motor's reaction torque.

    Reaction torque at full throttle, divided by the bolt-pattern radius,
    shared across four bolts, checked against the shank shear area at 0.6x
    the fastener's yield-equivalent (proof load derived) strength.
    """
    from drone_demo.analysis.mass_properties import mass_report

    mm = SPEC.motor_mount
    fast = SPEC.fastener
    steel = material("steel_a2")
    auw_g = mass_report().total_mass_g

    f_thrust_n = _thrust_per_motor_n("max_thrust", auw_g)
    # Reaction torque from thrust via the propeller's pitch: approximate using
    # a typical thrust-to-torque ratio for a small multirotor prop (~1/12 of
    # F*R, R = prop radius) — a coarse stand-in with no measured Q/T ratio.
    r_prop_mm = SPEC.propeller.diameter_mm / 2.0
    torque_n_mm = f_thrust_n * r_prop_mm / 12.0

    bolt_circle_r_mm = mm.bolt_pattern_a_mm / 2.0  # conservative: smaller of the two patterns
    force_per_bolt_n = torque_n_mm / bolt_circle_r_mm / 4.0

    shank_area_mm2 = math.pi / 4 * fast.nominal_dia_mm**2
    tau_applied = force_per_bolt_n / shank_area_mm2
    tau_allowable = 0.6 * steel.yield_mpa

    return Check(
        key="motor_bolt_shear",
        title="Motor bolt shear, full throttle",
        formula="tau = (Q/r/4) / A_shank,  Q ~ F*R/12",
        inputs={
            "F": (f_thrust_n, "N"), "R_prop": (r_prop_mm, "mm"),
            "r_bolts": (bolt_circle_r_mm, "mm"), "A_shank": (shank_area_mm2, "mm^2"),
        },
        applied=tau_applied,
        allowable=tau_allowable,
        unit="MPa",
        target_sf=3.0,
        note=(
            "Reaction torque uses a generic thrust-to-torque ratio (F*R/12), not a "
            "measured value for this propeller — a coarse estimate, not a manufacturer figure."
        ),
    )


def all_checks() -> tuple[Check, ...]:
    """Every check, in the order they appear in the report.

    Run from the outside of the load path inwards — prop/motor, then mount,
    then tube, then clamp — so a reader following the load path down the
    page can follow the argument. Hover and max-thrust are both checked for
    the tube and clamp, since neither load case dominates the other (max
    thrust applies a bigger load, hover demands a bigger margin).
    """
    return (
        motor_bolt_shear(),
        arm_root_bending("hover"),
        arm_root_bending("max_thrust"),
        arm_tip_deflection("hover"),
        arm_tip_deflection("max_thrust"),
        arm_first_mode_hz(),
        clamp_slip("hover"),
        clamp_slip("max_thrust"),
        landing_leg_impact(),
    )
