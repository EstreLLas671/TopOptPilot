param(
    [switch]$SkipInstall,
    [switch]$SkipSidecar,
    [switch]$SkipBundle,
    [switch]$RuntimePackage,
    [string]$RuntimeRoot = "",
    [string]$RuntimeSolver = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $ProjectRoot "desktop"
$ResourceRoot = Join-Path $DesktopRoot "src-tauri\resources"
$ResourceParent = Split-Path -Parent $ResourceRoot
$ExpectedResourceRoot = Join-Path $ProjectRoot "desktop\src-tauri\resources"
if ([System.IO.Path]::GetFullPath($ResourceRoot) -ne [System.IO.Path]::GetFullPath($ExpectedResourceRoot)) {
    throw "Refusing to stage resources outside the desktop resource directory."
}

function Resolve-BuildPython([string]$Requested) {
    $Candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { $Candidates.Add($Requested) }
    $Candidates.Add((Join-Path $ProjectRoot ".venv\Scripts\python.exe"))

    $GitCommonRaw = (& git -C $ProjectRoot rev-parse --git-common-dir 2>$null | Select-Object -First 1)
    if ($GitCommonRaw) {
        $GitCommon = if ([System.IO.Path]::IsPathRooted($GitCommonRaw)) {
            [System.IO.Path]::GetFullPath($GitCommonRaw)
        } else {
            [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $GitCommonRaw))
        }
        $CheckoutRoot = Split-Path -Parent $GitCommon
        if ($CheckoutRoot) { $Candidates.Add((Join-Path $CheckoutRoot ".venv\Scripts\python.exe")) }
    }

    $SystemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($SystemPython) { $Candidates.Add($SystemPython.Source) }
    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "No usable Python executable was found. Pass -PythonExe explicitly."
}

function Require-File([string]$Path, [string]$Message) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw $Message }
}

function Require-Directory([string]$Path, [string]$Message) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw $Message }
}

$PythonExe = Resolve-BuildPython -Requested $PythonExe
& $PythonExe -c "import PyInstaller"
if ($LASTEXITCODE -ne 0) { throw "Selected Python cannot import PyInstaller: $PythonExe" }

# Resolve and validate every immutable build input before creating or deleting staging.
$SidecarSource = Join-Path $ProjectRoot "idesktop_v2\api\desktop_sidecar.py"
$MatlabSource = Join-Path $ProjectRoot "matlab"
$McpSource = Join-Path $ProjectRoot "mcp"
$SolverSource = Join-Path $ProjectRoot "求解器模块"
$PiSource = Join-Path $ProjectRoot ".pi"
$NodeVendor = Join-Path $ProjectRoot "vendor\node"
$NodeExecutable = Join-Path $NodeVendor "node.exe"
$NodeLicense = Join-Path $NodeVendor "LICENSE"
$MatlabMcpSource = Join-Path $ProjectRoot "vendor\matlab-mcp-server"
$MatlabMcpExecutable = Join-Path $MatlabMcpSource "matlab-mcp-server-windows-x64.exe"
$RootNodeModules = Join-Path $ProjectRoot "node_modules"
$PackageJson = Join-Path $ProjectRoot "package.json"
$PackageLock = Join-Path $ProjectRoot "package-lock.json"
$AgentsFile = Join-Path $ProjectRoot "AGENTS.md"

