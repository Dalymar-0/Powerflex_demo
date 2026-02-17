param(
    [string]$Password = "root",
    [string]$Branch = "main",
    [string]$PythonBin = "/opt/rh/rh-python38/root/usr/bin/python3",
    [switch]$WithDeps,
    [switch]$WithNetwork,
    [switch]$TestOnly,
    [switch]$AllowUnpushed,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$deployScript = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "automated_deploy.ps1"
if (-not (Test-Path $deployScript)) {
    throw "Missing deploy script: $deployScript"
}

$args = @{
    Password = $Password
    Branch = $Branch
    PythonBin = $PythonBin
    SkipCodeSync = $false
    SkipNetwork = $true
    SkipDeps = $true
    TestOnly = $TestOnly
    AllowUnpushed = $AllowUnpushed
    Force = $Force
}

if ($WithNetwork) {
    $args.SkipNetwork = $false
}
if ($WithDeps) {
    $args.SkipDeps = $false
}

Write-Host "\n========================================================================" -ForegroundColor Cyan
Write-Host "PowerFlex Automated Resync (Commit Sync + Redeploy)" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "[i] Default mode: Skip network baseline + skip dependency reinstall" -ForegroundColor DarkCyan
Write-Host "[i] Use -WithNetwork and/or -WithDeps when needed" -ForegroundColor DarkCyan

& $deployScript @args
