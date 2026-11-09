# Baut die Extension, erzeugt den Extension-Index und legt ein GitHub-Release an.
#
# Blender holt Updates über diese Repository-URL (einmalig in Blender eintragen):
#   https://github.com/timborabora/comfy_bridge/releases/latest/download/index.json
# Preferences > Get Extensions > Repositories > + > Add Remote Repository,
# „Check for Updates on Startup“ anhaken.
#
# Voraussetzung: gh ist eingeloggt, Version in comfy_bridge/blender_manifest.toml erhöht.
param(
    [string]$Blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = "C:\Program Files\GitHub CLI\gh.exe" }
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$version = (Select-String -Path (Join-Path $root "comfy_bridge\blender_manifest.toml") -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value

Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory $dist | Out-Null
& $Blender --factory-startup --command extension build --source-dir (Join-Path $root "comfy_bridge") --output-dir $dist
& $Blender --factory-startup --command extension server-generate --repo-dir $dist
$zip = Get-ChildItem $dist -Filter "comfy_bridge-$version.zip"
if (-not $zip) { throw "Paket comfy_bridge-$version.zip wurde nicht gebaut." }

Write-Host "Version $version gebaut: $($zip.FullName)"
if ($DryRun) { Write-Host "DryRun: kein Release angelegt."; exit 0 }

# git and gh report progress on stderr; with "Stop" Windows PowerShell treats that as an error
$ErrorActionPreference = "Continue"
git -C $root tag "v$version"
git -C $root push origin "v$version"
if ($LASTEXITCODE -ne 0) { throw "Pushing tag v$version failed." }
& $gh release create "v$version" $zip.FullName (Join-Path $dist "index.json") --repo (git -C $root remote get-url origin) --title "Comfy Bridge $version" --notes "Comfy Bridge $version"
