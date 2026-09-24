"""AeroFrame X1 — a parametric quadcopter airframe, built in code.

The package is a pipeline with four stages, each depending only on the one
before it:

    config + materials   ->  parts     ->  assembly  ->  export
    (the specification)      (geometry)    (placement)   (glb/step/svg/json)

:mod:`drone_demo.analysis` hangs off the side and reads parts and assembly to
produce mass properties, hand calculations and FEA results.

Run ``python -m drone_demo --help`` for the command line interface.
"""

__version__ = "0.1.0"
