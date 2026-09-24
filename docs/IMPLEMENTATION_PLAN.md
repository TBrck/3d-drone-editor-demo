# AeroFrame X1 — implementation plan

This document is written to be handed to someone (or something) that will
write the code. The scaffolding, the specification, the part registry, the
engineering rationale and the file layout already exist in the repo. What is
missing is geometry, arithmetic and rendering.

Every stub in the codebase points back here with a step number. Every step
below states what to build, how to know it works, and what to avoid.

---

## 0. How to use this plan

**Read this first, then work milestone by milestone.** The milestones in
[§10](#10-milestones) are ordered so that something is visible on screen
early and stays working. Do not implement the whole pipeline before running
anything — the failure modes in CAD code are geometric, and geometric bugs
are found by looking.

**Rules that apply everywhere:**

1. **No hard-coded dimensions outside `config.py`.** If a number appears in a
   part module, it is a bug. The one exception is a genuinely universal
   constant (`math.pi`), and even then prefer a named constant.
2. **No design strings in JavaScript.** All display text comes from
   `manifest.json`. A number typed into the web layer stops matching the CAD
   the first time a parameter changes, and nothing will warn you.
3. **Units are mm, grams, newtons, MPa** throughout Python. The only unit
   conversion in the codebase is in `export/gltf.py`, which converts to
   metres because glTF requires it.
4. **Select CAD features by position, never by index.** `edges()[3]` works
   until a dimension changes and then silently fillets the wrong edge.
   Use `.filter_by()`, `.group_by(Axis.Z)`, `.sort_by()` with a geometric
   predicate.
5. **Run the tests after every part.** `pytest -m "not slow"` takes about
   four seconds and catches most parameter mistakes.
6. **When a stub's docstring and this document disagree, the docstring
   wins** — it is closer to the code.

---

## 1. Environment — already done and verified

`.venv311` exists and is provisioned. Python 3.11.7 on Windows. Every package
below installed cleanly and was smoke-tested end to end on this machine:

| Package | Version | Role |
|---|---|---|
| `build123d` | 0.11.1 | CAD kernel wrapper (pulls `cadquery-ocp-novtk` 7.9.3) |
| `trimesh` | 5.0.0 | mesh handling, GLB writing |
| `numpy` | 2.4.6 | arrays |
| `scipy` | 1.17.1 | sparse solver behind scikit-fem |
| `gmsh` | 4.15.2 | tetrahedral meshing; the wheel bundles the binary |
| `scikit-fem` | 12.0.2 | FE assembly and solve |
| `meshio` | 5.3.5 | `.msh` reader |
| `typer` / `rich` | 0.27.1 / 15.0.0 | CLI |
| `pytest` / `ruff` | 9.1.1 / 0.16.2 | tests, lint |

To rebuild from scratch: `.\scripts\bootstrap.ps1`.

**Verified working right now:** `python -m drone_demo parts` lists 16 part
types / 103 items, and `pytest tests/test_registry.py` passes 53 checks.

Still to do once: `.\scripts\fetch_vendor.ps1` to vendor three.js 0.185.1
into `web/vendor/`.

---

## 2. Architecture

```
config.py          every dimension, as frozen dataclasses. SPEC is the only instance.
materials.py       material properties + manufacturing processes with their design rules.
      |
parts/             base.py defines PartDef; six modules register 16 parts.
      |            Builders return geometry in the part's OWN local frame.
      |            They know nothing about where the part ends up.
assembly.py        places Instances in vehicle coordinates. Owns ALL positioning.
      |            Also owns explode direction and rank per instance.
      |
      +-- analysis/    mass_properties (CAD-derived), statics (closed form), fea (gmsh+skfem)
      |
export/            mesh.py  tessellation -> trimesh
                   gltf.py  scene -> drone.glb          (owns mm->m and Z-up->Y-up)
                   manifest.py  the JSON contract
                   drawings.py  SVG sheets + DXF flat patterns
                   cad.py       STEP / STL downloads
      |
web/               static site. Reads manifest.json and nothing else.
```

**The invariant that everything hangs on:**

```
glTF node name  ==  manifest instance node_id  ==  f"{part_key}__{index}"
```

Click-to-select, isolate, explode, colour-by-process and the FEA overlay are
all lookups on that string. `export/manifest.py::validate()` must check it
against the node names actually present in the `.glb`. When a click selects
nothing in the browser, check this before anything else.

---

## 3. Part geometry

Each builder returns a `build123d.Part` positioned at its own natural datum.
Read the docstring in the stub — it specifies the geometry feature by feature.
This section adds only what the docstrings do not cover.

### 3.1 `parts/arm.py::build_arm_tube`

Trivial, and therefore the right place to establish the pattern. Get the
local frame convention right here (axis along +X, starting at the origin) and
the rest of the arm follows.

**Done when:** volume matches `π/4·(D²−d²)·L` to within the chamfer volume,
and `test_every_part_builds` passes for it.

### 3.2 `parts/arm.py::build_motor_mount`

The hardest single part, and the one most worth the effort — it is the part a
reviewer will zoom in on.

Order of operations matters. Build collar and plate as separate solids, fuse
them, *then* fillet the junction. Filleting before the fuse gives an edge
that no longer exists after it.

For the fillet edge selection, find the edges shared between the collar and
plate faces geometrically rather than by index:

```python
junction = bp.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1]
fillet(junction, radius=mm.fillet_mm)
```

Fillets are the most common OCCT failure. If one throws, reduce the radius
and check that adjacent features are not closer to the edge than the radius —
that is nearly always the cause.

**Done when:** the part builds, is a single solid, has visible fillets and
chamfers, and its bolt pattern matches `MotorMount.bolt_pattern_a/b_mm`.

### 3.3 `parts/arm.py::_clamp_half`

One function, branching on `is_upper`. Do not split it into two — a change to
the tube diameter has to move both halves together or the joint opens up.

The 0.4 mm gap between the halves at nominal is deliberate and must be in the
model: it is what guarantees the bolts still have travel when the tube is at
its lower diameter tolerance.

### 3.4 `parts/frame.py`

The plate outline is a chamfered square; build it with `Polygon` or a
rectangle plus corner cuts, whichever reads more clearly. `standoff_circle_mm`
and the four arm bolt groups are `PolarLocations` and `Locations` patterns.

Handle `lightening_hole_dia_mm == 0` without failing — the config comment
promises it works.

### 3.5 `parts/landing.py`

The leg's tapered fuse section must be a continuous loft or sweep, not
stacked boxes. A stepped section puts the stress concentration at the step
instead of in the middle of the fuse, which defeats the design intent the
part exists to demonstrate.

The 45° overhang constraint is checked by `test_printed_leg_has_no_unprintable_overhang`.
Build the geometry with that test in mind rather than fixing it afterwards.

### 3.6 `parts/electronics.py`

Model the bends as real radii. The whole point of these two parts is showing
sheet metal literacy, and a folded bracket drawn with sharp corners says the
opposite. Sweeping the folded profile along the part width is the simplest
approach that gives true bend radii.

`flat_pattern_length()` uses the K-factor method, K = 0.38:

```
BA_90 = (π/2) · (r + K·t)
developed = leg_a + leg_b + BA_90        # legs measured to the bend tangents
```

`test_sheet_metal_thickness_is_uniform` cross-checks this against the CAD
volume, so the two have to agree.

### 3.7 `parts/rotor.py::build_propeller`

Loft through 6–8 twisted sections. The pitch law is three lines and is what
makes the prop look right:

```python
beta = math.atan2(pitch_mm, 2 * math.pi * r)     # radians from the rotor disc
```

Keep the section count low — 8 sections tessellate to a few thousand
triangles and look identical to 30.

### 3.8 `parts/hardware.py::build_screw`

Plain cylindrical shank, cosmetic hex socket, no helical thread. `functools.partial`
is already wired up for the two lengths.

---

## 4. Assembly (`assembly.py`)

Implement in this order: `translation` → `rotation_z` → `compose` →
`build_arm` → `build_frame` → `build_assembly`.

**Transform convention:** row-major 4×4, and `compose(a, b)` means "apply `a`,
then `b`". Write that down in the code and hold to it. A reversed
multiplication order is the single most likely source of a wrong-looking
assembly, and it is hard to spot because most parts sit near the origin.

**Build each arm along +X, then rotate once.** Do not place parts directly at
45° — the trigonometry ends up copied into a dozen places and one of them
will be wrong.

**Explode vectors.** Choose them so the explosion reads as a disassembly
sequence a fitter would actually perform:

| Instance | direction | rank |
|---|---|---|
| propeller | +Z | 4 |
| motor | +Z | 3 |
| motor screws | +Z | 5 |
| motor mount | +X (along the tube) | 2 |
| arm tube | +X | 1 |
| clamp upper | +Z | 2 |
| clamp lower | −Z | 2 |
| landing leg / foot | −Z | 2 / 3 |
| ESC bracket | −Z | 1 |
| top plate | +Z | 1 |
| battery / tray | −Z | 2 / 1 |
| frame plates, standoffs | ±Z | 1 |

Higher rank travels further, so outer parts clear the ones beneath them
instead of passing through. Check this visually at explode = 1.0; if any two
parts intersect on the way out, the ranks are wrong.

**Determinism.** Same code, same instance order, every run — otherwise the
`.glb` changes on every rebuild and git diffs become useless.

**Done when:** `build_assembly()` returns ~103 instances, every `node_id` is
unique, and rendering it shows a quadcopter rather than an exploded parts bin.

---

## 5. Analysis

### 5.1 `analysis/mass_properties.py`

Cache the built geometry. `part_mass`, the exporter and the FEA driver all
want the same solids, and each builder call is a full OCCT rebuild:

```python
@functools.lru_cache(maxsize=None)
def _geometry(key: str): return get(key).builder()
```

Verified available: `part.volume` (mm³) and `part.center(CenterOf.MASS)`.

**The centre of gravity must be summed over instances, not part types.** Four
arms at four angles have four different transforms, and each part's local
centre of mass has to be transformed into vehicle coordinates first. Getting
this wrong produces a CoG at the origin — which looks plausible and is wrong.

Report `cog_offset_from_rotor_axis_mm` explicitly. On a multirotor that
number decides whether the aircraft can trim level, and it is the first thing
an experienced reviewer looks for.

Purchased parts (`material_key == "cots"`) use `mass_override_g`. This is
already enforced by `test_purchased_parts_have_a_mass_override`.

### 5.2 `analysis/statics.py`

Every stub carries its formula. Points worth restating:

- **`arm_root_bending`** — take the cantilever length as free tube length
  plus half the motor mount collar. A clamp does not restrain a tube
  perfectly at its face, and assuming it does under-predicts the moment.
- **`arm_tip_deflection`** — the allowable is L/150, a *stiffness* criterion.
  State the basis in `note`; an allowable with no stated basis is just a number.
- **`arm_first_mode_hz`** — the only check whose failure would not show up in
  any static analysis, which is exactly why it belongs in the report.
- **`clamp_slip`** — the nut factor K = 0.20 is uncertain by roughly ±30 %.
  Say so. This check has to be confirmed by test and claiming otherwise
  oversells it.
- **`landing_leg_impact`** — knock the printed material's allowable down to
  60 % for layer adhesion and say that you did. Using an isotropic datasheet
  value for a printed part is the classic route to a confident wrong answer.
  **This check is expected to show the lowest safety factor on the vehicle.**
  That is the design intent, and the report has to present it that way or it
  reads as an oversight.

`Check.safety_factor` is `allowable / applied`; `passes` is
`safety_factor >= target_sf`.

### 5.3 `analysis/fea.py`

The whole chain is verified working on this machine. Reference implementation
of the solve core, taken from the smoke test that ran successfully:

```python
import gmsh, skfem, numpy as np
from skfem.models.elasticity import linear_elasticity, lame_parameters, linear_stress
from skfem.helpers import sym_grad

# --- mesh -------------------------------------------------------------
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
    gmsh.finalize()          # ALWAYS. gmsh keeps global state.

mesh = skfem.Mesh.load(msh_path)          # -> MeshTet1

# --- solve ------------------------------------------------------------
basis = skfem.Basis(mesh, skfem.ElementVector(skfem.ElementTetP1()))
lam, mu = lame_parameters(E_mpa, nu)
K = linear_elasticity(lam, mu).assemble(basis)
D = basis.get_dofs(lambda x: x[0] < x_min + 1e-6)      # restraint predicate
f = basis.zeros()
f[basis.get_dofs(load_predicate).nodal["u^3"]] = force_n / n_loaded_nodes
u = skfem.solve(*skfem.condense(K, f, D=D))

# --- von Mises --------------------------------------------------------
C = linear_stress(lam, mu)
s = C(sym_grad(basis.interpolate(u)))
vm = np.sqrt(0.5 * ((s[0,0]-s[1,1])**2 + (s[1,1]-s[2,2])**2 + (s[2,2]-s[0,0])**2
                    + 6*(s[0,1]**2 + s[1,2]**2 + s[0,2]**2)))
```

**Units:** E in MPa and mesh in mm gives forces in N and displacements in mm.
Keep everything in that system and no conversion is needed anywhere.

**Always `gmsh.finalize()` in a `finally`.** A leaked session makes the *next*
mesh inherit the previous model's settings — producing a plausible wrong
answer rather than an error.

**Local refinement:** use a `Distance` + `Threshold` mesh field around the
fillet edges. Dropping the global size to 0.6 mm on the motor mount gives
hundreds of thousands of elements and takes minutes.

**Convergence is not optional.** Run each case twice, at `mesh_size_mm` and at
half of it, and record the relative change in peak stress. Above ~10 % means
not converged, and the report must show the number. A stress plot with no
convergence check is decoration.

**Report the peak from element values,** not from vertex-averaged ones.
Averaging onto vertices smooths the maximum away, which flatters the result.
Use vertex averaging for the colour map only.

Cross-check `tube_root_bending` against `statics.arm_root_bending`. They
should agree within about 10 %. If they do not, one of them is wrong, and
experience says it is usually the FE model — check the restraint first.

**Colour ramp:** viridis or blue-white-red. Not a rainbow. Rainbow ramps
invent boundaries that are not in the data and are why so many FEA plots
mislead. The CSS legend gradient in `style.css` is already viridis; match it.

---

## 6. Export

### 6.1 `export/mesh.py`

```python
verts, tris = part.tessellate(tolerance=0.06, angular_tolerance=0.25)
# verts: list[build123d.Vector], tris: list[tuple[int,int,int]]
V = np.array([(v.X, v.Y, v.Z) for v in verts])
F = np.array(tris)
m = trimesh.Trimesh(vertices=V, faces=F, process=False)
m.merge_vertices()
```

Two things learned from testing this:

- `tessellate` emits vertices **per face**, so seams carry duplicates and the
  mesh reports as non-watertight until `merge_vertices()` runs. That call
  typically removes 30–50 % of the vertices and is what makes smooth-shading
  normals come out right across a fillet.
- Pass `process=False` to the constructor. Trimesh's default processing welds
  with its own tolerance and will merge across a sharp edge, rounding off the
  chamfers that were the point of the part.

### 6.2 `export/gltf.py`

Verified: `Scene.add_geometry(mesh, node_name=..., transform=...)` round-trips
node names through GLB intact, and `PBRMaterial` survives export.

```python
mesh.visual = trimesh.visual.TextureVisuals(
    material=trimesh.visual.material.PBRMaterial(
        name=material.key,
        baseColorFactor=[r, g, b, 1.0],
        metallicFactor=material.metalness,
        roughnessFactor=material.roughness))
scene.add_geometry(mesh, node_name=instance.node_id, transform=T)
blob = scene.export(file_type="glb")
```

**This module owns both conversions, and nothing else does:**
mm → m (`gltf_scale = 0.001`) and Z-up → Y-up (−90° about X). Bake them into
the scene root transform. Baking them into the CAD would corrupt the STEP
exports; doing it in the viewer would misplace every annotation.

**Share geometry across instances.** Cache the mesh per part key and reuse it
with four transforms for the four arms — it cuts the file to roughly a third.

Warn loudly above `triangle_budget` (900 k). A 40 MB glb makes the page
useless on a phone, and someone opening this link on a phone is a realistic
scenario worth protecting.

### 6.3 `export/manifest.py` — the schema

```jsonc
{
  "meta": {
    "schema_version": "1.0",       // viewer refuses an unknown major version
    "name": "AeroFrame X1",
    "revision": "A",
    "built_at": "2026-08-13T10:00:00Z",   // from git commit date, NOT now()
    "git_commit": "b180b79",
    "tool_versions": { "build123d": "0.11.1", "python": "3.11.7" },
    "scene": { "triangles": 412000, "nodes": 103,
               "bbox_min_m": [-0.24,-0.03,-0.24], "bbox_max_m": [0.24,0.09,0.24] }
  },

  "parts": {
    "motor_mount": {
      "key": "motor_mount", "name": "Motor mount, machined",
      "material_key": "al6061", "process_key": "cnc",
      "quantity": 4, "critical": true,
      "volume_mm3": 12450.0, "unit_mass_g": 33.6, "total_mass_g": 134.4,
      "mass_is_override": false,
      "local_com_mm": [0.0, 0.0, 4.2],
      "summary": "…", "design_notes": ["…"],
      "annotations": [{ "title":"…", "body":"…", "at_mm":[0,0,14], "kind":"interface" }],
      "drawing": "drawings/motor_mount.svg",
      "step": "downloads/motor_mount.step"
    }
  },

  "instances": [
    { "node_id": "motor_mount__0", "part_key": "motor_mount", "group": "arm_0",
      "transform_mm": [[…4×4 row-major…]],
      "explode_dir": [1,0,0], "explode_rank": 2 }
  ],

  "materials": { "al6061": { …copy of the Material dataclass… } },
  "processes": { "cnc":    { …copy of the Process dataclass… } },

  "bom": {
    "rows": [ { "part_key":"battery", "qty":1, "unit_mass_g":530.0,
                "total_mass_g":530.0, "mass_fraction":0.36 } ],
    "total_mass_g": 1472.3
  },

  "analysis": {
    "mass": { "total_mass_g":1472.3, "cog_mm":[0.0,0.0,12.4],
              "cog_offset_from_rotor_axis_mm":0.8,
              "inertia_g_mm2":[…], "structural_fraction":0.31 },
    "performance": { "thrust_to_weight":2.85, "hover_throttle":0.35,
                     "hover_endurance_min":18.2, "disc_loading_n_m2":28.4 },
    "checks": [
      { "key":"arm_root_bending", "title":"Arm tube root bending",
        "formula":"sigma = M*c/I,  M = F*L,  I = pi/64*(D^4-d^4)",
        "inputs": { "F":[10.3,"N"], "L":[165.0,"mm"], "D":[16.0,"mm"], "d":[13.0,"mm"] },
        "applied":41.2, "allowable":1200.0, "unit":"MPa",
        "safety_factor":29.1, "target_sf":2.0, "passes":true, "note":"…" }
    ],
    "fea": [
      { "key":"mount_max_thrust", "part_key":"motor_mount", "title":"…",
        "max_von_mises_mpa":86.4, "yield_mpa":276.0, "safety_factor":3.19,
        "max_displacement_mm":0.042, "nodes":48210, "elements":210433,
        "convergence_delta":0.061, "solve_seconds":14.2,
        "peak_location_mm":[0,6.2,5.1],
        "result_glb":"fea/mount_max_thrust.glb",
        "legend": { "min_mpa":0.0, "max_mpa":86.4, "ramp":"viridis" },
        "restraint":"…", "loading":"…" }
    ],
    "limitations": ["Linear-static, first-order tetrahedra…", "…"]
  },

  "story": [ { "key":"overview", "title":"…", "body":"…",
               "isolate":[], "explode":0.0, "camera":{…} } ],

  "downloads": { "Assembly STEP":"downloads/aeroframe_x1_assembly.step" }
}
```

`validate()` must check, at minimum:

- every `instance.part_key` resolves in `parts`
- every `material_key` / `process_key` resolves
- every `node_id` is unique **and the set matches the node names actually in
  `drone.glb`** — load it back with `trimesh.load(..., force="scene")` and
  compare `scene.graph.nodes_geometry`
- every referenced path exists on disk
- BOM total equals the mass report total to within 0.1 g
- every `story.isolate` entry names a real part key

Run it in the test suite *and* at the end of the build. A manifest naming a
node the glb does not contain gives a viewer that fails silently on click,
which is close to undebuggable from the browser side.

Serialise with `indent=2`, `sort_keys=False`, and take the timestamp from the
git commit date — not `datetime.now()`, or every rebuild produces a diff even
when nothing changed.

### 6.4 `export/drawings.py`

Verified working:

```python
visible, hidden = part.project_to_viewport(
    viewport_origin=(100, -100, 80), viewport_up=(0, 0, 1))
svg = ExportSVG(scale=2)
svg.add_layer("visible", line_weight=0.4)
svg.add_layer("hidden", line_weight=0.2, line_type=LineType.ISO_DASH)
svg.add_shape(visible, layer="visible")
svg.add_shape(hidden, layer="hidden")
svg.write(path)
```

build123d draws geometry, not dimensions. Compose dimension lines, arrows and
text into the SVG afterwards, driven by the declarative `dimension_set()`
data. Hand-placing dimensions in markup does not survive the first parameter
change.

**Dimension what is functional**, not what is convenient: bore diameter and
its fit, bolt pattern, thickness under the motor face. A drawing that
dimensions every edge tells a machinist nothing about what matters.

Sheet is A3 landscape, first-angle projection, and the title block must say
so. Pull material and mass from the manifest so the drawing can never
disagree with the model. The notes block carries the process design rules
straight out of `materials.py` — that is the part of the drawing that shows
process understanding.

DXF flat patterns via `ezdxf` (already installed as a build123d dependency),
with bend lines on their own layer marked with direction and angle.

### 6.5 `export/cad.py`

STEP for everything manufactured — it is what opens in SolidWorks as solid
geometry. Set each child's `label` to its `node_id` when building the assembly
`Compound` so it imports as a named tree rather than 60 anonymous bodies.
STL for the printed parts. Skip purchased parts.

---

## 7. CLI (`cli.py`)

`serve`, `parts` and `check` already work. Implement `build`, `analyse`,
`fea`, `drawings`, `downloads`, and `all`.

Each command prints a rich summary table — part count, instance count,
triangle count, file size, total mass, elapsed time. `all` runs everything in
order with `--skip-fea` for fast iteration.

`build` should take under 60 s. If it does not, the tessellation tolerance or
the propeller loft section count is the reason.

---

## 8. Web

Run `.\scripts\fetch_vendor.ps1` first.

### 8.1 `js/main.js`

Fetch `manifest.json`, check `meta.schema_version` major against
`SUPPORTED_SCHEMA_MAJOR`, refuse to start on a mismatch with a clear message.
Stream the glb with GLTFLoader's `onProgress` into the loader bar. Then
`createViewer` → `mountUI` → `renderReports` → remove the loader → restore
state from `location.hash`.

Deep links are worth getting right: `#part=motor_mount&explode=60` should
reproduce a view exactly. That is what makes the page linkable in an
application email, which is the whole point of building it.

### 8.2 `js/viewer.js`

The stub lists the full API and the implementation notes. The ones that will
cost time if missed:

- **Lighting:** hemisphere fill + key directional with shadows + rim, plus
  `RoomEnvironment` for reflections. A single directional light makes
  machined aluminium read as flat grey plastic and undoes the PBR work.
- **Section plane:** set `material.side = THREE.DoubleSide` on clipped
  materials, or the cut face renders as a hole and the model looks broken
  rather than sectioned.
- **Isolate:** fade others to opacity 0.06 rather than hiding them. A ghost of
  the surrounding structure is what makes an exploded sub-assembly readable;
  hide it and parts float in space with no reference.
- **Highlight:** boost emissive and restore the original on deselect. Do not
  replace the material — that loses the identity the colour modes depend on.
- **Picking:** walk `object.parent` up until the name matches a manifest
  `node_id`; glTF import nests meshes below the named node.
- `setPixelRatio(Math.min(devicePixelRatio, 2))`.

### 8.3 `js/ui.js`

Tree grouped by `instance.group` then `part_key`, so an arm shows one row per
part rather than four identical ones. Detail card from `manifest.parts[key]`.
Sliders throttled through `requestAnimationFrame`. Story steps drive
`flyTo` + `isolate` + `setExplode`, and **exit the tour on any manual camera
input** — a guided tour that fights the user for the camera is worse than no
tour.

Hotspots are DOM elements positioned by projecting the annotation's world
point to screen space each frame: the text stays selectable, accessible and
crisp at any zoom. Hide a hotspot when its point faces away from the camera
or it appears to float through the model.

Keyboard: `E` explode, `X` isolate, `Esc` clear, arrows step the story. Give
the canvas a tabindex and a focus ring.

### 8.4 `js/report.js`

BOM sorted by total mass descending with a mass-share bar behind each row —
on a flying vehicle the mass breakdown is the headline result and a plain
table buries it.

Analysis view: one `.calc` card per check showing formula, inputs, applied vs
allowable, and the safety factor coloured by margin. **The formula is the
point of the card.** A reviewer who can follow the algebra can judge the
result; one shown only a number has to take it on trust.

Put the FEA limitations next to the FEA results, not only on the About page.
A caveat belongs beside the result it qualifies.

One number-formatting helper used everywhere. Mixed precision down a column
is the fastest way to make a report look careless.

---

## 9. Tests

`tests/test_registry.py` passes (53 checks). Implement the skipped tests in
`tests/test_geometry.py`, in this order of value:

1. **`test_no_interference_between_instances`** — bounding boxes to find
   candidate pairs, then real boolean intersections on those. This is the
   highest-value automated check in mechanical CAD and the one thing this
   pipeline does that eyeballing a render cannot. Keep intended
   interferences (press fits, clamp grip) in an explicit allow-list so a new
   clash still fails.
2. **`test_parametric_sweep_stays_valid`** — rebuild across wheelbase
   350–600 mm and tube OD 12–20 mm. Catches the fillet that only fits at
   nominal, which is by far the most common way a "parametric" model turns
   out not to be.
3. **`test_printed_leg_has_no_unprintable_overhang`** — face normals against
   the 45° limit. Makes the "prints without support" claim checkable.
4. `test_moulded_parts_have_draft`, `test_sheet_metal_thickness_is_uniform`,
   `test_parts_are_single_solids`.

Add `tests/test_manifest.py` running `validate()` against a freshly built
manifest, including the glb node-name cross-check.

---

## 10. Milestones

Ordered so something is visible early and stays working.

| # | Deliverable | Contains |
|---|---|---|
| **M1** | *A drone on screen* | §3.1–3.3 (arm parts), §4 assembly, §6.1–6.2 glb, minimal §8.1–8.2 viewer with orbit only |
| **M2** | *The whole vehicle* | §3.4–3.8 remaining parts, full assembly, interference test |
| **M3** | *Interactive* | §6.3 manifest, §8.3 UI — tree, detail card, explode, section, isolate, story |
| **M4** | *Numbers* | §5.1–5.2 mass + statics, §8.4 BOM and analysis views |
| **M5** | *Simulation* | §5.3 FEA, stress overlay, legend, convergence |
| **M6** | *Documentation* | §6.4 drawings, §6.5 STEP downloads, drawings view |
| **M7** | *Publish* | preview image, deep links, mobile pass, Pages enabled |

M1–M3 is already a strong portfolio piece. M4 is what makes it a *mechanical
engineering* portfolio piece rather than a graphics demo. Do not skip ahead to
M5 — a stress plot on an unvalidated model is worth less than a clean hand
calculation.

---

## 11. Known risks

| Risk | Where it bites | What to do |
|---|---|---|
| Fillet/chamfer operations fail in OCCT | §3.2, §3.3 | Reduce the radius; check for features closer to the edge than the radius. Fail loudly rather than skipping the fillet — a part that silently loses its fillets also loses its FEA validity. |
| Transform order reversed | §4 | Assert one known instance's world position against a hand-computed value in the test suite. |
| Triangle count explodes | §6.1–6.2 | Budget is 900 k. The propeller loft and the tessellation tolerance are the two levers. |
| gmsh global state leaks between cases | §5.3 | `finalize()` in a `finally`, always. |
| FEA disagrees with hand calc | §5.3 | Expected within 10 %. Beyond that, check the restraint first — over-constraint is the usual cause. |
| glb node names do not match the manifest | §6.2–6.3 | `validate()` cross-checks against the actual glb. Do not skip it. |
| Page opened as `file://` | §8 | Modules and `fetch` are blocked from `file://`. `python -m drone_demo serve` exists for exactly this and says so. |
| three.js version drift | §8 | Vendored and pinned at 0.185.1. Core and addons must move together. |
| Assets not rebuilt before publishing | §10 | The Pages workflow's `check-assets` step fails the build. |

---

## 12. Definition of done

- `python -m drone_demo all` runs clean from a fresh clone after `bootstrap.ps1`
- `pytest` passes, including the geometry tests
- `validate()` returns no problems
- The page loads in under 3 s on a normal connection and works on a phone
- Every part opens a detail card with material, process, mass and design notes
- Every calculation shows its formula and inputs
- Every FEA result shows its convergence delta and the method's limitations
- The STEP download opens in SolidWorks as a named assembly tree
- Nothing on the page claims more than the analysis supports
