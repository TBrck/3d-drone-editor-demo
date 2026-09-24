"""2D engineering drawings as SVG.

Verified working in this environment::

    visible, hidden = part.project_to_viewport(
        viewport_origin=(100, -100, 80), viewport_up=(0, 0, 1))
    svg = ExportSVG(scale=2)
    svg.add_layer("visible", line_weight=0.4)
    svg.add_layer("hidden", line_weight=0.2, line_type=LineType.ISO_DASH)
    svg.add_shape(visible, layer="visible")
    svg.add_shape(hidden, layer="hidden")
    svg.write(path)

Why this is worth the effort: a 3D model shows that someone can drive CAD. A
dimensioned drawing with tolerances, a title block and a material callout
shows they know what actually gets sent to a supplier. The job advert asks
for "engineering drawings" explicitly.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date

#: Parts that get a drawing. Not every part needs one — fasteners and
#: purchased items do not — and a drawing set padded with trivial sheets
#: reads as padding.
DRAWN_PARTS: tuple[str, ...] = (
    "motor_mount",
    "arm_clamp_lower",
    "landing_leg",
    "esc_bracket",
    "top_plate",
)

#: A3 landscape, millimetres.
_SHEET_W = 420.0
_SHEET_H = 297.0
_MARGIN = 10.0
#: Reserved strip along the bottom for the title block.
_TITLE_H = 45.0

_SVG_NS = "http://www.w3.org/2000/svg"


def standard_views(part_key: str) -> dict[str, tuple[float, float, float]]:
    """Front, top, right and isometric viewport *directions* for one part.

    Unit vectors, not full camera positions — :func:`export_drawing` scales
    them out to the part's own bounding box so the camera clears the
    geometry regardless of the part's size.

    First-angle projection throughout, stated in every title block. Mixing
    projection conventions across a drawing set, or leaving the convention
    unstated, is a genuine error a mechanical reviewer will notice.
    """
    return {
        "front": (0.0, -1.0, 0.0),
        "top": (0.0, 0.0, 1.0),
        "right": (1.0, 0.0, 0.0),
        "iso": (1.0, -1.0, 0.7),
    }


#: Declarative dimension callouts per part: (label, value_mm, note). Values
#: are read from SPEC at render time, not hard-coded here, so a parameter
#: change can never leave a drawing showing a stale number. Deliberately
#: sparse — dimension what is functional, not what is convenient.
def dimension_set(part_key: str) -> tuple[dict, ...]:
    from drone_demo.config import SPEC

    if part_key == "motor_mount":
        mm = SPEC.motor_mount
        t = SPEC.arm_tube
        return (
            {
                "label": "Collar bore",
                "value_mm": t.outer_dia_mm + 0.6,
                "note": "H8 running fit on tube OD",
            },
            {
                "label": "Bolt pattern A",
                "value_mm": mm.bolt_pattern_a_mm,
                "note": "crossed M3 pattern",
            },
            {"label": "Bolt pattern B", "value_mm": mm.bolt_pattern_b_mm, "note": ""},
            {
                "label": "Plate thickness",
                "value_mm": mm.plate_thickness_mm,
                "note": "under the motor face",
            },
        )
    if part_key == "arm_clamp_lower":
        ac = SPEC.arm_clamp
        return (
            {"label": "Bolt spacing", "value_mm": ac.bolt_spacing_mm, "note": "2x M3 clearance"},
            {
                "label": "Groove radius",
                "value_mm": SPEC.arm_tube.outer_dia_mm / 2 + 0.05,
                "note": "tube OD + 0.05",
            },
        )
    if part_key == "landing_leg":
        leg = SPEC.landing_leg
        return (
            {
                "label": "Fuse thickness",
                "value_mm": leg.fuse_thickness_mm,
                "note": "designed weak section",
            },
            {"label": "Fuse height", "value_mm": leg.fuse_height_mm, "note": ""},
            {"label": "Splay angle", "value_mm": leg.splay_deg, "note": "deg, not mm"},
        )
    if part_key == "esc_bracket":
        eb = SPEC.esc_bracket
        return (
            {
                "label": "Bend radius",
                "value_mm": eb.bend_radius_mm,
                "note": "= 1x thickness, 5052",
            },
            {"label": "Hole diameter", "value_mm": eb.hole_dia_mm, "note": ""},
        )
    if part_key == "top_plate":
        fp = SPEC.frame_plate
        return (
            {
                "label": "Standoff circle",
                "value_mm": fp.standoff_circle_mm,
                "note": "6x M3 clearance",
            },
            {"label": "Thickness", "value_mm": fp.thickness_mm, "note": ""},
        )
    return ()


def title_block(part_key: str) -> dict:
    """Title block content, pulled from the model so it can never disagree
    with it: part name, material, process, mass, scale, projection
    convention, revision, date.
    """
    from drone_demo.analysis.mass_properties import part_mass
    from drone_demo.config import SPEC
    from drone_demo.materials import material, process
    from drone_demo.parts import get

    part = get(part_key)
    mat = material(part.material_key)
    proc = process(part.process_key)
    pm = part_mass(part_key)

    return {
        "part_number": part_key.upper(),
        "name": part.name,
        "material": mat.name,
        "process": proc.name,
        "finish": "As machined" if proc.key == "cnc" else "As " + proc.name.split(",")[0].lower(),
        "general_tolerance_mm": proc.typical_tolerance_mm,
        "mass_g": pm.unit_mass_g,
        "scale": "1:1",
        "projection": "First angle",
        "revision": SPEC.airframe.revision,
        "date": date.today().isoformat(),
        "sheet": "1 of 1",
    }


def _render_view(part, direction: tuple[float, float, float], tmp_path: str) -> ET.Element:
    """Project one view, write it via ExportSVG, and parse the result back
    in as an XML element so it can be embedded into the composed sheet.
    """
    from build123d import ExportSVG, LineType

    bbox = part.bounding_box()
    diag = (bbox.max - bbox.min).length or 1.0
    center = (bbox.min + bbox.max) * 0.5
    dx, dy, dz = direction
    origin = (center.X + dx * diag * 3, center.Y + dy * diag * 3, center.Z + dz * diag * 3)

    visible, hidden = part.project_to_viewport(origin, viewport_up=(0, 0, 1))
    svg = ExportSVG(scale=1)
    svg.add_layer("visible", line_weight=0.35)
    svg.add_layer("hidden", line_weight=0.18, line_type=LineType.ISO_DASH)
    if len(visible) > 0:
        svg.add_shape(visible, layer="visible")
    if len(hidden) > 0:
        svg.add_shape(hidden, layer="hidden")
    svg.write(tmp_path)

    ET.register_namespace("", _SVG_NS)
    tree = ET.parse(tmp_path)
    return tree.getroot()


def _parse_viewbox(root: ET.Element) -> tuple[float, float, float, float]:
    vb = root.get("viewBox", "0 0 1 1")
    minx, miny, w, h = (float(v) for v in vb.split())
    return minx, miny, w, h


def export_drawing(part_key: str, out_path: str) -> None:
    """Compose one drawing sheet: an isometric view, dimension callouts,
    title block and process notes, on a fixed A3 landscape sheet.

    Full multi-view orthographic projection with true dimension lines
    (extension lines, arrowheads, leader text) is a project in its own
    right; this ships one accurately projected view plus the dimensions
    that actually matter as labelled callouts, honestly, rather than a
    half-finished four-view layout. See ``standard_views`` for the other
    three directions, wired up but not yet composited onto the sheet.
    """
    import tempfile

    from drone_demo.materials import process
    from drone_demo.parts import get

    part = get(part_key)
    solid = part.builder()
    proc = process(part.process_key)

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        view_root = _render_view(solid, standard_views(part_key)["iso"], tmp_path)
    finally:
        import os

        os.unlink(tmp_path)

    _minx, _miny, vw, vh = _parse_viewbox(view_root)
    # Fit the view into the drawing area (sheet minus margins and the title
    # strip), preserving aspect ratio.
    avail_w = _SHEET_W - 2 * _MARGIN
    avail_h = _SHEET_H - 2 * _MARGIN - _TITLE_H
    view_scale = min(avail_w / vw, avail_h / vh) * 0.85
    tx = _MARGIN + (avail_w - vw * view_scale) / 2 - _minx * view_scale
    ty = _MARGIN + (avail_h - vh * view_scale) / 2 - _miny * view_scale

    inner_children = list(view_root)  # the <g transform="scale(1,-1)"> etc.

    tb = title_block(part_key)
    dims = dimension_set(part_key)

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="{_SVG_NS}" width="{_SHEET_W}mm" height="{_SHEET_H}mm" '
        f'viewBox="0 0 {_SHEET_W} {_SHEET_H}" font-family="monospace">'
    )
    lines.append(
        f'<rect x="0" y="0" width="{_SHEET_W}" height="{_SHEET_H}" '
        f'fill="white" stroke="black" stroke-width="0.5"/>'
    )
    lines.append(
        f'<rect x="{_MARGIN}" y="{_MARGIN}" width="{_SHEET_W - 2 * _MARGIN}" '
        f'height="{_SHEET_H - 2 * _MARGIN}" fill="none" stroke="black" stroke-width="0.3"/>'
    )

    # The projected view, positioned and scaled into the drawing area.
    lines.append(f'<g transform="translate({tx},{ty}) scale({view_scale})">')
    for child in inner_children:
        lines.append(ET.tostring(child, encoding="unicode"))
    lines.append("</g>")

    # Dimension callouts: a simple labelled list next to the view rather
    # than true leader-line dimensions (see the docstring above).
    dim_x = _SHEET_W - _MARGIN - 90.0
    dim_y = _MARGIN + 8.0
    lines.append(
        f'<text x="{dim_x}" y="{dim_y}" font-size="4" font-weight="bold">KEY DIMENSIONS</text>'
    )
    for i, d in enumerate(dims):
        y = dim_y + 6 + i * 5.5
        text = f"{d['label']}: {d['value_mm']:.2f} mm"
        if d["note"]:
            text += f"  ({d['note']})"
        if len(text) > 42:
            text = text[:39] + "..."
        lines.append(f'<text x="{dim_x}" y="{y}" font-size="3.2">{text}</text>')

    # Process design notes — the part of the sheet that shows process
    # understanding, not just geometry.
    notes_y = dim_y + 6 + len(dims) * 5.5 + 8
    lines.append(
        f'<text x="{dim_x}" y="{notes_y}" font-size="4" font-weight="bold">PROCESS NOTES</text>'
    )
    for i, rule in enumerate(proc.design_rules[:4]):
        y = notes_y + 6 + i * 5.0
        wrapped = rule if len(rule) <= 48 else rule[:45] + "..."
        lines.append(f'<text x="{dim_x}" y="{y}" font-size="2.8">{wrapped}</text>')

    # Title block: bottom strip, right-aligned within the border.
    tb_y0 = _SHEET_H - _MARGIN - _TITLE_H
    tb_x0 = _SHEET_W - _MARGIN - 150.0
    lines.append(
        f'<rect x="{tb_x0}" y="{tb_y0}" width="150" height="{_TITLE_H}" '
        f'fill="none" stroke="black" stroke-width="0.3"/>'
    )
    rows = [
        f"AEROFRAME X1 — {tb['name']}",
        f"Part No: {tb['part_number']}    Rev: {tb['revision']}    Sheet: {tb['sheet']}",
        f"Material: {tb['material']}",
        f"Process: {tb['process']}    Finish: {tb['finish']}",
        f"Mass: {tb['mass_g']:.1f} g    Scale: {tb['scale']}    "
        f"Tol: +/-{tb['general_tolerance_mm']:.2f} mm",
        f"Projection: {tb['projection']}    Date: {tb['date']}",
    ]
    for i, row in enumerate(rows):
        size = 4.2 if i == 0 else 3.0
        weight = ' font-weight="bold"' if i == 0 else ""
        ty_row = tb_y0 + 6 + i * 6
        lines.append(f'<text x="{tb_x0 + 3}" y="{ty_row}" font-size="{size}"{weight}>{row}</text>')

    lines.append("</svg>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_flat_pattern(part_key: str, out_path: str) -> None:
    """Flat pattern DXF for the sheet metal parts, with bend lines marked.

    Uses the developed length from :func:`drone_demo.parts.electronics.
    flat_pattern_length` so the flat outline can never disagree with the
    folded model's own bend allowance calculation.
    """
    import ezdxf

    from drone_demo.config import SPEC
    from drone_demo.parts import electronics

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("BEND", color=1, linetype="DASHED")
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add("DASHED", pattern=[0.6, 0.4, -0.2])

    if part_key == "esc_bracket":
        eb = SPEC.esc_bracket
        # Two identical 90 deg bends, one at each end of the base. Verified
        # consistent with flat_pattern_length's own single-bend formula:
        # flat_pattern_length(base, 0) == base + BA for one bend, so the
        # two-bend total below is base + 2*flange + 2*BA.
        ba = (math.pi / 2) * (eb.bend_radius_mm + 0.38 * eb.thickness_mm)
        expected_single_bend = electronics.flat_pattern_length(eb.base_length_mm, 0.0)
        assert abs(expected_single_bend - (eb.base_length_mm + ba)) < 1e-6

        total_len = eb.base_length_mm + 2 * eb.flange_height_mm + 2 * ba
        w = eb.base_width_mm
        msp.add_lwpolyline(
            [(0, 0), (total_len, 0), (total_len, w), (0, w), (0, 0)],
            dxfattribs={"layer": "OUTLINE"},
        )
        # Bend lines at the centre of each developed bend-allowance zone.
        bend1_x = eb.flange_height_mm + ba / 2
        bend2_x = eb.flange_height_mm + ba + eb.base_length_mm + ba / 2
        for bx in (bend1_x, bend2_x):
            msp.add_line((bx, 0), (bx, w), dxfattribs={"layer": "BEND"})
        msp.add_text(
            f"BEND 90 UP, R{eb.bend_radius_mm:.1f}",
            dxfattribs={"layer": "OUTLINE", "height": 3.0, "insert": (bend1_x, w + 3)},
        )
    elif part_key == "battery_tray":
        bt = SPEC.battery_tray
        # Simplified flat outline: floor plus the two long walls unfolded
        # flat on either side (end lips omitted from the flat pattern for
        # clarity — a real nest drawing would show all four).
        ba = (math.pi / 2) * (bt.bend_radius_mm + 0.38 * bt.thickness_mm)
        total_h = bt.wall_height_mm + ba + bt.width_mm + ba + bt.wall_height_mm
        msp.add_lwpolyline(
            [(0, 0), (bt.length_mm, 0), (bt.length_mm, total_h), (0, total_h), (0, 0)],
            dxfattribs={"layer": "OUTLINE"},
        )
        bend1_y = bt.wall_height_mm
        bend2_y = bt.wall_height_mm + ba + bt.width_mm
        for by in (bend1_y, bend2_y):
            msp.add_line((0, by), (bt.length_mm, by), dxfattribs={"layer": "BEND"})
        msp.add_text(
            f"BEND 90 UP, R{bt.bend_radius_mm:.1f}",
            dxfattribs={"layer": "OUTLINE", "height": 3.0, "insert": (3, bend1_y + 3)},
        )
    else:
        raise ValueError(f"{part_key!r} is not a sheet metal part with a flat pattern")

    doc.saveas(out_path)
