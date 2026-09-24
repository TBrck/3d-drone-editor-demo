"""``manifest.json`` — the contract between Python and the browser.

The viewer contains no design data of its own. Every string, number and
colour it displays is read from this file, which means the site can never
drift out of step with the CAD: change a dimension, rebuild, and the page
updates itself.

The schema is specified in full in ``docs/IMPLEMENTATION_PLAN.md`` section 6.3.
:func:`validate` below is the executable copy of that specification; if the
two disagree, :func:`validate` wins and the document is the bug.
"""

from __future__ import annotations

import dataclasses
import subprocess
from importlib.metadata import PackageNotFoundError, version

from drone_demo import __version__
from drone_demo.assembly import build_assembly
from drone_demo.config import SPEC
from drone_demo.materials import MATERIALS, PROCESSES
from drone_demo.parts import all_parts

#: Bumped whenever the schema changes shape. The viewer refuses to render a
#: manifest whose major version it does not recognise, which turns a
#: confusing half-broken page into a clear error message.
SCHEMA_VERSION = "1.0"


def _tool_version(pkg: str) -> str:
    try:
        return version(pkg)
    except PackageNotFoundError:  # pragma: no cover - defensive only
        return "unknown"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git available
        return "unknown"


def _git_commit_date() -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git available
        return "unknown"


def build_manifest(
    scene_stats: dict | None = None,
    fea_results: tuple | None = None,
    downloads: dict[str, str] | None = None,
) -> dict:
    """Collect the whole design into one JSON-serialisable dict.

    ``scene_stats`` is the dict :func:`drone_demo.export.gltf.export_glb`
    returns (triangle/node counts, bounding box) — passed in rather than
    recomputed here so the manifest always describes the glb that was
    actually just written, not a second, possibly different, rebuild.

    ``fea_results`` — a tuple of :class:`drone_demo.analysis.fea.FeaResult`
    — and ``downloads`` — the ``{label: relative_path}`` dict from
    :func:`drone_demo.export.cad.export_downloads` — are optional and slow
    to produce (a couple of minutes and tens of seconds respectively), so
    the CLI runs them separately and passes the results in; a plain
    ``build_manifest()`` still returns a fully valid manifest with those
    sections empty rather than fabricating figures.
    """
    from drone_demo.analysis.mass_properties import mass_report
    from drone_demo.analysis.statics import all_checks, performance

    assembly = build_assembly()
    mass = mass_report()
    perf = performance()
    checks = all_checks()
    mass_by_key = {pm.part_key: pm for pm in mass.parts}

    from drone_demo.export.drawings import DRAWN_PARTS

    parts: dict[str, dict] = {}
    for p in all_parts():
        pm = mass_by_key[p.key]
        parts[p.key] = {
            "key": p.key,
            "name": p.name,
            "material_key": p.material_key,
            "process_key": p.process_key,
            "quantity": p.quantity,
            "critical": p.critical,
            "volume_mm3": pm.volume_mm3,
            "unit_mass_g": pm.unit_mass_g,
            "total_mass_g": pm.total_mass_g,
            "mass_is_override": pm.is_override,
            "summary": p.summary,
            "design_notes": list(p.design_notes),
            "annotations": [dataclasses.asdict(a) for a in p.annotations],
            "drawing": f"drawings/{p.key}.svg" if p.key in DRAWN_PARTS else None,
        }

    instances = [
        {
            "node_id": inst.node_id,
            "part_key": inst.part.key,
            "group": inst.group,
            "transform_mm": [list(row) for row in inst.transform],
            "explode_dir": list(inst.explode_dir),
            "explode_rank": inst.explode_rank,
        }
        for inst in assembly.instances
    ]

    bom_rows = sorted(mass.parts, key=lambda pm: pm.total_mass_g, reverse=True)
    bom = {
        "rows": [
            {
                "part_key": pm.part_key,
                "name": pm.name,
                "material_key": pm.material_key,
                "process_key": pm.process_key,
                "qty": pm.quantity,
                "unit_mass_g": pm.unit_mass_g,
                "total_mass_g": pm.total_mass_g,
                "mass_fraction": pm.total_mass_g / mass.total_mass_g,
            }
            for pm in bom_rows
        ],
        "total_mass_g": mass.total_mass_g,
    }

    materials = {k: dataclasses.asdict(v) for k, v in MATERIALS.items()}
    processes = {k: dataclasses.asdict(v) for k, v in PROCESSES.items()}

    meta = {
        "schema_version": SCHEMA_VERSION,
        "name": SPEC.airframe.name,
        "revision": SPEC.airframe.revision,
        "built_at": _git_commit_date(),
        "git_commit": _git_commit(),
        "tool_versions": {
            "drone_demo": __version__,
            "build123d": _tool_version("build123d"),
            "trimesh": _tool_version("trimesh"),
        },
        "explode_distance_mm": SPEC.export.explode_distance_mm,
        "scene": scene_stats or {},
    }

    return {
        "meta": meta,
        "parts": parts,
        "instances": instances,
        "materials": materials,
        "processes": processes,
        "bom": bom,
        "analysis": {
            "mass": {
                "total_mass_g": mass.total_mass_g,
                "target_auw_g": SPEC.airframe.target_auw_g,
                "cog_mm": list(mass.cog_mm),
                "cog_offset_from_rotor_axis_mm": mass.cog_offset_from_rotor_axis_mm,
                "inertia_g_mm2": list(mass.inertia_g_mm2),
                "structural_fraction": mass.structural_fraction,
            },
            "performance": {
                "all_up_mass_g": perf.all_up_mass_g,
                "total_thrust_g": perf.total_thrust_g,
                "thrust_to_weight": perf.thrust_to_weight,
                "hover_throttle": perf.hover_throttle,
                "hover_endurance_min": perf.hover_endurance_min,
                "disc_loading_n_m2": perf.disc_loading_n_m2,
            },
            "checks": [
                {
                    "key": c.key,
                    "title": c.title,
                    "formula": c.formula,
                    "inputs": {k: list(v) for k, v in c.inputs.items()},
                    "applied": c.applied,
                    "allowable": c.allowable,
                    "unit": c.unit,
                    "target_sf": c.target_sf,
                    "safety_factor": c.safety_factor,
                    "passes": c.passes,
                    "note": c.note,
                }
                for c in checks
            ],
            "fea": [
                {
                    "key": r.case.key,
                    "part_key": r.case.part_key,
                    "title": r.case.title,
                    "description": r.case.description,
                    "restraint": r.case.restraint,
                    "loading": r.case.loading,
                    "max_von_mises_mpa": r.max_von_mises_mpa,
                    "max_displacement_mm": r.max_displacement_mm,
                    "yield_mpa": r.yield_mpa,
                    "safety_factor": r.safety_factor,
                    "max_von_mises_refined_mpa": r.max_von_mises_refined_mpa,
                    "convergence_delta": r.convergence_delta,
                    "node_count": r.node_count,
                    "element_count": r.element_count,
                    "solve_seconds": r.solve_seconds,
                    "peak_location_mm": list(r.peak_location_mm),
                    "result_glb": r.result_glb,
                    "legend": {"min_mpa": 0.0, "max_mpa": r.max_von_mises_mpa, "ramp": "viridis"},
                }
                for r in (fea_results or ())
            ],
            "limitations": [
                "Finite element results (when present) are linear-static on "
                "first-order tetrahedra: a screening and comparison tool, "
                "not a certification analysis.",
                "Bolted joints are modelled as fixed restraints — no "
                "contact, preload or friction.",
                "Composite parts are treated as isotropic, reasonable for "
                "the tube in axial bending and wrong in every other "
                "direction.",
                "The point-mass inertia approximation ignores each part's "
                "own rotational inertia about its own centre of mass.",
            ],
        },
        "story": [dict(s) for s in STORY_STEPS],
        "downloads": downloads or {},
    }


