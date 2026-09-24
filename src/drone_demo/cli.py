"""Command line entry point.

    python -m drone_demo --help

The build is split into commands rather than being one script because the
stages have very different costs. Tessellation takes seconds; the FEA takes
minutes. While iterating on the geometry you want ``build`` alone, and
``all`` only before publishing.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    add_completion=False,
    help="AeroFrame X1 — parametric drone airframe: build, analyse, publish.",
)
console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
ASSET_DIR = WEB_DIR / "assets"


# ---------------------------------------------------------------------------
# Working commands
# ---------------------------------------------------------------------------


@app.command()
def serve(port: int = 8000, open_browser: bool = True) -> None:
    """Serve web/ over HTTP and open it.

    The page must be served over HTTP, not opened as a file:// URL. Browsers
    refuse ES module imports and fetch() from file://, so double-clicking
    index.html gives a blank page with a CORS error — a confusing failure
    that is worth heading off with this command.
    """
    if not (WEB_DIR / "index.html").exists():
        console.print(f"[red]No index.html under {WEB_DIR}[/red]")
        raise typer.Exit(1)

    glb = ASSET_DIR / "drone.glb"
    if not glb.exists():
        console.print(
            "[yellow]web/assets/drone.glb is missing — the page will load but "
            "show nothing. Run 'python -m drone_demo build' first.[/yellow]"
        )

    handler = http.server.SimpleHTTPRequestHandler

    class Handler(handler):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB_DIR), **kw)

        def log_message(self, fmt, *a):  # keep the console quiet
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        console.print(f"[green]Serving {WEB_DIR} at {url}[/green]  (ctrl-c to stop)")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            console.print("\nstopped")


@app.command()
def studio(port: int = 5000, open_browser: bool = True) -> None:
    """Launch the parts & assembly studio (requires the 'studio' extra).

    Local-only, like `serve`: binds 127.0.0.1. Authenticated with a dummy
    hardcoded credential today (see drone_demo.studio.auth) -- the check is
    isolated in one function so a real user store can replace it later
    without touching any route.
    """
    try:
        from drone_demo.studio import create_app
    except ImportError:
        console.print("[red]Install the studio extra:[/red] pip install -e \".[studio]\"")
        raise typer.Exit(1) from None

    flask_app = create_app()
    url = f"http://127.0.0.1:{port}/"
    console.print(f"[green]Studio at {url}[/green]  (admin/admin — local dev only, ctrl-c to stop)")
    if open_browser:
        webbrowser.open(url)
    # threaded=True: /api/rebuild blocks on a subprocess for ~20-30s (a fresh
    # interpreter importing build123d/OCCT from cold is not fast). Without
    # this, Flask's single-threaded dev server can't serve anything else --
    # not even a static file -- for the whole rebuild, which reads as a
    # frozen page rather than a slow one.
    flask_app.run(host="127.0.0.1", port=port, threaded=True)


@app.command()
def parts() -> None:
    """List every registered part with its material, process and quantity."""
    from drone_demo.parts import all_parts

    table = Table(title="Part registry", header_style="bold")
    for col in ("key", "name", "material", "process", "qty", "critical"):
        table.add_column(col)
    for p in all_parts():
        table.add_row(
            p.key,
            p.name,
            p.material_key,
            p.process_key,
            str(p.quantity),
            "yes" if p.critical else "",
        )
    console.print(table)


@app.command()
def check() -> None:
    """Report which pipeline stages are implemented.

    Handy while the implementation is in progress: it walks the registry,
    calls each builder inside a try/except, and prints a pass/fail table
    instead of dying on the first NotImplementedError.
    """
    from drone_demo.parts import all_parts

    table = Table(title="Builder status", header_style="bold")
    table.add_column("part")
    table.add_column("status")
    table.add_column("detail")
    ok = 0
    for p in all_parts():
        try:
            solid = p.builder()
            table.add_row(p.key, "[green]built[/green]", f"{solid.volume:,.0f} mm^3")
            ok += 1
        except NotImplementedError:
            table.add_row(p.key, "[yellow]todo[/yellow]", "")
        except Exception as exc:  # noqa: BLE001 - a report, not a crash
            table.add_row(p.key, "[red]error[/red]", f"{type(exc).__name__}: {exc}")
    console.print(table)
    console.print(f"{ok}/{len(all_parts())} parts build")


# ---------------------------------------------------------------------------
# Commands that depend on the implementation
# ---------------------------------------------------------------------------


@app.command()
def build() -> None:
    """Build geometry and write drone.glb + manifest.json.

    The fast, iteration-friendly command: mass properties and the
    closed-form checks are cheap and always included, but the FEA and
    downloads sections are left empty (run ``all`` before publishing to
    fill them in) — re-running FEA on every geometry tweak would make
    iteration painful for no benefit.
    """
    from drone_demo.export.gltf import export_glb
    from drone_demo.export.manifest import validate, write_manifest

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    console.print("Building geometry and exporting drone.glb...")
    stats = export_glb(str(ASSET_DIR / "drone.glb"))
    manifest = write_manifest(str(ASSET_DIR / "manifest.json"), scene_stats=stats)

    problems = validate(manifest, assets_dir=str(ASSET_DIR))
    table = Table(title="Build summary", header_style="bold")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("Parts", str(len(manifest["parts"])))
    table.add_row("Instances", str(len(manifest["instances"])))
    table.add_row("Triangles", f"{stats['triangles']:,}")
    table.add_row("File size", f"{stats['bytes'] / 1024:.0f} KB")
    table.add_row("Total mass", f"{manifest['bom']['total_mass_g']:.1f} g")
    console.print(table)
    if problems:
        console.print("[red]Manifest validation problems:[/red]")
        for p in problems:
            console.print(f"  - {p}")
        raise typer.Exit(1)
    console.print("[green]OK[/green]")


@app.command()
def analyse() -> None:
    """Print the mass properties and closed-form checks to the console."""
    from drone_demo.analysis.mass_properties import mass_report
    from drone_demo.analysis.statics import all_checks, performance

    mass = mass_report()
    perf = performance()

    console.print(f"All-up mass: {mass.total_mass_g:.1f} g")
    console.print(f"Centre of gravity: {tuple(round(v, 2) for v in mass.cog_mm)} mm")
    console.print(f"CoG offset from rotor axis: {mass.cog_offset_from_rotor_axis_mm:.3f} mm")
    console.print(f"Structural mass fraction: {mass.structural_fraction * 100:.1f}%")
    console.print(f"Thrust-to-weight: {perf.thrust_to_weight:.2f}")
    console.print(f"Hover endurance (est.): {perf.hover_endurance_min:.1f} min")
    console.print()

    table = Table(title="Checks", header_style="bold")
    for col in ("check", "applied", "allowable", "unit", "SF", "target", "pass"):
        table.add_column(col)
    for c in all_checks():
        style = "green" if c.passes else "red"
        table.add_row(
            c.title,
            f"{c.applied:.2f}",
            f"{c.allowable:.2f}",
            c.unit,
            f"{c.safety_factor:.2f}",
            f"{c.target_sf:.1f}",
            f"[{style}]{'yes' if c.passes else 'no'}[/{style}]",
        )
    console.print(table)


@app.command()
def fea(case: str = typer.Option(None, help="Single case key; omit for all of them.")) -> None:
    """Run the finite element cases and write the result overlay GLBs.

    Does not rewrite manifest.json on its own — run ``all`` to fold the
    results into a published manifest.
    """
    from drone_demo.analysis import fea as fea_module

    cases = (
        [c for c in fea_module.FEA_CASES if c.key == case]
        if case
        else list(fea_module.FEA_CASES)
    )
    if not cases:
        console.print(f"[red]No FEA case named {case!r}[/red]")
        raise typer.Exit(1)

    fea_dir = ASSET_DIR / "fea"
    fea_dir.mkdir(parents=True, exist_ok=True)

    table = Table(title="FEA results", header_style="bold")
    for col in ("case", "max von Mises", "SF", "convergence", "elements", "time"):
        table.add_column(col)
    for c in cases:
        console.print(f"Solving {c.key}...")
        result = fea_module.solve(c)
        fea_module.export_result_glb(c, str(fea_dir / f"{c.key}.glb"))
        table.add_row(
            c.key,
            f"{result.max_von_mises_mpa:.2f} MPa",
            f"{result.safety_factor:.2f}",
            f"{result.convergence_delta * 100:.1f}%",
            f"{result.element_count:,}",
            f"{result.solve_seconds:.0f}s",
        )
    console.print(table)


@app.command()
def drawings() -> None:
    """Export the SVG drawing sheets and the DXF flat patterns."""
    from drone_demo.export.drawings import DRAWN_PARTS, export_drawing, export_flat_pattern

    draw_dir = ASSET_DIR / "drawings"
    draw_dir.mkdir(parents=True, exist_ok=True)
    for part_key in DRAWN_PARTS:
        out = draw_dir / f"{part_key}.svg"
        export_drawing(part_key, str(out))
        console.print(f"  {out.relative_to(WEB_DIR)}")

    for part_key in ("esc_bracket", "battery_tray"):
        out = draw_dir / f"{part_key}_flat.dxf"
        export_flat_pattern(part_key, str(out))
        console.print(f"  {out.relative_to(WEB_DIR)}")
    console.print("[green]OK[/green]")


@app.command()
def downloads() -> None:
    """Export the STEP/STL/DXF download set."""
    from drone_demo.export.cad import export_downloads

    out_dir = ASSET_DIR / "downloads"
    result = export_downloads(str(out_dir))
    table = Table(title="Downloads", header_style="bold")
    table.add_column("label")
    table.add_column("file")
    for label, path in result.items():
        table.add_row(label, path)
    console.print(table)


@app.command(name="all")
def build_all(skip_fea: bool = False) -> None:
    """Run the whole pipeline in order and write the final manifest.json.

    This is the command to run before publishing: geometry, FEA, drawings
    and downloads, folded into one internally-consistent manifest.
    """
    from drone_demo.analysis import fea as fea_module
    from drone_demo.export.cad import export_downloads
    from drone_demo.export.drawings import DRAWN_PARTS, export_drawing, export_flat_pattern
    from drone_demo.export.gltf import export_glb
    from drone_demo.export.manifest import validate, write_manifest

    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    console.print("[bold]1/5[/bold] Geometry -> drone.glb")
    stats = export_glb(str(ASSET_DIR / "drone.glb"))

    fea_results = ()
    if not skip_fea:
        console.print("[bold]2/5[/bold] FEA (this takes a few minutes)")
        fea_dir = ASSET_DIR / "fea"
        fea_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for c in fea_module.FEA_CASES:
            console.print(f"  solving {c.key}...")
            r = fea_module.solve(c)
            fea_module.export_result_glb(c, str(fea_dir / f"{c.key}.glb"))
            results.append(r)
        fea_results = tuple(results)
    else:
        console.print("[bold]2/5[/bold] FEA skipped (--skip-fea)")

    console.print("[bold]3/5[/bold] Drawings")
    draw_dir = ASSET_DIR / "drawings"
    draw_dir.mkdir(parents=True, exist_ok=True)
    for part_key in DRAWN_PARTS:
        export_drawing(part_key, str(draw_dir / f"{part_key}.svg"))
    for part_key in ("esc_bracket", "battery_tray"):
        export_flat_pattern(part_key, str(draw_dir / f"{part_key}_flat.dxf"))

    console.print("[bold]4/5[/bold] Downloads (STEP/STL/DXF)")
    # export_downloads() returns paths relative to its own output dir; the
    # manifest's paths are all relative to web/assets/, so prefix here.
    raw_downloads = export_downloads(str(ASSET_DIR / "downloads"))
    downloads_map = {label: f"downloads/{path}" for label, path in raw_downloads.items()}

    console.print("[bold]5/5[/bold] manifest.json")
    manifest = write_manifest(
        str(ASSET_DIR / "manifest.json"),
        scene_stats=stats,
        fea_results=fea_results,
        downloads=downloads_map,
    )
    problems = validate(manifest, assets_dir=str(ASSET_DIR))
    if problems:
        console.print("[red]Manifest validation problems:[/red]")
        for p in problems:
            console.print(f"  - {p}")
        raise typer.Exit(1)
    console.print(f"[green]OK[/green] — {manifest['bom']['total_mass_g']:.1f} g all-up")


def main() -> None:
    try:
        app()
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented yet:[/yellow] {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()
