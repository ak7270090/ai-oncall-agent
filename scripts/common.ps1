$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Config = Import-PowerShellDataFile (Join-Path $PSScriptRoot "cluster.config.psd1")

# Docker Desktop ships an old kubectl on the machine PATH; prefer the winget-installed one.
$WingetLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
if (Test-Path $WingetLinks) { $env:Path = "$WingetLinks;$env:Path" }

function Resolve-RepoPath([string]$RelativePath) {
    Join-Path $RepoRoot $RelativePath
}

function Invoke-Native {
    param([Parameter(Mandatory)][string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

# Windows PowerShell turns redirected native stderr into terminating errors under
# ErrorActionPreference=Stop; probes that may write warnings to stderr run relaxed.
function Invoke-NativeQuietly {
    param([Parameter(Mandatory)][string]$Command, [string[]]$Arguments)
    $ErrorActionPreference = "Continue"
    $output = & $Command @Arguments 2>$null
    [pscustomobject]@{ Succeeded = ($LASTEXITCODE -eq 0); Output = $output }
}

function Assert-DockerRunning {
    if (-not (Invoke-NativeQuietly docker @("info")).Succeeded) {
        throw "Docker is not running. Start Docker Desktop first."
    }
}
