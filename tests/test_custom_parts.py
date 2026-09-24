"""The studio's shape interpreter, tested in isolation from the registry.

Fast: builds a handful of small standalone solids, no full-assembly rebuild.
Not marked slow.
"""

from __future__ import annotations

import json

import pytest

from drone_demo.parts.custom import build_from_shape_spec, load_custom_part_specs


def test_box_builds_with_correct_volume():
    part = build_from_shape_spec({"op": "box", "length_mm": 10, "width_mm": 20, "height_mm": 5})
    assert part.volume == pytest.approx(10 * 20 * 5)
    assert len(part.solids()) == 1


def test_cylinder_builds_with_correct_volume():
    import math

    part = build_from_shape_spec({"op": "cylinder", "radius_mm": 3, "height_mm": 10})
    assert part.volume == pytest.approx(math.pi * 3**2 * 10, rel=1e-3)


def test_sphere_builds_with_correct_volume():
    import math

    part = build_from_shape_spec({"op": "sphere", "radius_mm": 4})
    assert part.volume == pytest.approx(4 / 3 * math.pi * 4**3, rel=1e-3)


def test_transform_moves_a_primitive():
    part = build_from_shape_spec({
        "op": "box", "length_mm": 10, "width_mm": 10, "height_mm": 10,
        "transform": {"translate_mm": [50, 0, 0]},
    })
    assert part.center().X == pytest.approx(50.0)


def test_subtract_produces_a_real_hole():
    spec = {
        "op": "subtract",
        "children": [
            {"op": "box", "length_mm": 20, "width_mm": 20, "height_mm": 20},
            {"op": "cylinder", "radius_mm": 3, "height_mm": 40},
        ],
    }
    part = build_from_shape_spec(spec)
    assert len(part.solids()) == 1
    box_volume = 20 * 20 * 20
    assert part.volume < box_volume
    assert part.volume == pytest.approx(box_volume - 3.14159265 * 3**2 * 20, rel=1e-2)


def test_subtract_with_no_overlap_raises():
    spec = {
        "op": "subtract",
        "children": [
            {"op": "box", "length_mm": 10, "width_mm": 10, "height_mm": 10},
            {
                "op": "box", "length_mm": 5, "width_mm": 5, "height_mm": 5,
                "transform": {"translate_mm": [100, 0, 0]},
            },
        ],
    }
    with pytest.raises(ValueError, match="removed nothing"):
        build_from_shape_spec(spec)


def test_union_of_overlapping_primitives_is_one_solid():
    spec = {
        "op": "union",
        "children": [
            {"op": "box", "length_mm": 10, "width_mm": 10, "height_mm": 10},
            {
                "op": "box", "length_mm": 10, "width_mm": 10, "height_mm": 10,
                "transform": {"translate_mm": [5, 0, 0]},
            },
        ],
    }
    part = build_from_shape_spec(spec)
    assert len(part.solids()) == 1


def test_intersect_of_non_overlapping_primitives_raises():
    spec = {
        "op": "intersect",
        "children": [
            {"op": "box", "length_mm": 10, "width_mm": 10, "height_mm": 10},
            {
                "op": "box", "length_mm": 10, "width_mm": 10, "height_mm": 10,
                "transform": {"translate_mm": [100, 0, 0]},
            },
        ],
    }
    with pytest.raises(ValueError, match="do not overlap"):
        build_from_shape_spec(spec)


def test_boolean_needs_at_least_two_children():
    with pytest.raises(ValueError, match="at least 2 children"):
        build_from_shape_spec({
            "op": "union",
            "children": [{"op": "box", "length_mm": 1, "width_mm": 1, "height_mm": 1}],
        })


def test_unknown_op_raises():
    with pytest.raises(ValueError, match="unknown shape op"):
        build_from_shape_spec({"op": "torus", "radius_mm": 1})


def test_load_custom_part_specs_missing_file_returns_empty(tmp_path):
    assert load_custom_part_specs(tmp_path / "does_not_exist.json") == []


def test_load_custom_part_specs_reads_parts_list(tmp_path):
    path = tmp_path / "custom_parts.json"
    path.write_text(json.dumps({"schema_version": "1.0", "parts": [{"key": "a"}, {"key": "b"}]}))
    specs = load_custom_part_specs(path)
    assert [s["key"] for s in specs] == ["a", "b"]


def test_load_custom_part_specs_rejects_unsupported_major_version(tmp_path):
    path = tmp_path / "custom_parts.json"
    path.write_text(json.dumps({"schema_version": "2.0", "parts": []}))
    with pytest.raises(ValueError, match="schema"):
        load_custom_part_specs(path)
