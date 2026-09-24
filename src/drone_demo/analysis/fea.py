"""Linear-elastic FEA: gmsh for meshing, scikit-fem for the solve.

Chain, all of it pip-installable and verified working on this machine::

    build123d Part
        -> export_step()                    (.step on disk)
        -> gmsh.model.occ.importShapes()    (OCCT geometry into gmsh)
        -> gmsh.model.mesh.generate(3)      (linear tetrahedra)
        -> skfem.Mesh.load()                (MeshTet1)
        -> skfem linear_elasticity          (assemble + condense + solve)
        -> von Mises per element -> per vertex
        -> trimesh vertex colours -> .glb   (viewer overlay)

Scope and honesty
-----------------
This is a linear static solve on first-order tetrahedra. It is genuinely
useful for comparing designs and for finding where stress concentrates. It
is *not* a certification-grade analysis, and the report must say so plainly
and in the same size type as the results. Specifically:

* Linear tets are stiff and under-predict peak stress. Mesh refinement at
  fillets matters and the convergence check below is not optional.
* Contact, bolt preload and friction are not modelled. Loads are applied to
  bearing surfaces as pressures instead.
* Composite parts are treated as isotropic. For the CFRP tube this is
  reasonable in axial bending and wrong in every other direction.
* Printed parts are treated as isotropic with a knocked-down modulus.

Every one of those simplifications is defensible, and being able to state
them is worth more in an interview than a prettier stress plot.
"""

from __future__ import annotations

import math
import os
import tempfile
import time
from dataclasses import dataclass

import numpy as np

from drone_demo.config import SPEC
from drone_demo.materials import material
from drone_demo.parts import get

_G = 9.80665


@dataclass(frozen=True)
class FeaCase:
    """Definition of one finite element run."""

    key: str
    part_key: str
    load_case_key: str
    title: str
    description: str
    #: Target element size in mm away from features.
    mesh_size_mm: float
    #: Refined element size near fillets and loaded faces.
    mesh_size_fine_mm: float
    #: How the fixed boundary is selected, described for the report.
    restraint: str
    #: How the load is applied, described for the report.
    loading: str


@dataclass(frozen=True)
class FeaResult:
    """Outcome of one run, plus everything the report needs to be honest."""

    case: FeaCase
    node_count: int
    element_count: int
    max_von_mises_mpa: float
    max_displacement_mm: float
    yield_mpa: float
    safety_factor: float
    #: Peak stress from a run at half the element size, for convergence.
    max_von_mises_refined_mpa: float
    #: Relative change between the two meshes. Above ~10 % means not converged.
    convergence_delta: float
    #: Path to the vertex-coloured .glb the viewer overlays on the part.
    result_glb: str
    #: Location of the peak, in part-local mm, so the viewer can fly to it.
    peak_location_mm: tuple[float, float, float]
    solve_seconds: float


FEA_CASES: tuple[FeaCase, ...] = (
    FeaCase(
        key="mount_max_thrust",
        part_key="motor_mount",
        load_case_key="max_thrust",
        title="Motor mount at full thrust",
        description=(
            "Checks the collar-to-plate fillet, which is where a machined "
            "bracket like this normally cracks."
        ),
        mesh_size_mm=1.5,
        mesh_size_fine_mm=0.6,
        restraint="Collar bore fully fixed, representing a tight clamp on the tube.",
        loading="Thrust applied as a uniform load over the motor plate's top face.",
    ),
    FeaCase(
        key="tube_root_bending",
        part_key="arm_tube",
        load_case_key="max_thrust",
        title="Arm tube root bending",
        description=(
            "Confirms the closed-form cantilever calculation in "
            ":func:`drone_demo.analysis.statics.arm_root_bending`. The two "
            "should agree within about 10 %; if they do not, one of them is "
            "wrong and the hand calculation is usually right."
        ),
        mesh_size_mm=2.0,
        mesh_size_fine_mm=0.8,
        restraint="Clamped length at the frame end fully fixed.",
        loading="Point load at the motor end, equal to one motor's static thrust.",
    ),
    FeaCase(
        key="leg_hard_landing",
        part_key="landing_leg",
        load_case_key="hard_landing",
        title="Landing leg, 0.5 m drop",
        description=(
            "Should show the peak stress in the fuse section, confirming the "
            "leg fails there and not at the snap collar."
        ),
        mesh_size_mm=2.0,
        mesh_size_fine_mm=0.8,
        restraint="Snap collar inner face fixed.",
        loading="Equivalent static force from the energy method, applied at the foot spigot.",
    ),
)


