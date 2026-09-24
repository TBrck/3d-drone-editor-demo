"""Everything that leaves the Python process.

Output contract with the web viewer, all under ``web/assets/``::

    drone.glb            one scene, one node per instance, node name = node_id
    manifest.json        parts, materials, processes, BOM, analysis, annotations
    fea/<case>.glb       vertex-coloured result meshes
    drawings/<part>.svg  projected views with dimensions
    downloads/*.step     per-part STEP files for anyone who wants the real CAD

``manifest.json`` is the contract. The viewer reads nothing else about the
design, and every string it displays comes from there. Its schema is written
out in ``docs/IMPLEMENTATION_PLAN.md`` and must be kept in step with
``web/js/types.js``.
"""

from __future__ import annotations