#: The guided tour. Each step names a camera pose, a set of parts to isolate,
#: an explode fraction, and the text to show. This is what turns the page
#: from a model viewer into a portfolio piece: a reader who does not know
#: what to click still gets the argument, in order.
STORY_STEPS: tuple[dict, ...] = (
    {
        "key": "overview",
        "title": "AeroFrame X1",
        "body": (
            "A 450 mm quadcopter airframe, designed entirely in code. Every "
            "dimension on this page comes from one parameter file; every mass, "
            "stress and safety factor was computed from the same geometry you "
            "are looking at."
        ),
        "isolate": [],
        "explode": 0.0,
    },
    {
        "key": "load_path",
        "title": "Follow the load path",
        "body": (
            "Thrust starts at the propeller and ends at the battery's inertia. "
            "Prop, motor, machined mount, carbon tube, split clamp, and into "
            "the frame box. Every part highlighted here exists to carry that "
            "load; everything else exists to hold those parts in place."
        ),
        "isolate": [
            "propeller",
            "motor",
            "motor_mount",
            "arm_tube",
            "arm_clamp_upper",
            "arm_clamp_lower",
            "top_plate",
            "bottom_plate",
        ],
        "explode": 0.0,
    },
    {
        "key": "arm",
        "title": "The arm, taken apart",
        "body": (
            "The tube is never drilled and never bonded. Both ends are held by "
            "split clamps that grip on friction, so the joint can be undone in "
            "the field and the load-carrying fibres stay intact."
        ),
        "isolate": ["arm_tube", "motor_mount", "arm_clamp_upper", "arm_clamp_lower"],
        "explode": 1.0,
    },
    {
        "key": "processes",
        "title": "Six processes, one airframe",
        "body": (
            "Machined brackets, folded sheet metal, routed composite plate, "
            "printed legs, moulded feet, purchased tube. Each part is made the "
            "cheapest way that meets its requirement — colour-coded here by "
            "process."
        ),
        "isolate": [],
        "explode": 0.35,
        "colour_by": "process",
    },
    {
        "key": "analysis",
        "title": "Does it hold?",
        "body": (
            "Hand calculations first, finite element second to confirm them. "
            "The lowest safety factor on the vehicle is in the landing leg — "
            "by design, because that is the part chosen to break."
        ),
        "isolate": ["motor_mount", "arm_tube", "landing_leg"],
        "explode": 0.0,
        "show_fea": True,
    },
)