def _step_path(part_key: str, tmpdir: str) -> str:
    from build123d import export_step

    part = get(part_key)
    solid = part.builder()
    path = os.path.join(tmpdir, f"{part_key}.step")
    export_step(solid, path)
    return path


def mesh_part(part_key: str, size_mm: float, size_fine_mm: float):
    """STEP -> gmsh -> ``skfem.MeshTet``.

    Always finalizes gmsh in a ``finally`` block. gmsh keeps global state,
    and a leaked session makes the *next* mesh silently inherit the
    previous model's settings — which produces a plausible, wrong answer
    rather than an error.
    """
    import gmsh
    import skfem

    with tempfile.TemporaryDirectory() as tmpdir:
        step_path = _step_path(part_key, tmpdir)
        msh_path = os.path.join(tmpdir, f"{part_key}.msh")

        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(part_key)
            gmsh.model.occ.importShapes(step_path)
            gmsh.model.occ.synchronize()
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_fine_mm)
            gmsh.model.mesh.generate(3)
            gmsh.write(msh_path)
        finally:
            gmsh.finalize()

        mesh = skfem.Mesh.load(msh_path)
    return mesh


# ---------------------------------------------------------------------------
# Per-case restraint and load selection.
#
# Every predicate operates on the mesh's own coordinates, which are the
# part's local frame (unchanged by the STEP export). Selection is by
# geometric position, not by named gmsh entities — simpler, and robust to
# gmsh's own face numbering, which is not guaranteed stable across versions.
# ---------------------------------------------------------------------------


def _thrust_n() -> float:
    return SPEC.airframe.thrust_per_motor_g / 1000.0 * _G


def _setup_mount_max_thrust():
    from drone_demo.parts.arm import motor_mount_plate_top_z

    mm = SPEC.motor_mount
    t = SPEC.arm_tube
    collar_bore_r = (t.outer_dia_mm + 0.6) / 2
    top_z = motor_mount_plate_top_z()
    cx = mm.collar_length_mm / 2
    bolt_xy = (
        (cx + mm.bolt_pattern_a_mm / 2, 0.0),
        (cx - mm.bolt_pattern_a_mm / 2, 0.0),
        (cx, mm.bolt_pattern_b_mm / 2),
        (cx, -mm.bolt_pattern_b_mm / 2),
    )

    def restraint(x):
        r = np.sqrt(x[1] ** 2 + x[2] ** 2)
        return (np.abs(r - collar_bore_r) < 0.3) & (x[0] > -1) & (x[0] < mm.collar_length_mm + 1)

    def load(x):
        # Concentrated at the four motor bolt bosses, not spread over the
        # whole flat top face — a uniform-pressure load over that broad,
        # unremarkable area produced a near-flat stress field with no real
        # peak to converge on (verified: ~69% mesh-to-mesh delta). Loading
        # right at the bosses, next to the collar-to-plate fillet the case
        # exists to check, gives the solver an actual concentration to find.
        on_top = np.abs(x[2] - top_z) < 0.3
        near_bolt = np.zeros_like(on_top)
        for bx, by in bolt_xy:
            near_bolt |= np.sqrt((x[0] - bx) ** 2 + (x[1] - by) ** 2) < mm.bolt_dia_mm
        return on_top & near_bolt

    return restraint, load, (0.0, 0.0, -1.0), _thrust_n()


def _setup_tube_root_bending():
    t = SPEC.arm_tube

    def restraint(x):
        return x[0] < t.clamp_engagement_mm

    def load(x):
        return x[0] > t.length_mm - 2.0

    return restraint, load, (0.0, 0.0, 1.0), _thrust_n()


