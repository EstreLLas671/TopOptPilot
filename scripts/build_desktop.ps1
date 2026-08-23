param(
    [switch]$SkipInstall,
    [switch]$SkipSidecar,
    [switch]$SkipBundle
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $ProjectRoot "desktop"
$ResourceRoot = Join-Path $DesktopRoot "src-tauri\resources"
$ExpectedResourceRoot = (Join-Path $ProjectRoot "desktop\src-tauri\resources")
if ([System.IO.Path]::GetFullPath($ResourceRoot) -ne [System.IO.Path]::GetFullPath($ExpectedResourceRoot)) {
    throw "Refusing to stage resources outside the desktop resource directory."
}

if (-not $SkipInstall) {
    python -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
    npm --prefix $DesktopRoot install
}

$StageItems = Get-ChildItem -LiteralPath $ResourceRoot -Force | Where-Object { $_.Name -ne ".keep" }
foreach ($Item in $StageItems) {
    Remove-Item -LiteralPath $Item.FullName -Recurse -Force
}

$BackendDist = Join-Path $ProjectRoot "build\desktop-sidecar"
if (-not $SkipSidecar) {
    python -m PyInstaller --noconfirm --clean --onefile --name topoptpilot-backend `
        --distpath $BackendDist --workpath (Join-Path $ProjectRoot "build\pyinstaller") `
        --specpath (Join-Path $ProjectRoot "build") `
        --paths $ProjectRoot --hidden-import topoptpilot.api.fastapi_app `
        --hidden-import solver.topopt_engine --hidden-import solver.topopt3d `
        (Join-Path $ProjectRoot "topoptpilot\api\desktop_sidecar.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller sidecar build failed with exit code $LASTEXITCODE." }
}

if (-not (Test-Path (Join-Path $BackendDist "topoptpilot-backend.exe"))) {
    throw "Desktop sidecar executable is missing after the build step."
}

New-Item -ItemType Directory -Force -Path (Join-Path $ResourceRoot "bin") | Out-Null
Copy-Item -LiteralPath (Join-Path $BackendDist "topoptpilot-backend.exe") `
    -Destination (Join-Path $ResourceRoot "bin\topoptpilot-backend.exe")

$NodeVendor = Join-Path $ProjectRoot "vendor\node"
if (-not (Test-Path (Join-Path $NodeVendor "node.exe"))) {
    $NodeZip = Join-Path $env:TEMP "topoptpilot-node-v24.14.0-win-x64.zip"
    curl.exe -L "https://nodejs.org/dist/v24.14.0/node-v24.14.0-win-x64.zip" -o $NodeZip
    $NodeExtract = Join-Path $env:TEMP "topoptpilot-node-v24.14.0"
    if (Test-Path $NodeExtract) { Remove-Item -LiteralPath $NodeExtract -Recurse -Force }
    Expand-Archive -LiteralPath $NodeZip -DestinationPath $NodeExtract -Force
    New-Item -ItemType Directory -Force -Path $NodeVendor | Out-Null
    Copy-Item -Path (Join-Path $NodeExtract "node-v24.14.0-win-x64\*") -Destination $NodeVendor -Recurse -Force
}

New-Item -ItemType Directory -Force -Path (Join-Path $ResourceRoot "node") | Out-Null
Copy-Item -LiteralPath (Join-Path $NodeVendor "node.exe") -Destination (Join-Path $ResourceRoot "node\node.exe")
Copy-Item -LiteralPath (Join-Path $NodeVendor "LICENSE") -Destination (Join-Path $ResourceRoot "node\LICENSE")
New-Item -ItemType Directory -Force -Path (Join-Path $ResourceRoot "vendor") | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "vendor\matlab-mcp-server") `
    -Destination (Join-Path $ResourceRoot "vendor\matlab-mcp-server") -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot ".pi") -Destination (Join-Path $ResourceRoot ".pi") -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "node_modules") -Destination (Join-Path $ResourceRoot "node_modules") -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "mcp") -Destination (Join-Path $ResourceRoot "mcp") -Recurse
$GeneratedMatlabState = Join-Path $ResourceRoot "mcp\matlab_mcp\MathWorks"
if (Test-Path $GeneratedMatlabState) {
    $ResolvedGeneratedState = (Resolve-Path -LiteralPath $GeneratedMatlabState).Path
    if (-not $ResolvedGeneratedState.StartsWith([System.IO.Path]::GetFullPath($ResourceRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove generated MATLAB state outside staged resources."
    }
    Remove-Item -LiteralPath $ResolvedGeneratedState -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $ResourceRoot "topoptpilot\knowledge") | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "topoptpilot\knowledge\documents") `
    -Destination (Join-Path $ResourceRoot "topoptpilot\knowledge\documents") -Recurse
$SolverRoot = Get-ChildItem -LiteralPath $ProjectRoot -Directory | Where-Object {
    Test-Path (Join-Path $_.FullName "TopOpt-3D")
} | Select-Object -First 1
if (-not $SolverRoot) { throw "MATLAB solver module directory was not found." }
Copy-Item -LiteralPath $SolverRoot.FullName -Destination (Join-Path $ResourceRoot $SolverRoot.Name) -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "package.json") -Destination $ResourceRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "package-lock.json") -Destination $ResourceRoot
if (Test-Path (Join-Path $ProjectRoot "AGENTS.md")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "AGENTS.md") -Destination $ResourceRoot
}
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "vendor\matlab-mcp-server") -Recurse -File | `
    Get-FileHash -Algorithm SHA256 | ForEach-Object { "{0}  {1}" -f $_.Hash,$_.Path.Substring($ProjectRoot.Length+1) } | `
    Set-Content -LiteralPath (Join-Path $ResourceRoot "MATLAB_MCP_SHA256.txt") -Encoding utf8
Get-ChildItem -LiteralPath $ResourceRoot -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }

if (-not $SkipBundle) {
    $ReleaseResources = Join-Path $DesktopRoot "src-tauri\target\release\resources"
    $ExpectedReleaseResources = Join-Path $ProjectRoot "desktop\src-tauri\target\release\resources"
    if (Test-Path $ReleaseResources) {
        if ([System.IO.Path]::GetFullPath($ReleaseResources) -ne [System.IO.Path]::GetFullPath($ExpectedReleaseResources)) {
            throw "Refusing to clean an unexpected release resource directory."
        }
        Get-ChildItem -LiteralPath $ReleaseResources -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
        Remove-Item -LiteralPath $ReleaseResources -Recurse -Force
    }
    $env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
    $env:CARGO_HTTP_PROXY = ""
    npm --prefix $DesktopRoot run tauri build
    if ($LASTEXITCODE -ne 0) { throw "Tauri bundle build failed with exit code $LASTEXITCODE." }
}
