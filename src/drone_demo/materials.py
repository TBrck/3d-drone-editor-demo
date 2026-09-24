"""Material and manufacturing-process library.

Every part declares a material key from :data:`MATERIALS` and a process key
from :data:`PROCESSES`.  The manifest exporter copies these records into
``manifest.json`` so the web viewer can show the engineering rationale next
to each part, and :mod:`drone_demo.analysis` reads the mechanical properties
straight from here.

Property values are representative handbook figures for design study
purposes, not certified data.  ``source`` records where each figure comes
from so the numbers can be defended in an interview.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    """Mechanical and visual properties of one material.

    Attributes
    ----------
    density_g_cm3:
        Used for mass properties.  CAD gives volume, this gives mass.
    youngs_modulus_mpa, poisson_ratio:
        Feed the FEA solver.
    yield_mpa:
        Onset of permanent deformation.  For brittle/composite materials this
        holds the ultimate strength instead and ``brittle`` is True.
    colour:
        Base colour used in the glTF material, as ``#rrggbb``.
    metalness, roughness:
        PBR parameters so the viewer distinguishes machined aluminium from a
        matte 3D print at a glance.
    """

    key: str
    name: str
    density_g_cm3: float
    youngs_modulus_mpa: float
    poisson_ratio: float
    yield_mpa: float
    colour: str
    metalness: float
    roughness: float
    brittle: bool = False
    cost_per_kg_eur: float = 0.0
    notes: str = ""
    source: str = ""


@dataclass(frozen=True)
class Process:
    """A manufacturing process, with the design rules it imposes."""

    key: str
    name: str
    #: Short statement of why this process was chosen for these parts.
    rationale: str
    #: The DFM constraints the geometry actually respects.
    design_rules: tuple[str, ...]
    #: Achievable general tolerance for the feature sizes used here.
    typical_tolerance_mm: float
    lead_time_days: int
    setup_cost_eur: float


MATERIALS: dict[str, Material] = {
    "al6061": Material(
        key="al6061",
        name="Aluminium 6061-T6",
        density_g_cm3=2.70,
        youngs_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        yield_mpa=276.0,
        colour="#b8bdc4",
        metalness=0.95,
        roughness=0.35,
        cost_per_kg_eur=9.0,
        notes=(
            "Chosen for the machined brackets: good strength-to-weight, "
            "excellent machinability, anodises for corrosion protection."
        ),
        source="MatWeb 6061-T6 typical values",
    ),
    "al5052": Material(
        key="al5052",
        name="Aluminium 5052-H32",
        density_g_cm3=2.68,
        youngs_modulus_mpa=70_300.0,
        poisson_ratio=0.33,
        yield_mpa=193.0,
        colour="#c9ced4",
        metalness=0.9,
        roughness=0.45,
        cost_per_kg_eur=7.0,
        notes=(
            "Sheet metal alloy: far better bend ductility than 6061, which "
            "cracks on tight bends. Used for every folded bracket."
        ),
        source="ASM Aerospace Specification Metals, 5052-H32",
    ),
    "cfrp_tube": Material(
        key="cfrp_tube",
        name="CFRP, pultruded tube (UD)",
        density_g_cm3=1.55,
        youngs_modulus_mpa=135_000.0,
        poisson_ratio=0.30,
        yield_mpa=1_200.0,
        colour="#23262b",
        metalness=0.15,
        roughness=0.30,
        brittle=True,
        cost_per_kg_eur=85.0,
        notes=(
            "Axial modulus of a unidirectional pultrusion. Stiff and light "
            "along the arm, weak transversely — hence the wide split clamps "
            "instead of a through-bolt, which would crush and delaminate it."
        ),
        source="Toray T700 / typical pultrusion datasheet, axial direction",
    ),
    "cfrp_plate": Material(
        key="cfrp_plate",
        name="CFRP, 2 mm woven laminate",
        density_g_cm3=1.50,
        youngs_modulus_mpa=60_000.0,
        poisson_ratio=0.10,
        yield_mpa=600.0,
        colour="#1b1e22",
        metalness=0.10,
        roughness=0.40,
        brittle=True,
        cost_per_kg_eur=120.0,
        notes=(
            "3K twill, quasi-isotropic layup. In-plane properties only — the "
            "plates are loaded in their plane by design."
        ),
        source="Typical 3K 2x2 twill prepreg laminate properties",
    ),
    "pa12cf": Material(
        key="pa12cf",
        name="PA12-CF (FDM printed)",
        density_g_cm3=1.06,
        youngs_modulus_mpa=4_800.0,
        poisson_ratio=0.38,
        yield_mpa=72.0,
        colour="#3a3f45",
        metalness=0.0,
        roughness=0.85,
        cost_per_kg_eur=95.0,
        notes=(
            "Printed legs: tough, and the anisotropy is acceptable because "
            "the leg is loaded mainly along the print's strong in-plane "
            "direction. Layer adhesion assumed at 60 % of in-plane strength."
        ),
        source="Vendor datasheet class average for CF-filled PA12",
    ),
    "tpu": Material(
        key="tpu",
        name="TPU 95A (injection moulded)",
        density_g_cm3=1.21,
        youngs_modulus_mpa=26.0,
        poisson_ratio=0.48,
        yield_mpa=9.0,
        colour="#16181b",
        metalness=0.0,
        roughness=0.95,
        cost_per_kg_eur=12.0,
        notes=(
            "Feet only. Soft enough to absorb landing energy and cheap to "
            "mould in the quantities a production drone would need."
        ),
        source="Typical TPU 95A shore-A grade",
    ),
    "nylon_gf": Material(
        key="nylon_gf",
        name="PA6-GF30 (injection moulded)",
        density_g_cm3=1.36,
        youngs_modulus_mpa=9_000.0,
        poisson_ratio=0.35,
        yield_mpa=160.0,
        colour="#2a2d31",
        metalness=0.0,
        roughness=0.55,
        cost_per_kg_eur=6.0,
        notes="Standard propeller material: stiff, fatigue tolerant, mouldable.",
        source="Typical PA6 30 % glass fill",
    ),
    "steel_a2": Material(
        key="steel_a2",
        name="Stainless A2-70 (fasteners)",
        density_g_cm3=7.90,
        youngs_modulus_mpa=193_000.0,
        poisson_ratio=0.30,
        yield_mpa=450.0,
        colour="#8e949b",
        metalness=1.0,
        roughness=0.25,
        cost_per_kg_eur=15.0,
        notes="ISO 4762 socket head cap screws, property class A2-70.",
        source="ISO 3506-1",
    ),
    "cots": Material(
        key="cots",
        name="Purchased assembly",
        density_g_cm3=0.0,
        youngs_modulus_mpa=0.0,
        poisson_ratio=0.0,
        yield_mpa=0.0,
        colour="#4a4f57",
        metalness=0.6,
        roughness=0.5,
        notes=(
            "Motors and the battery are bought in. Their mass is taken from "
            "the vendor figure in config.py, not from the CAD volume."
        ),
        source="Vendor data",
    ),
}


PROCESSES: dict[str, Process] = {
    "cnc": Process(
        key="cnc",
        name="CNC milling, 3-axis",
        rationale=(
            "The load-bearing brackets need tight bores and flat mating "
            "faces. At prototype volumes machining beats tooling up a mould."
        ),
        design_rules=(
            "All internal corners filleted to R2 so a 4 mm end mill reaches them.",
            "No pocket deeper than 4x its width — avoids long, chattering tools.",
            "All features reachable from two setups; the collar bore is the datum.",
            "0.5 mm chamfer on every exposed edge for deburring and handling.",
        ),
        typical_tolerance_mm=0.05,
        lead_time_days=7,
        setup_cost_eur=120.0,
    ),
    "sheet_metal": Process(
        key="sheet_metal",
        name="Sheet metal, laser cut and press braked",
        rationale=(
            "Brackets that only need stiffness in one plane are far cheaper "
            "folded from 1.5 mm sheet than machined from solid."
        ),
        design_rules=(
            "Inside bend radius equals material thickness (1.5 mm) for 5052.",
            "Bend relief slots at every corner to stop tearing at the bend line.",
            "Holes kept at least 3 mm from the bend tangent so they stay round.",
            "K-factor 0.38 used for the flat pattern development.",
        ),
        typical_tolerance_mm=0.3,
        lead_time_days=5,
        setup_cost_eur=60.0,
    ),
    "fdm": Process(
        key="fdm",
        name="FDM 3D printing",
        rationale=(
            "The legs are the part most likely to change between test "
            "flights, and the part most likely to be destroyed. Printing "
            "makes an iteration cost an afternoon instead of a week."
        ),
        design_rules=(
            "No overhang steeper than 45 deg — the whole leg prints unsupported.",
            "Walls a multiple of the 0.4 mm nozzle width (3 perimeters = 1.2 mm).",
            "Print orientation chosen so layer lines run across, not along, the load.",
            "Deliberate thin section at the fuse: this part is meant to fail first.",
        ),
        typical_tolerance_mm=0.2,
        lead_time_days=1,
        setup_cost_eur=0.0,
    ),
    "injection": Process(
        key="injection",
        name="Injection moulding",
        rationale=(
            "Feet and propellers are the high-volume, geometry-stable parts. "
            "They justify tooling once the design freezes."
        ),
        design_rules=(
            "1.5 deg draft on every face parallel to the pull direction.",
            "Uniform 2 mm nominal wall to avoid sink marks and voids.",
            "Two-plate mould, single parting line, no side actions needed.",
            "Ribs kept to 60 % of the adjoining wall thickness.",
        ),
        typical_tolerance_mm=0.1,
        lead_time_days=35,
        setup_cost_eur=8_000.0,
    ),
    "composite_cut": Process(
        key="composite_cut",
        name="CFRP sheet, CNC routed",
        rationale=(
            "Plates are 2D profiles in a stiff, light laminate. Routing a "
            "cured sheet gives the stiffness of composite at machining cost."
        ),
        design_rules=(
            "Diamond-coated compression router to stop delamination at the edges.",
            "Minimum internal radius 3 mm — set by the cutter, not the design.",
            "No countersinks in the laminate; loads are spread by washers instead.",
        ),
        typical_tolerance_mm=0.2,
        lead_time_days=6,
        setup_cost_eur=90.0,
    ),
    "stock": Process(
        key="stock",
        name="Purchased stock, cut to length",
        rationale="Pultruded tube and standoffs are commodity items; no reason to make them.",
        design_rules=(
            "Tube cut with an abrasive wheel and the ends sealed against moisture ingress.",
            "Length is the only controlled dimension.",
        ),
        typical_tolerance_mm=0.5,
        lead_time_days=2,
        setup_cost_eur=0.0,
    ),
    "purchased": Process(
        key="purchased",
        name="Purchased component",
        rationale="Motors, ESCs, battery and fasteners are catalogue parts.",
        design_rules=(
            "Interface dimensions taken from the vendor drawing and frozen in config.py.",
        ),
        typical_tolerance_mm=0.2,
        lead_time_days=10,
        setup_cost_eur=0.0,
    ),
}


def material(key: str) -> Material:
    """Look up a material, failing loudly on a typo."""
    try:
        return MATERIALS[key]
    except KeyError:  # pragma: no cover - programming error
        raise KeyError(f"Unknown material {key!r}. Known: {sorted(MATERIALS)}") from None


def process(key: str) -> Process:
    """Look up a process, failing loudly on a typo."""
    try:
        return PROCESSES[key]
    except KeyError:  # pragma: no cover - programming error
        raise KeyError(f"Unknown process {key!r}. Known: {sorted(PROCESSES)}") from None
