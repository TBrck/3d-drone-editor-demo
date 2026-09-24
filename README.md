# AeroFrame X1

A 450 mm quadcopter airframe, designed parametrically in Python and published
as an interactive web page you can rotate, explode and take apart in a
browser.

**[Open the interactive model →](https://tbrockmeyer.github.io/3d-drone-demo/)**
*(link goes live once GitHub Pages is enabled on this repo)*

---

## What this is

A mechanical design study. Every part was modelled in code on the OpenCASCADE
kernel; every mass, stress and safety factor shown on the site was computed
from that same geometry rather than typed in. Change one number in
[config.py](src/drone_demo/config.py) and the model, the bill of materials,
the drawings and the analysis all regenerate together.

The airframe is deliberately built from six different manufacturing processes,
one per part family, so the design decisions behind each are visible:

| Part | Process | Material |
|---|---|---|
| Motor mounts, arm clamps | CNC milling | Al 6061-T6 |
| Frame plates | CFRP sheet, CNC routed | 2 mm woven laminate |
| Arm tubes | Pultruded stock, cut to length | CFRP |
| ESC brackets, battery tray | Sheet metal, laser + press brake | Al 5052-H32 |
| Landing legs | FDM 3D printing | PA12-CF |
| Feet, propellers | Injection moulding | TPU / PA6-GF30 |

## What the site shows

- The full assembly, orbitable, with an exploded-view slider and a section plane
- Click any part for its material, process, mass, tolerances and the reasoning behind its design
- A bill of materials with the mass breakdown
- Hand calculations — arm root bending, tip deflection, first natural frequency, clamp slip, bolt shear, landing impact — each shown with its formula and inputs
- Linear-static FEA results overlaid on the model, with a mesh convergence check and a plain statement of the method's limits
- Dimensioned drawings and downloadable STEP files

---

## Quick start — just look at it

You do **not** need to rebuild anything to view the model: the generated
`drone.glb`, `manifest.json`, drawings and STEP files are already committed
under `web/assets/`. All you need is Python 3.11 to serve them (the CAD
kernel is not required just to view the page — only to change it).

```powershell
.\scripts\bootstrap.ps1                  # one-time: creates .venv311, installs everything
python -m drone_demo serve               # serves web/ and opens it in your browser
```

`bootstrap.ps1` also activates nothing on its own — after it finishes, either
activate the venv (`.venv311\Scripts\Activate.ps1`, after which plain `python`
means the venv's Python) or call the interpreter directly every time:

```powershell
.venv311\Scripts\python.exe -m drone_demo serve
```

Both `python -m drone_demo <command>` and `python src/drone_demo <command>`
work identically — pick whichever you find more natural. `serve` opens
`http://127.0.0.1:8000` in your default browser automatically; pass
`--port 8080` or `--no-open-browser` if you want something different.

> **The page must be served over HTTP.** Double-clicking `web/index.html`
> will not work — it loads `manifest.json` and `drone.glb` via `fetch()` and
> uses ES modules, both of which browsers block on `file://` URLs.

---

## Making a change

Everything downstream is *derived*, never hand-edited. The one-way flow is:

```
config.py + materials.py     the specification — every dimension, one file
        |
        v
parts/*.py                   geometry builders — one file per sub-assembly
        |
        v
assembly.py                  where each part instance is placed, and how many
        |
        +--> analysis/       mass properties, hand calculations, FEA
        |
        v
export/                      writes drone.glb, manifest.json, SVG, STEP, DXF
        |
        v
web/                          the site — reads manifest.json, has no design data of its own
```

That last point matters: the browser never contains a dimension, a mass or a
material property directly. It only reads whatever `export/manifest.py`
wrote. So changing the design is always the same three steps: **edit the
Python, regenerate the assets, refresh the browser.**

### 1. Change a dimension

Every physical dimension in the airframe lives in one file:
[`src/drone_demo/config.py`](src/drone_demo/config.py). It's a set of frozen
dataclasses, one per sub-assembly, assembled into a single `SPEC` object that
the rest of the codebase imports and never mutates.

For example, to make the vehicle bigger, open `config.py` and find the
`Airframe` dataclass near the top:

```python
@dataclass(frozen=True)
class Airframe:
    ...
    wheelbase_mm: float = 450.0   # <- change this to 550.0, say
```

Then rebuild just the geometry (fast — tens of seconds, no FEA) and refresh
the already-open browser tab:

```powershell
python -m drone_demo build
```

If `serve` is still running in another terminal, a browser refresh is all you
need — `build` overwrites `web/assets/drone.glb` and `manifest.json` in
place.

Other dataclasses worth knowing:

| Dataclass | Controls |
|---|---|
| `Airframe` | wheelbase, arm count, arm angle, target mass, thrust target |
| `ArmTube`, `MotorMount`, `ArmClamp` | the arm assembly |
| `FramePlate`, `Standoff` | the top/bottom plates and how they're spaced |
| `LandingLeg`, `LandingFoot` | the printed leg and moulded foot |
| `EscBracket`, `BatteryTray` | the two sheet-metal parts |
| `Motor`, `Propeller`, `Battery` | purchased-item envelopes (for mass and clearance only — not designed here) |

A few dimensions are cross-checked by tests (for example `ArmTube.length_mm`
has to keep the arm's tube+collar geometry landing exactly on the wheelbase
radius). If you change something load-bearing, run `pytest` afterward (see
below) — it will tell you exactly which geometric consistency check broke,
rather than letting the model silently go out of tolerance.

### 2. Change a shape

Dimensions alone only get you so far — actually changing *what a part looks
like* means editing its builder function in
[`src/drone_demo/parts/`](src/drone_demo/parts/). There's one file per
sub-assembly:

| File | Parts it builds |
|---|---|
| `arm.py` | arm tube, motor mount, split clamp halves |
| `frame.py` | top/bottom plates, standoffs |
| `landing.py` | landing leg, landing foot |
| `electronics.py` | ESC bracket, battery tray, motor/battery placeholder solids |
| `rotor.py` | propeller |
| `hardware.py` | screws |

Each part is a small, self-contained function that returns a
`build123d.Part`, built with build123d's `BuildPart`/`BuildSketch` context
managers (the same declarative style as most modern Python CAD kernels — see
[build123d's docs](https://build123d.readthedocs.io/) if you haven't used it
before). At the bottom of each file, one `register(PartDef(...))` call wires
the builder into the pipeline — that's the part's key, its name, which
material/process it uses, how many the assembly needs, and the design notes
shown in the viewer's detail panel. `src/drone_demo/parts/base.py` documents
every `PartDef` field.

To **add a brand-new part**: write a builder function, `register()` it with
a new unique key, and import the module (for its side effect of calling
`register()`) from [`parts/__init__.py`](src/drone_demo/parts/__init__.py).
Nothing else in the pipeline needs to know — mass, BOM, drawings and the
viewer all discover parts by walking the registry.

### 3. Change where a part is placed

How many instances of a part exist, and where each one sits in the assembly,
is decided in [`assembly.py`](src/drone_demo/assembly.py) — not in the part's
own builder, which only ever describes the part in its own local coordinate
frame. If you add a part and it isn't showing up anywhere (or four of
something show up stacked on top of each other), this is the file to look at.

### 4. Rebuild and check your work

```powershell
python -m drone_demo build       # geometry only -> drone.glb + manifest.json (fast: iterate here)
python -m drone_demo analyse     # print mass properties + hand calcs to the console
python -m drone_demo all         # full pipeline: geometry, FEA, drawings, downloads, manifest (slow: a few minutes)
pytest                            # run the test suite (add -m "not slow" to skip the CAD-rebuild tests)
```

Run `build` while you iterate on a shape or dimension — it's the fast loop.
Run `all` once, right before you're done, since it's the only command that
regenerates *everything* the published page depends on (including the FEA
results and STEP downloads, which `build` intentionally skips because they
take minutes). `pytest` catches the two failure modes that are easy to
introduce by hand and hard to spot by eye: parts that now interfere in 3D,
and a "parametric" model that only actually builds at its default dimensions.

---

## Parts & assembly studio

A local, login-gated web app for creating **simple** new parts — box/
cylinder/sphere plus union/subtract/intersect and rigid transforms — and
placing them in the vehicle, either by dragging primitives in a 3D editor or
by hand-editing JSON. It's a separate tool from the published site: it needs
its own dependency and never ships to GitHub Pages.

```powershell
pip install -e ".[studio]"      # one-time: installs Flask
python -m drone_demo studio     # http://127.0.0.1:5000, admin/admin (dummy — local only)
```

Everything a studio part needs — its shape, material, placement — lives in
[`src/drone_demo/custom_parts.json`](src/drone_demo/custom_parts.json), a
plain JSON file. The studio UI is one way to edit it; hand-editing the file
directly works exactly the same, since both go through the same
[`build_from_shape_spec`](src/drone_demo/parts/custom.py) interpreter — there
is no separate "studio path" a hand-written part takes that produces a
different result. A studio part becomes an ordinary `PartDef`/`Instance` the
moment `custom_parts.json` has an entry for it, so it flows through mass
properties, the BOM, `manifest.json` and STEP export with no other code
involved.

This complements, not replaces, the parametric workflow above: anything
needing a fillet, a loft, a chamfer or a sweep — most of what's actually on
this airframe — stays a hand-written `build123d` function, the same as
today. The studio is for the simple stuff (a spacer, a mounting plate, a
bracket) you'd rather sketch than write a `BuildPart` block for.

A saved change updates `custom_parts.json` immediately, but the read-only
assembly shown behind the part you're editing, and the actual published
site, only update when you rebuild — either the studio's own "Rebuild"
button, or `python -m drone_demo build` from the terminal.

**Honestly not production-grade, on purpose**: the login is a single
hardcoded credential (`admin`/`admin`), checked by one function
([`drone_demo.studio.auth.verify_credentials`](src/drone_demo/studio/auth.py))
that everything else calls through — swapping in a real user store later is
a one-function change, not a rewrite. It's fine as-is because the studio only
ever binds to `127.0.0.1`, exactly like `serve`.

---

## Project layout

```
src/drone_demo/
  config.py          every dimension — the one file to edit for a resize
  materials.py        material properties (density, yield) and process metadata
  custom_parts.json     studio-authored parts — see "Parts & assembly studio" above
  parts/               one module per sub-assembly; each part is a PartDef
    base.py            the PartDef contract every part module satisfies
    custom.py           reads custom_parts.json, interprets shape JSON into build123d
  assembly.py          instance placement: how many of each part, and where
  analysis/
    mass_properties.py  mass, centre of gravity, inertia
    statics.py          closed-form hand calculations
    fea.py               gmsh meshing + scikit-fem finite element solves
  export/
    gltf.py              writes drone.glb for the web viewer
    manifest.py          writes manifest.json, the contract with web/
    drawings.py           dimensioned SVG sheets + DXF flat patterns
    cad.py                STEP/STL downloads
  studio/                Flask app behind `python -m drone_demo studio` (needs the studio extra)
  cli.py                the `drone_demo` command line app
web/
  index.html, css/, js/  the static viewer (three.js) — reads manifest.json only
  vendor/                 vendored, pinned three.js (not from a CDN)
  assets/                  generated output: drone.glb, manifest.json, drawings/, downloads/, fea/
studio/
  templates/, static/     the studio's own frontend — deliberately not under web/,
                           since web/ is what ships to the public GitHub Pages site
docs/
  IMPLEMENTATION_PLAN.md  build order, specifications, acceptance criteria
tests/                    pytest suite — geometry, interference, manifest contract
```

## CLI reference

```powershell
python -m drone_demo --help     # full command list
python -m drone_demo parts      # list the part registry
python -m drone_demo check      # sanity-check every builder still runs
python -m drone_demo build      # geometry -> drone.glb + manifest.json (fast, for iteration)
python -m drone_demo analyse    # print mass properties and the hand calculations
python -m drone_demo fea        # finite element cases (slow, a few minutes)
python -m drone_demo drawings   # SVG sheets and DXF flat patterns
python -m drone_demo downloads  # STEP/STL/DXF download set
python -m drone_demo all        # everything above, in order, into one manifest
python -m drone_demo serve      # http://127.0.0.1:8000
python -m drone_demo studio     # http://127.0.0.1:5000 — parts & assembly studio, needs pip install -e ".[studio]"
```

---

## Troubleshooting

**The page loads (header and side panel look right) but the 3D viewport is
solid black.** This is almost always the browser's WebGL context, not the
generated model — nothing in `web/assets/` differs between a working and a
black viewport. Check, in order:
1. Open DevTools (F12) → Console while on the Model tab and look for a red
   error mentioning `WebGLRenderer` or `CONTEXT_LOST`. That error message is
   the actual cause.
2. In Chrome/Edge, open `chrome://gpu` (or `edge://gpu`) and check the
   "Graphics Feature Status" section for `WebGL`/`WebGL2`. If it says
   "Software only" or lists it as disabled, hardware acceleration is off —
   re-enable it under Settings → System, or check with IT if this is a
   managed machine (common on corporate/VDI images).
3. Hard-refresh (Ctrl+Shift+R) to rule out a stale cached `drone.glb` from
   before a rebuild.

**`ModuleNotFoundError` when running a command.** Every intra-package import
in `src/drone_demo` is a fully-qualified `drone_demo.xyz` absolute import, so
`python -m drone_demo ...`, `python src/drone_demo ...` and the installed
`drone-demo` console script all work identically — this only breaks if the
package isn't installed in your active interpreter. Re-run
`.\scripts\bootstrap.ps1`, or check `python -c "import drone_demo; print(drone_demo.__file__)"`
resolves to this repo's `src/drone_demo/`.

**Port 8000 already in use.** `python -m drone_demo serve --port 8080`.

---

## Documentation

- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) — build order, specifications, acceptance criteria

## Limitations

Stated plainly, because a design study that oversells its analysis is worse
than one that has none:

- FEA is linear-static on first-order tetrahedra: a screening and comparison
  tool, not a certification analysis.
- Bolted joints are fixed restraints. No contact, preload or friction.
- Composites are treated as isotropic — reasonable for the tube in axial
  bending, wrong elsewhere.
- Endurance is a first-order energy estimate, good to perhaps 20 %.
- Nothing here has been built or flown.

## Licence

MIT.
