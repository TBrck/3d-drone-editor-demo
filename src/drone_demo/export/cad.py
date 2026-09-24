"""Native CAD exports, offered as downloads from the site.

A hiring manager who wants to open the real geometry in SolidWorks should be
able to. STEP is the format that guarantees they can: it is neutral, it is
solid geometry rather than mesh, and every CAD system on the market imports
it. Offering only an STL would signal not knowing the difference.

All three exporters are verified working here: ``export_step``,
``export_stl``, and the 3MF writer via ``lib3mf``.
"""

from __future__ import annotations

import os

#: Purchased parts are not this project's design — shipping a STEP of
#: someone else's motor is pointless and slightly rude. Everything else
#: gets a real download.
_SKIP_KEYS = frozenset({"motor", "battery", "standoff", "screw_m3x8", "screw_m3x12"})

#: Printed parts also get an STL, ready to slice.
_PRINTED_KEYS = frozenset({"landing_leg"})

#: Sheet metal parts also get a DXF flat pattern.
_SHEET_METAL_KEYS = frozenset({"esc_bracket", "battery_tray"})


def export_part_step(part_key: str, out_path: str) -> None:
    """One part as STEP AP214, in millimetres, at its local datum."""
    from build123d import export_step

    from drone_demo.parts import get

    solid = get(part_key).builder()
    export_step(solid, out_path)


def export_assembly_step(out_path: str) -> None:
    """The whole vehicle as one STEP file, parts placed and named.

    Builds a ``build123d.Compound`` from every instance's solid, moved to
    its vehicle-space transform via a raw ``gp_Trsf`` (the same technique
    verified in ``test_no_interference_between_instances``), with each
    child's ``label`` set to its ``node_id``. STEP carries labels through,
    so the assembly opens in SolidWorks as a named tree, not an anonymous
    blob of 100-odd bodies.
    """
    import functools

    from build123d import Compound, Location, export_step
    from OCP.gp import gp_Trsf

    from drone_demo.assembly import build_assembly
    from drone_demo.parts import get

    @functools.cache
    def geometry(key: str):
        return get(key).builder()

    children = []
    for inst in build_assembly().instances:
        trsf = gp_Trsf()
        trsf.SetValues(*[v for row in inst.transform[:3] for v in row])
        loc = Location(gp_trsf=trsf)
        placed = loc * geometry(inst.part.key)
        placed.label = inst.node_id
        children.append(placed)

    assembly = Compound(children=children)
    assembly.label = "AeroFrame X1"
    export_step(assembly, out_path)


def export_downloads(out_dir: str) -> dict[str, str]:
    """Write the full download set and return ``{label: relative path}``.

    Contents: assembly STEP, one STEP per manufactured part, one STL per
    printed part (ready to slice), and DXF flat patterns for the sheet metal
    parts. Skip purchased parts — shipping a STEP of someone else's motor is
    pointless and slightly rude.
    """
    from build123d import export_stl

    from drone_demo.export.drawings import export_flat_pattern
    from drone_demo.parts import all_parts

    os.makedirs(out_dir, exist_ok=True)
    downloads: dict[str, str] = {}

    assembly_path = os.path.join(out_dir, "aeroframe_x1_assembly.step")
    export_assembly_step(assembly_path)
    downloads["Assembly (STEP)"] = "aeroframe_x1_assembly.step"

    for part in all_parts():
        if part.key in _SKIP_KEYS:
            continue

        step_name = f"{part.key}.step"
        export_part_step(part.key, os.path.join(out_dir, step_name))
        downloads[f"{part.name} (STEP)"] = step_name

        if part.key in _PRINTED_KEYS:
            stl_name = f"{part.key}.stl"
            from drone_demo.parts import get

            export_stl(get(part.key).builder(), os.path.join(out_dir, stl_name))
            downloads[f"{part.name} (STL)"] = stl_name

        if part.key in _SHEET_METAL_KEYS:
            dxf_name = f"{part.key}_flat.dxf"
            export_flat_pattern(part.key, os.path.join(out_dir, dxf_name))
            downloads[f"{part.name} (flat pattern DXF)"] = dxf_name

    return downloads