def validate(
    manifest: dict,
    glb_node_names: set[str] | None = None,
    assets_dir: str | None = None,
) -> list[str]:
    """Return a list of problems. Empty means the manifest is good.

    ``glb_node_names`` — the node names actually present in ``drone.glb``
    (``scene.graph.nodes_geometry`` after reloading it) — and ``assets_dir``
    — the ``web/assets`` directory, to confirm every referenced drawing,
    FEA result and download file actually exists on disk — are both
    optional so this can run as a pure data check in the test suite without
    a freshly built site on disk; the CLI always passes both.
    """
    import os

    problems: list[str] = []
    parts = manifest["parts"]

    for key, part in parts.items():
        if part["material_key"] not in manifest["materials"]:
            problems.append(f"part {key!r} has unknown material_key {part['material_key']!r}")
        if part["process_key"] not in manifest["processes"]:
            problems.append(f"part {key!r} has unknown process_key {part['process_key']!r}")

    node_ids = [inst["node_id"] for inst in manifest["instances"]]
    if len(node_ids) != len(set(node_ids)):
        seen: set[str] = set()
        dupes = {n for n in node_ids if n in seen or seen.add(n)}  # type: ignore[func-returns-value]
        problems.append(f"duplicate node_id(s): {sorted(dupes)}")

    for inst in manifest["instances"]:
        if inst["part_key"] not in parts:
            problems.append(
                f"instance {inst['node_id']!r} references unknown part {inst['part_key']!r}"
            )

    if glb_node_names is not None:
        manifest_ids = set(node_ids)
        missing_in_glb = manifest_ids - glb_node_names
        extra_in_glb = glb_node_names - manifest_ids
        if missing_in_glb:
            problems.append(f"nodes in manifest but not in drone.glb: {sorted(missing_in_glb)}")
        if extra_in_glb:
            problems.append(f"nodes in drone.glb but not in manifest: {sorted(extra_in_glb)}")

    bom_total = manifest["bom"]["total_mass_g"]
    mass_total = manifest["analysis"]["mass"]["total_mass_g"]
    if abs(bom_total - mass_total) > 0.1:
        problems.append(
            f"BOM total {bom_total:.2f} g disagrees with mass report {mass_total:.2f} g"
        )

    for step in manifest["story"]:
        for part_key in step.get("isolate", []):
            if part_key not in parts:
                problems.append(f"story step {step['key']!r} isolates unknown part {part_key!r}")

    if assets_dir is not None:
        referenced: list[str] = []
        for part in parts.values():
            if part.get("drawing"):
                referenced.append(part["drawing"])
        for fea_case in manifest["analysis"].get("fea", []):
            referenced.append(fea_case["result_glb"])
        referenced.extend(manifest.get("downloads", {}).values())

        for rel_path in referenced:
            if not os.path.isfile(os.path.join(assets_dir, rel_path)):
                problems.append(f"referenced file does not exist on disk: {rel_path!r}")

    return problems


def write_manifest(
    out_path: str,
    scene_stats: dict | None = None,
    fea_results: tuple | None = None,
    downloads: dict[str, str] | None = None,
) -> dict:
    """Build, validate and write. Raises if validation fails.

    Serialise with ``indent=2`` and ``sort_keys=False``. The file is small
    and a readable diff is worth more than the bytes.
    """
    import json

    manifest = build_manifest(scene_stats, fea_results=fea_results, downloads=downloads)
    problems = validate(manifest)
    if problems:
        raise ValueError("manifest failed validation:\n" + "\n".join(f"  - {p}" for p in problems))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)

    return manifest