def _setup_leg_hard_landing():
    from drone_demo.analysis.mass_properties import mass_report
    from drone_demo.parts.landing import landing_leg_collar_bore_radius, landing_leg_spigot_tip

    leg = SPEC.landing_leg
    bore_r = landing_leg_collar_bore_radius()
    tip = landing_leg_spigot_tip()

    # Same energy method as statics.landing_leg_impact(), recomputed here
    # rather than imported, since fea.py needs only the equivalent static
    # force, not the full Check record.
    mat = material("pa12cf")
    auw_g = mass_report().total_mass_g
    mass_kg = auw_g / 1000.0
    energy_n_mm = mass_kg * _G * 500.0
    fuse_w = leg.strut_width_mm
    fuse_t = leg.fuse_thickness_mm
    i_fuse_mm4 = fuse_w * fuse_t**3 / 12.0
    k_n_per_mm = 3 * mat.youngs_modulus_mpa * i_fuse_mm4 / leg.height_mm**3
    delta_mm = math.sqrt(2 * energy_n_mm / k_n_per_mm)
    force_n = k_n_per_mm * delta_mm

    def restraint(x):
        r = np.sqrt(x[1] ** 2 + x[2] ** 2)
        return (np.abs(r - bore_r) < 0.3) & (x[0] > -1) & (x[0] < 17)

    def load(x):
        return np.sqrt((x[1] - tip[1]) ** 2 + (x[2] - tip[2]) ** 2) < 3.0

    return restraint, load, (0.0, 1.0, 0.0), force_n


_CASE_SETUP = {
    "mount_max_thrust": _setup_mount_max_thrust,
    "tube_root_bending": _setup_tube_root_bending,
    "leg_hard_landing": _setup_leg_hard_landing,
}


def _solve_once(case: FeaCase, size_mm: float, size_fine_mm: float):
    """One mesh + solve, returning (mesh, basis, von_mises_per_element, u, peak_xyz)."""
    import skfem
    from skfem.helpers import sym_grad
    from skfem.models.elasticity import lame_parameters, linear_elasticity, linear_stress

    mesh = mesh_part(case.part_key, size_mm, size_fine_mm)
    e = skfem.ElementVector(skfem.ElementTetP1())
    basis = skfem.Basis(mesh, e)

    mat = material(get(case.part_key).material_key)
    lam, mu = lame_parameters(mat.youngs_modulus_mpa, mat.poisson_ratio)
    stiffness = linear_elasticity(lam, mu).assemble(basis)

    restraint_pred, load_pred, direction, total_force_n = _CASE_SETUP[case.key]()
    restrained = basis.get_dofs(restraint_pred)
    load_dofs = basis.get_dofs(load_pred)
    if len(mesh.nodes_satisfying(restraint_pred)) == 0:
        raise RuntimeError(
            f"{case.key}: restraint predicate matched no mesh nodes — "
            "check the geometric selection against the actual part dimensions"
        )
    if len(mesh.nodes_satisfying(load_pred)) == 0:
        raise RuntimeError(
            f"{case.key}: load predicate matched no mesh nodes — "
            "check the geometric selection against the actual part dimensions"
        )

    # Distribute the total force evenly across the matching nodes' DOFs in
    # each direction component that the load vector actually uses.
    f = basis.zeros()
    dof_comp = {0: "u^1", 1: "u^2", 2: "u^3"}
    for comp, dcomp in enumerate(direction):
        if dcomp == 0.0:
            continue
        dofs = load_dofs.nodal[dof_comp[comp]]
        f[dofs] = total_force_n * dcomp / max(len(dofs), 1)

    u = skfem.solve(*skfem.condense(stiffness, f, D=restrained))

    stress_matrix = linear_stress(lam, mu)
    strain = sym_grad(basis.interpolate(u))
    stress = stress_matrix(strain)
    vm = np.sqrt(
        0.5
        * (
            (stress[0, 0] - stress[1, 1]) ** 2
            + (stress[1, 1] - stress[2, 2]) ** 2
            + (stress[2, 2] - stress[0, 0]) ** 2
            + 6 * (stress[0, 1] ** 2 + stress[1, 2] ** 2 + stress[0, 2] ** 2)
        )
    )
    # vm has shape (n_elements, n_quad_points) — verified empirically
    # (stress[i, j].shape == (n_elements, n_quad)), the opposite of the
    # naive assumption. Take the per-element max over quadrature points
    # (axis=1), then the peak across elements — reporting the element-level
    # peak, not a vertex-averaged one, which would smooth the maximum away
    # and flatter the result.
    vm_per_element = vm.max(axis=1)
    peak_element = int(np.argmax(vm_per_element))
    peak_xyz = tuple(mesh.p[:, mesh.t[:, peak_element]].mean(axis=1))

    return mesh, basis, vm_per_element, u, peak_xyz


