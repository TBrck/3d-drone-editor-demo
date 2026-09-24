"""Mass, centre of gravity and inertia, taken from the CAD.

Mass comes from ``density x volume`` for manufactured parts, and from
``PartDef.mass_override_g`` for purchased ones.  Mixing the two is the whole
subtlety here: a placeholder solid for a motor has the wrong volume by
design, so trusting its CAD mass would corrupt the centre of gravity.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np
from build123d import CenterOf

from drone_demo.materials import material
from drone_demo.parts import all_parts, get


@dataclass(frozen=True)
class PartMass:
    """Mass result for one part type across all its instances."""

    part_key: str
    name: str
    material_key: str
    process_key: str
    quantity: int
    volume_mm3: float
    unit_mass_g: float
    total_mass_g: float
    #: True if the mass came from a vendor figure rather than density x volume.
    is_override: bool
    #: Centre of mass in the part's own local frame, mm.
    local_com_mm: tuple[float, float, float]


@dataclass(frozen=True)
class MassReport:
    """Vehicle-level mass properties."""

    parts: tuple[PartMass, ...]
    total_mass_g: float
    #: Centre of gravity in vehicle coordinates, mm.
    cog_mm: tuple[float, float, float]
    #: Offset of the CoG from the rotor centroid in the XY plane, mm.
    cog_offset_from_rotor_axis_mm: float
    #: Mass moments of inertia about the vehicle axes through the CoG, g*mm^2.
    inertia_g_mm2: tuple[float, float, float]
    #: Structural mass as a fraction of all-up mass — the headline metric.
    structural_fraction: float

    def heaviest(self, n: int = 5) -> tuple[PartMass, ...]:
        """The n heaviest part types by total mass. Drives the BOM sort order."""
        return tuple(sorted(self.parts, key=lambda p: p.total_mass_g, reverse=True)[:n])


#: Parts whose mass is payload/propulsion rather than structure. Everything
#: else counts toward structural_fraction.
_NON_STRUCTURAL_KEYS = frozenset({"battery", "motor", "propeller"})


@functools.cache
def _geometry(key: str):
    """Build (and cache) one part's solid. Each builder call is a full OCCT rebuild."""
    return get(key).builder()


def part_mass(part_key: str) -> PartMass:
    """Mass properties of a single part.

    Purchased parts (``mass_override_g`` set) use the vendor mass, since
    their CAD is a placeholder solid with the wrong volume by design — but
    still use the placeholder's own geometric centre of mass for position,
    which is a reasonable stand-in for where the real part actually sits.
    """
    part = get(part_key)
    solid = _geometry(part_key)
    volume = solid.volume
    com = solid.center(CenterOf.MASS)
    local_com = (com.X, com.Y, com.Z)

    if part.mass_override_g is not None:
        unit_mass = part.mass_override_g
        is_override = True
    else:
        mat = material(part.material_key)
        unit_mass = volume * mat.density_g_cm3 / 1000.0  # mm^3 * g/cm^3 -> g, 1 cm^3 = 1000 mm^3
        is_override = False

    return PartMass(
        part_key=part_key,
        name=part.name,
        material_key=part.material_key,
        process_key=part.process_key,
        quantity=part.quantity,
        volume_mm3=volume,
        unit_mass_g=unit_mass,
        total_mass_g=unit_mass * part.quantity,
        is_override=is_override,
        local_com_mm=local_com,
    )


def mass_report() -> MassReport:
    """Roll every instance up into a vehicle mass report.

    The centre of gravity is computed over *instances*, not part types: four
    arms at four angles have four different local-to-vehicle transforms, and
    each instance's local centre of mass is transformed into vehicle
    coordinates before being summed.

    ``cog_offset_from_rotor_axis_mm`` is the CoG's distance from the
    centroid of the four propeller positions in the XY plane — on a
    multirotor that number decides whether the aircraft can trim level.

    ``inertia_g_mm2`` uses a point-mass (parallel-axis) approximation: each
    instance is treated as a point mass at its own centre of mass, ignoring
    its rotational inertia about that point. That understates inertia for
    parts with real bulk close to the vehicle CoG (chiefly the battery and
    the frame plates) and is negligible everywhere else. Good for comparing
    designs, not for a flight-dynamics model.
    """
    from drone_demo.assembly import (
        build_assembly,  # local import: assembly imports parts, avoiding a cycle
    )

    assembly = build_assembly()
    masses = {p.key: part_mass(p.key) for p in all_parts()}

    total_mass = 0.0
    moment = np.zeros(3)
    rotor_xy: list[np.ndarray] = []
    for inst in assembly.instances:
        pm = masses[inst.part.key]
        transform = np.array(inst.transform)
        world_com = transform @ np.array([*pm.local_com_mm, 1.0])
        total_mass += pm.unit_mass_g
        moment += pm.unit_mass_g * world_com[:3]
        if inst.part.key == "propeller":
            rotor_xy.append(world_com[:2])

    cog = moment / total_mass
    rotor_centroid = np.mean(rotor_xy, axis=0)
    cog_offset = float(np.linalg.norm(cog[:2] - rotor_centroid))

    inertia = np.zeros(3)
    for inst in assembly.instances:
        pm = masses[inst.part.key]
        transform = np.array(inst.transform)
        world_com = transform @ np.array([*pm.local_com_mm, 1.0])
        r = world_com[:3] - cog
        inertia[0] += pm.unit_mass_g * (r[1] ** 2 + r[2] ** 2)
        inertia[1] += pm.unit_mass_g * (r[0] ** 2 + r[2] ** 2)
        inertia[2] += pm.unit_mass_g * (r[0] ** 2 + r[1] ** 2)

    structural_mass = sum(
        pm.total_mass_g for pm in masses.values() if pm.part_key not in _NON_STRUCTURAL_KEYS
    )

    return MassReport(
        parts=tuple(masses.values()),
        total_mass_g=total_mass,
        cog_mm=(float(cog[0]), float(cog[1]), float(cog[2])),
        cog_offset_from_rotor_axis_mm=cog_offset,
        inertia_g_mm2=(float(inertia[0]), float(inertia[1]), float(inertia[2])),
        structural_fraction=structural_mass / total_mass,
    )