Require-File $SidecarSource "Desktop sidecar source is missing."
Require-Directory (Join-Path $MatlabSource "engineering\TopOpt_2D") "v2 2D MATLAB engineering source was not found."
Require-Directory (Join-Path $MatlabSource "engineering\TopOpt-3D") "v2 3D MATLAB engineering source was not found."
Require-File (Join-Path $MatlabSource "engineering\solver-sources.json") "MATLAB solver source manifest was not found."
Require-File $PackageJson "Root package.json is missing."
Require-File $PackageLock "Root package-lock.json is missing."
if (-not $SkipBundle) {
    Require-Directory $McpSource "mcp resource is missing."
    Require-Directory $SolverSource "MATLAB MCP solver source is missing."
    Require-Directory $PiSource ".pi runtime resource is missing."
    Require-File $NodeExecutable "Bundled vendor node.exe is missing; provision vendor/node before building."
    Require-File $NodeLicense "Bundled vendor Node LICENSE is missing."
    Require-File $MatlabMcpExecutable "MATLAB MCP vendor executable is missing."
    Require-Directory $RootNodeModules "Root node_modules is missing; install the pinned Pi runtime dependencies before building."
}

$RuntimeRootPath = $null
$RuntimeDll = $null
$RuntimeUninstaller = $null
$RuntimeSolverPath = $null
if ($RuntimePackage) {
    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        throw "RuntimePackage requires -RuntimeRoot pointing to a verified MATLAB Runtime root."
    }
    $RuntimeRootPath = (Resolve-Path -LiteralPath $RuntimeRoot -ErrorAction Stop).Path
    Require-Directory $RuntimeRootPath "RuntimePackage requires -RuntimeRoot to be a directory."
    $RuntimeDll = Get-ChildItem -LiteralPath $RuntimeRootPath -Recurse -Force -File -Filter "mclmcrrt*.dll" |
        Where-Object { $_.FullName -match "\\(runtime|bin)\\win64\\" } | Select-Object -First 1
    if (-not $RuntimeDll) { throw "RuntimePackage requires a mclmcrrt*.dll under runtime/bin/win64." }
    $RuntimeUninstaller = Join-Path $RuntimeRootPath "bin\win64\Uninstall_MATLAB_Runtime.exe"
    Require-File $RuntimeUninstaller "RuntimePackage requires a standalone MATLAB Runtime root; a full MATLAB installation is not redistributable as Runtime."
    if ([string]::IsNullOrWhiteSpace($RuntimeSolver)) {
        $RuntimeSolver = Join-Path $ProjectRoot "matlab\dist\solver\TopOptSolver.exe"
    }
    $RuntimeSolverPath = (Resolve-Path -LiteralPath $RuntimeSolver -ErrorAction Stop).Path
    if ([System.IO.Path]::GetExtension($RuntimeSolverPath).ToLowerInvariant() -ne ".exe") {
        throw "RuntimePackage requires a regular TopOptSolver.exe file."
    }
    Require-File $RuntimeSolverPath "RuntimePackage requires a regular TopOptSolver.exe file."
} elseif (-not [string]::IsNullOrWhiteSpace($RuntimeRoot) -or -not [string]::IsNullOrWhiteSpace($RuntimeSolver)) {
    throw "-RuntimeRoot and -RuntimeSolver require -RuntimePackage."
}

if (-not $SkipInstall) {
    & $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed with exit code $LASTEXITCODE." }
    npm --prefix $DesktopRoot install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE." }
}

$BackendDist = Join-Path $ProjectRoot "build\desktop-sidecar"
$BackendExecutable = Join-Path $BackendDist "topoptpilot-backend.exe"
if (-not $SkipSidecar) {
    if (Test-Path -LiteralPath $BackendExecutable) {
        Remove-Item -LiteralPath $BackendExecutable -Force
    }
    & $PythonExe -m PyInstaller --noconfirm --clean --onefile --name topoptpilot-backend `
        --distpath $BackendDist --workpath (Join-Path $ProjectRoot "build\pyinstaller") `
        --specpath (Join-Path $ProjectRoot "build") `
        --paths $ProjectRoot --hidden-import idesktop_v2.api.app --hidden-import idesktop_v2.api.desktop_sidecar `
        --hidden-import solver.topopt_engine --hidden-import solver.topopt3d `
        --collect-submodules openai `
        $SidecarSource
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
}
Require-File $BackendExecutable "Sidecar executable is missing; omit -SkipSidecar or provide the existing build artifact."