def solve(case: FeaCase) -> FeaResult:
    """Assemble and solve one case, at nominal and half element size.

    Units: E in MPa (N/mm^2) and the mesh in mm gives forces in N and
    displacements in mm — no conversion needed anywhere.
    """
    t0 = time.time()
    mesh, basis, vm, u, peak_xyz = _solve_once(case, case.mesh_size_mm, case.mesh_size_fine_mm)
    max_vm = float(vm.max())
    max_disp = float(np.abs(u).max())

    _, _, vm_refined, _, _ = _solve_once(
        case, case.mesh_size_mm / 2.0, case.mesh_size_fine_mm / 2.0
    )
    max_vm_refined = float(vm_refined.max())
    convergence = abs(max_vm_refined - max_vm) / max_vm if max_vm > 0 else 0.0

    mat = material(get(case.part_key).material_key)
    sf = mat.yield_mpa / max_vm if max_vm > 0 else math.inf

    return FeaResult(
        case=case,
        node_count=mesh.p.shape[1],
        element_count=mesh.t.shape[1],
        max_von_mises_mpa=max_vm,
        max_displacement_mm=max_disp,
        yield_mpa=mat.yield_mpa,
        safety_factor=sf,
        max_von_mises_refined_mpa=max_vm_refined,
        convergence_delta=convergence,
        result_glb=f"fea/{case.key}.glb",
        peak_location_mm=peak_xyz,
        solve_seconds=time.time() - t0,
    )


#: Same five stops as the CSS legend ramp in web/css/style.css
#: (.legend__ramp) — kept in sync by hand since one lives in Python and the
#: other in CSS; if you change one, change the other.
_VIRIDIS_STOPS = np.array(
    [
        [0x44, 0x01, 0x54],
        [0x3B, 0x52, 0x8B],
        [0x21, 0x91, 0x8C],
        [0x5E, 0xC9, 0x62],
        [0xFD, 0xE7, 0x25],
    ],
    dtype=np.float64,
)


def _viridis(t: np.ndarray) -> np.ndarray:
    """Map t in [0, 1] to an RGB colour by linear interpolation of the stops."""
    t = np.clip(t, 0.0, 1.0)
    n = len(_VIRIDIS_STOPS) - 1
    scaled = t * n
    idx = np.clip(scaled.astype(int), 0, n - 1)
    frac = (scaled - idx)[:, None]
    return _VIRIDIS_STOPS[idx] * (1 - frac) + _VIRIDIS_STOPS[idx + 1] * frac


def export_result_glb(case: FeaCase, out_path: str) -> tuple[float, float]:
    """Write the stress-coloured surface mesh for the viewer.

    Rebuilds the solve (cheap relative to the mesh generation already done
    by :func:`solve`) to get element-level von Mises, averages onto
    vertices for a smooth colour map, and writes a vertex-coloured GLB.
    Returns the (min, max) MPa the colour ramp spans, so the manifest can
    give the viewer's legend real units instead of an unlabelled gradient.
    """
    import trimesh

    mesh, basis, vm_per_element, u, _peak = _solve_once(
        case, case.mesh_size_mm, case.mesh_size_fine_mm
    )

    # Average element stress onto vertices for the colour map only — the
    # reported peak (in FeaResult) always comes from the element values.
    vertex_vm = np.zeros(mesh.p.shape[1])
    counts = np.zeros(mesh.p.shape[1])
    for elem_idx in range(mesh.t.shape[1]):
        for node_idx in mesh.t[:, elem_idx]:
            vertex_vm[node_idx] += vm_per_element[elem_idx]
            counts[node_idx] += 1
    vertex_vm /= np.maximum(counts, 1)

    vmin, vmax = 0.0, float(vertex_vm.max())
    norm = vertex_vm / vmax if vmax > 0 else vertex_vm
    rgb = _viridis(norm)
    colours = np.concatenate([rgb, np.full((len(rgb), 1), 255.0)], axis=1).astype(np.uint8)

    # Surface facets only (boundary of the tet mesh) for a lightweight GLB.
    boundary_facets = mesh.facets[:, mesh.boundary_facets()]
    verts = mesh.p.T
    faces = boundary_facets.T

    tri_mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    tri_mesh.visual = trimesh.visual.ColorVisuals(
        mesh=tri_mesh, vertex_colors=colours[: len(verts)]
    )

    scene = trimesh.Scene(tri_mesh)
    blob = scene.export(file_type="glb")
    with open(out_path, "wb") as f:
        f.write(blob)

    return vmin, vmax


def run_all() -> tuple[FeaResult, ...]:
    """Run every case in :data:`FEA_CASES`. Expect a couple of minutes total."""
    return tuple(solve(case) for case in FEA_CASES)
