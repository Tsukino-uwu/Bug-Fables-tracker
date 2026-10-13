# The pack's checks, all, every time: the export from the apworld, the logic parity tests (lupa) and PopTracker's
# pack-checker (strict, against PopTracker's own schemas at the commit the pack was checked against), on the folder
# and on the zip a release would ship. Run from anywhere.
# -Archipelago: your Archipelago checkout, with the randomizer's apworld linked in as worlds/bug_fables.
# First time: python -m venv --system-site-packages .venv; .venv\Scripts\python -m pip install -r requirements-dev.txt
param(
    [Parameter(Mandatory)] [string] $Archipelago,
    [int] $Seeds = 200
)
$ErrorActionPreference = 'Continue'
$env:SKIP_REQUIREMENTS_UPDATE = '1'
$pack = Split-Path -Parent $PSScriptRoot
$python = Join-Path $pack '.venv\Scripts\python.exe'
$schemas = 'https://raw.githubusercontent.com/black-sliver/PopTracker/dad367501cc1a8e892305a9779c30431246d9ae4/schema/packs/'
$failed = @()

Write-Host '== Export'
& $python (Join-Path $PSScriptRoot 'export.py') --archipelago $Archipelago
if ($LASTEXITCODE -ne 0) { $failed += 'export' }

Write-Host "== Parity: $Seeds seeds"
$env:ARCHIPELAGO_DIR = (Resolve-Path $Archipelago).Path
$env:PARITY_SEEDS = "$Seeds"
& $python -m pytest (Join-Path $pack 'tests') -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { $failed += 'parity' }

Write-Host '== pack-checker'
& (Join-Path $pack '.venv\Scripts\pack-checker.exe') -b --strict --schema $schemas $pack
if ($LASTEXITCODE -ne 0) { $failed += 'pack-checker' }

# What a release's download would hold: the tracked files with their uncommitted changes, less export-ignore.
Write-Host '== The release zip'
$ref = git -C $pack stash create
if (-not $ref) { $ref = 'HEAD' }
$zip = Join-Path $pack 'build\release.zip'
New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
git -C $pack archive --format=zip -o $zip $ref
& $python (Join-Path $PSScriptRoot 'release.py') check-zip $zip
if ($LASTEXITCODE -ne 0) { $failed += 'release zip' }
& (Join-Path $pack '.venv\Scripts\pack-checker.exe') -b --strict --schema $schemas $zip
if ($LASTEXITCODE -ne 0) { $failed += 'pack-checker on the release zip' }

if ($failed) { Write-Host "FAILED: $($failed -join ', ')"; exit 1 }
Write-Host 'All passed'