$StageRoot = Join-Path $ResourceParent ("resources.staging-" + $PID)
$BackupResourceRoot = Join-Path $ResourceParent ("resources.backup-" + $PID)
$Swapped = $false
if (Test-Path -LiteralPath $StageRoot) { Remove-Item -LiteralPath $StageRoot -Recurse -Force }
if (Test-Path -LiteralPath $BackupResourceRoot) { Remove-Item -LiteralPath $BackupResourceRoot -Recurse -Force }

try {
    New-Item -ItemType Directory -Force -Path (Join-Path $StageRoot "bin") | Out-Null
    Copy-Item -LiteralPath (Join-Path $ResourceRoot ".keep") -Destination (Join-Path $StageRoot ".keep")
    Copy-Item -LiteralPath $BackendExecutable -Destination (Join-Path $StageRoot "bin\topoptpilot-backend.exe")
    Copy-Item -LiteralPath $MatlabSource -Destination (Join-Path $StageRoot "matlab") -Recurse
    $StagedMatlabRoot = Join-Path $StageRoot "matlab"
    $StagedMatlabDist = Join-Path $StagedMatlabRoot "dist"
    if (Test-Path -LiteralPath $StagedMatlabDist) {
        Remove-Item -LiteralPath $StagedMatlabDist -Recurse -Force
    }
    Get-ChildItem -LiteralPath $StagedMatlabRoot -Recurse -Force -File |
        Where-Object { $_.Name -like "*.codex-*" -or $_.Name -like "*.codex-original" -or
            $_.Name -like "*.codex-replace" -or $_.Name -like "*.bad" -or $_.Name -like ".tmp-*" } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

    Copy-Item -LiteralPath $PackageJson -Destination $StageRoot
    Copy-Item -LiteralPath $PackageLock -Destination $StageRoot
    if (Test-Path -LiteralPath $AgentsFile -PathType Leaf) { Copy-Item -LiteralPath $AgentsFile -Destination $StageRoot }

    if ($RuntimePackage) {
        $RuntimeStageRoot = Join-Path $StageRoot "runtime"
        $RuntimeSolverStage = Join-Path $RuntimeStageRoot "solver"
        New-Item -ItemType Directory -Force -Path $RuntimeSolverStage | Out-Null
        Copy-Item -LiteralPath $RuntimeSolverPath -Destination (Join-Path $RuntimeSolverStage "TopOptSolver.exe")
        $RuntimeLeaf = Split-Path -Path $RuntimeRootPath -Leaf
        if ([string]::IsNullOrWhiteSpace($RuntimeLeaf)) { throw "RuntimePackage cannot determine the MATLAB Runtime directory name." }
        $RuntimeDestination = Join-Path $RuntimeStageRoot (Join-Path "MATLAB Runtime" $RuntimeLeaf)
        Copy-Item -LiteralPath $RuntimeRootPath -Destination $RuntimeDestination -Recurse
        $RelativeDll = $RuntimeDll.FullName.Substring($RuntimeRootPath.Length).TrimStart("\", "/").Replace("\", "/")
        [ordered]@{
            schemaVersion = 1; packageKind = "idesktop-v2-runtime"
            runtimeRoot = ("runtime/MATLAB Runtime/" + $RuntimeLeaf)
            runtimeDll = ("runtime/MATLAB Runtime/" + $RuntimeLeaf + "/" + $RelativeDll)
            solver = "runtime/solver/TopOptSolver.exe"
            runtimeDllSha256 = (Get-FileHash -LiteralPath $RuntimeDll.FullName -Algorithm SHA256).Hash
            solverSha256 = (Get-FileHash -LiteralPath $RuntimeSolverPath -Algorithm SHA256).Hash
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $RuntimeStageRoot "runtime-manifest.json") -Encoding UTF8
    }

    if (-not $SkipBundle) {
        New-Item -ItemType Directory -Force -Path (Join-Path $StageRoot "node") | Out-Null
        Copy-Item -LiteralPath $NodeExecutable -Destination (Join-Path $StageRoot "node\node.exe")
        Copy-Item -LiteralPath $NodeLicense -Destination (Join-Path $StageRoot "node\LICENSE")
        New-Item -ItemType Directory -Force -Path (Join-Path $StageRoot "vendor") | Out-Null
        Copy-Item -LiteralPath $MatlabMcpSource -Destination (Join-Path $StageRoot "vendor\matlab-mcp-server") -Recurse
        Copy-Item -LiteralPath $PiSource -Destination (Join-Path $StageRoot ".pi") -Recurse
        Copy-Item -LiteralPath $RootNodeModules -Destination (Join-Path $StageRoot "node_modules") -Recurse
        Copy-Item -LiteralPath $McpSource -Destination (Join-Path $StageRoot "mcp") -Recurse
        Copy-Item -LiteralPath $SolverSource -Destination (Join-Path $StageRoot "求解器模块") -Recurse
        Get-ChildItem -LiteralPath $StageRoot -Recurse -Force -File |
            Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
        @(Get-ChildItem -LiteralPath $StageRoot -Recurse -Force -Directory |
            Where-Object { $_.Name -eq "__pycache__" } |
            Sort-Object { $_.FullName.Length } -Descending) |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
        foreach ($RequiredRelative in @(
            "bin\topoptpilot-backend.exe", "node\node.exe",
            "vendor\matlab-mcp-server\matlab-mcp-server-windows-x64.exe",
            "mcp\matlab_mcp\topopt-tools.json",
            "matlab\engineering\TopOpt_2D\topopt_main.m",
            "matlab\engineering\TopOpt-3D\topopt3d_main.m",
            "matlab\engineering\solver-sources.json",
            "求解器模块\2D\TopOpt_integrated\TopOpt_integrated\topopt_main.m",
            "求解器模块\TopOpt-3D\TopOpt-3D\topopt3d_main.m"
        )) {
            Require-File (Join-Path $StageRoot $RequiredRelative) "Staged resource is missing: $RequiredRelative"
        }
        Get-ChildItem -LiteralPath $StageRoot -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
    }

    if (Test-Path -LiteralPath $ResourceRoot) {
        Move-Item -LiteralPath $ResourceRoot -Destination $BackupResourceRoot
    }
    Move-Item -LiteralPath $StageRoot -Destination $ResourceRoot
    $Swapped = $true

    if (-not $SkipBundle) {
        $ReleaseResourceRoot = Join-Path $DesktopRoot "src-tauri\target\release\resources"
        if (Test-Path -LiteralPath $ReleaseResourceRoot) {
            Remove-Item -LiteralPath $ReleaseResourceRoot -Recurse -Force
        }
        $BundleRoot = Join-Path $DesktopRoot "src-tauri\target\release\bundle\nsis"
        if (Test-Path -LiteralPath $BundleRoot) {
            Get-ChildItem -LiteralPath $BundleRoot -File -Filter "*.exe" | Remove-Item -Force
        }
        $env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
        $env:CARGO_HTTP_PROXY = ""
        npm --prefix $DesktopRoot run tauri build
        if ($LASTEXITCODE -ne 0) { throw "Tauri bundle build failed with exit code $LASTEXITCODE." }
    } else {
        Write-Host "SkipBundle: staged sidecar and MATLAB source only; formal vendor resources are not required."
    }

    if (Test-Path -LiteralPath $BackupResourceRoot) {
        Remove-Item -LiteralPath $BackupResourceRoot -Recurse -Force
    }
} catch {
    if ($Swapped -and (Test-Path -LiteralPath $ResourceRoot)) {
        Remove-Item -LiteralPath $ResourceRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $BackupResourceRoot) {
        Move-Item -LiteralPath $BackupResourceRoot -Destination $ResourceRoot
    }
    if (Test-Path -LiteralPath $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
    throw
}
