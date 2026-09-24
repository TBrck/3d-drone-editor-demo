<#
.SYNOPSIS
    Download three.js into web/vendor/ so the site has no CDN dependency.

.DESCRIPTION
    The published page must keep working regardless of anyone else's uptime,
    and it is going in a job application, so a broken CDN on the wrong day is
    not an acceptable risk. Vendoring costs about 1.2 MB in the repo and
    removes that risk entirely. It also means the page works offline, which
    is handy when demonstrating it on a train.

    Run once. The files are committed.

.PARAMETER Version
    three.js version. 0.185.1 was current when this project was set up. Only
    change it deliberately: the addons under examples/jsm import from the
    matching core build, and mixing versions produces confusing runtime
    errors rather than a clean failure.
#>
param(
    [string]$Version = "0.185.1"
)

$ErrorActionPreference = "Stop"

$root      = Split-Path -Parent $PSScriptRoot
$vendor    = Join-Path $root "web\vendor"
$addons    = Join-Path $vendor "addons"
$base      = "https://unpkg.com/three@$Version"

New-Item -ItemType Directory -Force -Path $vendor  | Out-Null
New-Item -ItemType Directory -Force -Path $addons  | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $addons "controls")  | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $addons "loaders")   | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $addons "environments") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $addons "utils")     | Out-Null

# Keep this list minimal. Every addon pulled in is another file to keep in
# step on a version bump, and the viewer only needs these.
#
# Two dependencies here are easy to miss and were only found by actually
# loading the page in a browser and reading the 404s:
#   - three.module.js imports './three.core.js' — recent three.js builds
#     split the module into two files. Without it, `import * as THREE from
#     'three'` fails at runtime with no build-time warning.
#   - GLTFLoader.js imports BufferGeometryUtils.js and SkeletonUtils.js
#     internally even though the viewer never calls either directly.
$files = @{
    "build/three.module.js"                       = "three.module.js"
    "build/three.core.js"                          = "three.core.js"
    "examples/jsm/controls/OrbitControls.js"      = "addons/controls/OrbitControls.js"
    "examples/jsm/loaders/GLTFLoader.js"          = "addons/loaders/GLTFLoader.js"
    "examples/jsm/environments/RoomEnvironment.js" = "addons/environments/RoomEnvironment.js"
    "examples/jsm/utils/BufferGeometryUtils.js"   = "addons/utils/BufferGeometryUtils.js"
    "examples/jsm/utils/SkeletonUtils.js"         = "addons/utils/SkeletonUtils.js"
}

foreach ($src in $files.Keys) {
    $dest = Join-Path $vendor $files[$src]
    Write-Host "  $src -> web/vendor/$($files[$src])"
    Invoke-WebRequest -Uri "$base/$src" -OutFile $dest -UseBasicParsing
}

Set-Content -Path (Join-Path $vendor "VERSION") -Value $Version -Encoding utf8
Write-Host ""
Write-Host "three.js $Version vendored into web/vendor/." -ForegroundColor Green
Write-Host "The importmap in web/index.html already points at these paths."
