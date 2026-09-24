<#
.SYNOPSIS
    Set up .venv311 from scratch and verify the toolchain.

.DESCRIPTION
    Safe to re-run. Creates the virtual environment if it is missing,
    installs pinned dependencies, installs this package in editable mode,
    vendors three.js, and then runs a smoke check that imports the CAD kernel
    and builds a solid — because a successful pip install does not prove the
    OCCT binary actually loads on this machine.
#>
param(
    [switch]$SkipVendor
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv311"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating .venv311 with Python 3.11..."
    & py -3.11 -m venv $venv
    if (-not (Test-Path $py)) { throw "Could not create the virtual environment. Is Python 3.11 installed? Check 'py -0p'." }
}

Write-Host "Python: $(& $py -V)"

& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r (Join-Path $root "requirements.txt")
& $py -m pip install -e $root --no-deps

if (-not $SkipVendor) {
    Write-Host "Vendoring three.js..."
    & (Join-Path $PSScriptRoot "fetch_vendor.ps1")
}

Write-Host "Verifying the CAD kernel actually loads..."
& $py -c "from build123d import BuildPart, Cylinder;`nwith BuildPart() as p: Cylinder(radius=5, height=10)`nprint(f'OCCT ok, volume {p.part.volume:.1f} mm3')"

Write-Host ""
Write-Host "Ready." -ForegroundColor Green
Write-Host "  .venv311\Scripts\python.exe -m drone_demo --help"
Write-Host "  .venv311\Scripts\python.exe -m drone_demo all"
Write-Host "  .venv311\Scripts\python.exe -m drone_demo serve"
