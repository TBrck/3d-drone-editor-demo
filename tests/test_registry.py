"""Checks that need no geometry. These run in well under a second.

Keep it that way. A fast test file that catches typos in material keys is
worth far more day to day than a slow one that rebuilds every solid, because
this one actually gets run.
"""

from __future__ import annotations

import pytest

from drone_demo.config import LOAD_CASES, SPEC
from drone_demo.materials import MATERIALS, PROCESSES
from drone_demo.parts import all_parts


def test_parts_registered():
    assert len(all_parts()) >= 15


@pytest.mark.parametrize("part", all_parts(), ids=lambda p: p.key)
def test_part_keys_resolve(part):
    assert part.material_key in MATERIALS, part.key
    assert part.process_key in PROCESSES, part.key


@pytest.mark.parametrize("part", all_parts(), ids=lambda p: p.key)
def test_parts_are_documented(part):
    """Every part must carry its reasoning.

    This is not box-ticking. The entire premise of the demo is that the
    design decisions are visible, and an undocumented part shows up in the
    viewer as an empty panel — which reads worse than not including it.
    """
    assert part.summary, f"{part.key} has no summary"
    assert part.design_notes, f"{part.key} has no design notes"
    assert part.quantity >= 1


@pytest.mark.parametrize("part", all_parts(), ids=lambda p: p.key)
def test_purchased_parts_have_a_mass_override(part):
    """A placeholder solid must never contribute its CAD mass to the CoG."""
    if part.material_key == "cots":
        assert part.mass_override_g is not None, (
            f"{part.key} is a purchased part, so its CAD volume is a "
            f"placeholder and its mass must come from the vendor figure"
        )


def test_part_keys_are_snake_case():
    """node_id parsing in the viewer splits on '__', so keys must not contain it."""
    for p in all_parts():
        assert "__" not in p.key
        assert p.key == p.key.lower()


def test_load_cases_unique():
    keys = [c.key for c in LOAD_CASES]
    assert len(keys) == len(set(keys))


def test_arm_geometry_closes():
    """The arm must actually reach the wheelbase radius.

    Catches the most likely parameter mistake: changing the wheelbase without
    changing the tube length, which leaves the motors floating short of, or
    beyond, where they should be. The plates, clamps and tube have to add up.
    """
    reach = (
        SPEC.frame_plate.half_width_mm
        + SPEC.arm_tube.length_mm
        + SPEC.motor_mount.collar_length_mm / 2.0
    )
    assert reach == pytest.approx(SPEC.airframe.arm_radius_mm, abs=25.0), (
        f"arm reaches {reach:.1f} mm but the wheelbase implies "
        f"{SPEC.airframe.arm_radius_mm:.1f} mm — adjust ArmTube.length_mm"
    )


def test_thrust_to_weight_target():
    """A quadcopter below 2:1 cannot arrest a descent. Hard requirement."""
    total = SPEC.airframe.thrust_per_motor_g * SPEC.airframe.arm_count
    assert total / SPEC.airframe.target_auw_g >= 2.0
