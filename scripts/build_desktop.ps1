param(
    [switch]$SkipInstall,
    [switch]$SkipSidecar,
    [switch]$SkipBundle,
    [switch]$RuntimePackage,
    [string]$RuntimeRoot = "",
    [string]$RuntimeSolver = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $ProjectRoot "desktop"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}
$ResourceRoot = Join-Path $DesktopRoot "src-tauri\resources"
$ExpectedResourceRoot = (Join-Path $ProjectRoot "desktop\src-tauri\resources")
if ([System.IO.Path]::GetFullPath($ResourceRoot) -ne [System.IO.Path]::GetFullPath($ExpectedResourceRoot)) {
    throw "Refusing to stage resources outside the desktop resource directory."
}

if (-not $SkipInstall) {
    & $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed with exit code $LASTEXITCODE." }
    npm --prefix $DesktopRoot install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE." }
}

$StageItems = Get-ChildItem -LiteralPath $ResourceRoot -Force | Where-Object { $_.Name -ne ".keep" }
foreach ($Item in $StageItems) {
    Remove-Item -LiteralPath $Item.FullName -Recurse -Force
}

$BackendDist = Join-Path $ProjectRoot "build\desktop-sidecar"
$BackendExecutable = Join-Path $BackendDist "topoptpilot-backend.exe"
if (-not $SkipSidecar) {
    if (Test-Path $BackendExecutable) {
        Remove-Item -LiteralPath $BackendExecutable -Force
    }
    & $PythonExe -m PyInstaller --noconfirm --clean --onefile --name topoptpilot-backend `
        --distpath $BackendDist --workpath (Join-Path $ProjectRoot "build\pyinstaller") `
        --specpath (Join-Path $ProjectRoot "build") `
        --paths $ProjectRoot --hidden-import idesktop_v2.api.app --hidden-import idesktop_v2.api.desktop_sidecar `
        --hidden-import solver.topopt_engine --hidden-import solver.topopt3d `
        --collect-submodules openai `
        (Join-Path $ProjectRoot "idesktop_v2\api\desktop_sidecar.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
}

if (-not (Test-Path $BackendExecutable)) { throw "Sidecar executable is missing; omit -SkipSidecar or provide the existing build artifact." }
New-Item -ItemType Directory -Force -Path (Join-Path $ResourceRoot "bin") | Out-Null
Copy-Item -LiteralPath $BackendExecutable -Destination (Join-Path $ResourceRoot "bin\topoptpilot-backend.exe")

$MatlabSource = Join-Path $ProjectRoot "matlab"
if (-not (Test-Path (Join-Path $MatlabSource "engineering\TopOpt-3D"))) { throw "v2 MATLAB engineering source was not found." }
Copy-Item -LiteralPath $MatlabSource -Destination (Join-Path $ResourceRoot "matlab") -Recurse
$StagedMatlabRoot = Join-Path $ResourceRoot "matlab"
$StagedMatlabDist = Join-Path $StagedMatlabRoot "dist"
if (Test-Path -LiteralPath $StagedMatlabDist) {
    Remove-Item -LiteralPath $StagedMatlabDist -Recurse -Force
}

Get-ChildItem -LiteralPath $StagedMatlabRoot -Recurse -Force -File |
    Where-Object {
        $_.Name -like "*.codex-*" -or
        $_.Name -like "*.codex-original" -or
        $_.Name -like "*.codex-replace" -or
        $_.Name -like "*.bad" -or

        $_.Name -like ".tmp-*"
    } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

if ($RuntimePackage) {
    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        throw "RuntimePackage requires -RuntimeRoot pointing to a verified MATLAB Runtime root."
    }
    $RuntimeRootPath = (Resolve-Path -LiteralPath $RuntimeRoot -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $RuntimeRootPath -PathType Container)) {
        throw "RuntimePackage requires -RuntimeRoot to be a directory."
    }
    $RuntimeDll = Get-ChildItem -LiteralPath $RuntimeRootPath -Recurse -Force -File -Filter "mclmcrrt*.dll" |
        Where-Object { $_.FullName -match "\\(runtime|bin)\\win64\\" } |
        Select-Object -First 1
    if (-not $RuntimeDll) {
        throw "RuntimePackage requires a mclmcrrt*.dll under runtime/bin/win64."
    }
    $RuntimeUninstaller = Join-Path $RuntimeRootPath "bin\win64\Uninstall_MATLAB_Runtime.exe"
    if (-not (Test-Path -LiteralPath $RuntimeUninstaller -PathType Leaf)) {
        throw "RuntimePackage requires a standalone MATLAB Runtime root; a full MATLAB installation is not redistributable as Runtime."
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeSolver)) {
        $RuntimeSolver = Join-Path $ProjectRoot "matlab\dist\solver\TopOptSolver.exe"
    }
    $RuntimeSolverPath = (Resolve-Path -LiteralPath $RuntimeSolver -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $RuntimeSolverPath -PathType Leaf) -or [System.IO.Path]::GetExtension($RuntimeSolverPath).ToLowerInvariant() -ne ".exe") {
        throw "RuntimePackage requires a regular TopOptSolver.exe file."
    }
    $RuntimeStageRoot = Join-Path $ResourceRoot "runtime"
    $RuntimeSolverStage = Join-Path $RuntimeStageRoot "solver"
    New-Item -ItemType Directory -Force -Path $RuntimeSolverStage | Out-Null
    Copy-Item -LiteralPath $RuntimeSolverPath -Destination (Join-Path $RuntimeSolverStage "TopOptSolver.exe")
    $RuntimeLeaf = Split-Path -Path $RuntimeRootPath -Leaf
    if ([string]::IsNullOrWhiteSpace($RuntimeLeaf)) {
        throw "RuntimePackage cannot determine the MATLAB Runtime directory name."
    }
    $RuntimeDestination = Join-Path $RuntimeStageRoot (Join-Path "MATLAB Runtime" $RuntimeLeaf)
    Copy-Item -LiteralPath $RuntimeRootPath -Destination $RuntimeDestination -Recurse
    $RelativeDll = $RuntimeDll.FullName.Substring($RuntimeRootPath.Length).TrimStart("\", "/").Replace("\", "/")
    $RuntimeManifest = [ordered]@{
        schemaVersion = 1
        packageKind = "idesktop-v2-runtime"
        runtimeRoot = ("runtime/MATLAB Runtime/" + $RuntimeLeaf)
        runtimeDll = ("runtime/MATLAB Runtime/" + $RuntimeLeaf + "/" + $RelativeDll)
        solver = "runtime/solver/TopOptSolver.exe"
        runtimeDllSha256 = (Get-FileHash -LiteralPath $RuntimeDll.FullName -Algorithm SHA256).Hash
        solverSha256 = (Get-FileHash -LiteralPath $RuntimeSolverPath -Algorithm SHA256).Hash
    }
    $RuntimeManifest | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $RuntimeStageRoot "runtime-manifest.json") -Encoding UTF8
} elseif (-not [string]::IsNullOrWhiteSpace($RuntimeRoot) -or -not [string]::IsNullOrWhiteSpace($RuntimeSolver)) {
    throw "-RuntimeRoot and -RuntimeSolver require -RuntimePackage."
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "package.json") -Destination $ResourceRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "package-lock.json") -Destination $ResourceRoot
if (Test-Path (Join-Path $ProjectRoot "AGENTS.md")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "AGENTS.md") -Destination $ResourceRoot
}

if (-not $SkipBundle) {
    if (-not (Test-Path (Join-Path $ProjectRoot "vendor\matlab-mcp-server"))) { throw "MATLAB MCP vendor resource is missing." }
    if (-not (Test-Path (Join-Path $ProjectRoot ".pi"))) { throw ".pi runtime resource is missing." }
    if (-not (Test-Path (Join-Path $ProjectRoot "mcp"))) { throw "mcp resource is missing." }
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
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "vendor\matlab-mcp-server") -Destination (Join-Path $ResourceRoot "vendor\matlab-mcp-server") -Recurse
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".pi") -Destination (Join-Path $ResourceRoot ".pi") -Recurse
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "node_modules") -Destination (Join-Path $ResourceRoot "node_modules") -Recurse
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "mcp") -Destination (Join-Path $ResourceRoot "mcp") -Recurse
    Get-ChildItem -LiteralPath $ResourceRoot -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
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
} else {
    Write-Host "SkipBundle: staged sidecar and MATLAB source only; formal vendor resources are not required."
}
