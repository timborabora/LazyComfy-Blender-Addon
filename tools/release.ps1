# Builds the extension, generates the extension index and creates a GitHub release.
#
# Blender gets updates from this repository URL (add it once in Blender):
#   https://github.com/timborabora/LazyComfy-Blender-Addon/releases/latest/download/index.json
# Preferences > Get Extensions > Repositories > + > Add Remote Repository,
# tick "Check for Updates on Startup".
#
# Requires: gh logged in, version bumped in lazy_comfy/blender_manifest.toml.
param(
    [string]$Blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    [string]$Notes = "",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = "C:\Program Files\GitHub CLI\gh.exe" }
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$version = (Select-String -Path (Join-Path $root "lazy_comfy\blender_manifest.toml") -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value

Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory $dist | Out-Null
& $Blender --factory-startup --command extension build --source-dir (Join-Path $root "lazy_comfy") --output-dir $dist
& $Blender --factory-startup --command extension server-generate --repo-dir $dist
$zip = Get-ChildItem $dist -Filter "lazy_comfy-$version.zip"
if (-not $zip) { throw "Package lazy_comfy-$version.zip was not built." }

Write-Host "Built version ${version}: $($zip.FullName)"
if ($DryRun) { Write-Host "DryRun: no release created."; exit 0 }

# git and gh report progress on stderr; with "Stop" Windows PowerShell treats that as an error
$ErrorActionPreference = "Continue"
git -C $root tag "v$version"
git -C $root push origin "v$version"
if ($LASTEXITCODE -ne 0) { throw "Pushing tag v$version failed." }
if (-not $Notes) { $Notes = "Lazy Comfy $version" }
& $gh release create "v$version" $zip.FullName (Join-Path $dist "index.json") --repo (git -C $root remote get-url origin) --title "Lazy Comfy $version" --notes $Notes
