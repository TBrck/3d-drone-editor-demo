"""Validates the manifest.json contract end to end.

Excludes FEA and downloads (both slow — a few minutes and tens of seconds
respectively): those are exercised manually via ``python -m drone_demo all``
before every publish, not on every test run. What's checked here is the
part everything else depends on: the manifest/glb node-name contract that
lets the browser click a triangle and find the right part record.
"""

from __future__ import annotations

import pytest
import trimesh

from drone_demo.export.gltf import export_glb
from drone_demo.export.manifest import build_manifest, validate

pytestmark = pytest.mark.slow


def test_manifest_validates_against_real_glb(tmp_path):
    glb_path = tmp_path / "drone.glb"
    stats = export_glb(str(glb_path))
    manifest = build_manifest(scene_stats=stats)

    scene = trimesh.load(str(glb_path), force="scene")
    glb_node_names = set(scene.graph.nodes_geometry)

    problems = validate(manifest, glb_node_names=glb_node_names)
    assert not problems, "\n".join(problems)


def test_manifest_bom_total_matches_mass_report():
    manifest = build_manifest()
    assert manifest["bom"]["total_mass_g"] == pytest.approx(
        manifest["analysis"]["mass"]["total_mass_g"], abs=0.1
    )


def test_manifest_every_instance_resolves_to_a_part():
    manifest = build_manifest()
    parts = manifest["parts"]
    for inst in manifest["instances"]:
        assert inst["part_key"] in parts
