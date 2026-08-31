[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [string]$VenvPath = ".venv",
    [switch]$SkipPythonDependencies,
    [switch]$SkipPiRuntime,
    [switch]$ReinstallPiRuntime,
    [switch]$Json
)

<#
.SYNOPSIS
Prepare the repository-local dependencies required by topoptctl.

.DESCRIPTION
This bootstrapper is intentionally narrower than the desktop build script.  It
creates or reuses a virtual environment below the repository, installs the
pinned Python requirements, and provisions the root Pi runtime only when it is
absent.  It never writes credentials, starts a Sidecar, launches MATLAB, or
submits an Engineering/Research action.

An existing node_modules directory is never replaced by default.  An explicit
-ReinstallPiRuntime is required before npm ci is allowed to replace it.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PiCli = Join-Path $ProjectRoot "node_modules\@earendil-works\pi-coding-agent\dist\cli.js"

function Resolve-RepositoryChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$RequestedPath,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($RequestedPath)) {
        throw "$Label must not be empty."
    }

    $resolved = if ([System.IO.Path]::IsPathRooted($RequestedPath)) {
        [System.IO.Path]::GetFullPath($RequestedPath)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RequestedPath))
    }
    $rootPrefix = $ProjectRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    if ($resolved -eq $ProjectRoot -or -not $resolved.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must be a subdirectory of this repository: $ProjectRoot"
    }
    return $resolved
}

function Resolve-SystemPython {
    param([string]$Requested)

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        if (Test-Path -LiteralPath $Requested -PathType Leaf) {
            return [pscustomobject]@{ File = (Resolve-Path -LiteralPath $Requested).Path; Prefix = @() }
        }
        $command = Get-Command $Requested -ErrorAction SilentlyContinue
        if ($command) {
            return [pscustomobject]@{ File = $command.Source; Prefix = @() }
        }
        throw "Requested Python executable was not found: $Requested"
    }

    $py = Get-Command "py" -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{ File = $py.Source; Prefix = @("-3") }
    }
    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{ File = $python.Source; Prefix = @() }
    }
    throw "Python 3 was not found. Install Python 3 or pass -PythonExe explicitly."
}

function Resolve-Npm {
    foreach ($candidate in @("npm.cmd", "npm")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    throw "npm was not found. Install Node.js LTS before provisioning the Pi runtime."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Action
    )

    if ($Json) {
        & $File @Arguments *> $null
    } else {
        & $File @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Write-BootstrapResult {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Result)

    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    if ($Json) {
        [Console]::Out.WriteLine(($Result | ConvertTo-Json -Depth 6 -Compress))
        return
    }

    Write-Host "TopOptPilot headless bootstrap: $($Result.status)"
    Write-Host "Repository: $($Result.projectRoot)"
    Write-Host "Python: $($Result.python)"
    Write-Host "Python dependencies: $($Result.pythonDependencies)"
    Write-Host "Pi runtime: $($Result.piRuntime)"
    foreach ($step in $Result.nextSteps) {
        Write-Host "Next: $step"
    }
}

try {
    if ($SkipPiRuntime -and $ReinstallPiRuntime) {
        throw "-SkipPiRuntime and -ReinstallPiRuntime cannot be used together."
    }

    foreach ($required in @("requirements.txt", "package-lock.json", "topoptctl.py", "topoptctl.cmd")) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $required) -PathType Leaf)) {
            throw "Required headless input is missing: $required"
        }
    }

    $venvRoot = Resolve-RepositoryChildPath -RequestedPath $VenvPath -Label "VenvPath"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $venvCreated = $false
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        if (Test-Path -LiteralPath $venvRoot) {
            throw "The requested virtual environment exists but has no Scripts\python.exe: $venvRoot"
        }
        $systemPython = Resolve-SystemPython -Requested $PythonExe
        Invoke-Checked -File $systemPython.File -Arguments ($systemPython.Prefix + @("-m", "venv", $venvRoot)) -Action "Python virtual-environment creation"
        $venvCreated = $true
    }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment creation did not produce Scripts\python.exe: $venvRoot"
    }

    $pythonDependencyStatus = "skipped"
    if (-not $SkipPythonDependencies) {
        Invoke-Checked -File $venvPython -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $ProjectRoot "requirements.txt")) -Action "Python dependency installation"
        $pythonDependencyStatus = "installed-or-verified"
    }

    $piRuntimeStatus = "skipped"
    $nodeModules = Join-Path $ProjectRoot "node_modules"
    if (-not $SkipPiRuntime) {
        if ($ReinstallPiRuntime -or -not (Test-Path -LiteralPath $PiCli -PathType Leaf)) {
            if ((Test-Path -LiteralPath $nodeModules -PathType Container) -and -not $ReinstallPiRuntime) {
                throw "Pi runtime is incomplete. Refusing to replace existing node_modules automatically; inspect it or rerun with -ReinstallPiRuntime."
            }
            $npm = Resolve-Npm
            Invoke-Checked -File $npm -Arguments @("ci", "--ignore-scripts", "--no-audit", "--fund=false") -Action "Pi runtime installation"
            if (-not (Test-Path -LiteralPath $PiCli -PathType Leaf)) {
                throw "npm completed but the expected Pi CLI is missing: $PiCli"
            }
            $piRuntimeStatus = if ($ReinstallPiRuntime) { "reinstalled" } else { "installed" }
        } else {
            $piRuntimeStatus = "present"
        }
    }

    Write-BootstrapResult -Result ([ordered]@{
        ok = $true
        status = "ready"
        projectRoot = $ProjectRoot
        python = $venvPython
        virtualEnvironment = if ($venvCreated) { "created" } else { "present" }
        pythonDependencies = $pythonDependencyStatus
        piRuntime = $piRuntimeStatus
        guarantees = @(
            "no credentials were read or written",
            "no Sidecar, MATLAB solver, Engineering run, or Research action was started",
            "the Pi runtime is installed with npm ci --ignore-scripts only when absent or explicitly reinstalled"
        )
        nextSteps = @(
            ".\topoptctl.cmd --data-dir <state-dir> daemon start",
            ".\topoptctl.cmd --data-dir <state-dir> doctor"
        )
    })
} catch {
    $failure = [ordered]@{
        ok = $false
        status = "failed"
        error = $_.Exception.Message
    }
    if ($Json) {
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
        [Console]::Out.WriteLine(($failure | ConvertTo-Json -Depth 4 -Compress))
    } else {
        Write-Error "TopOptPilot headless bootstrap failed: $($failure.error)"
    }
    exit 2
}
