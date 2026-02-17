param(
    [string]$Password = "root",
    [string]$Branch = "main",
    [string]$PythonBin = "/opt/rh/rh-python38/root/usr/bin/python3",
    [switch]$SkipNetwork,
    [Alias("SkipRepoSync")]
    [switch]$SkipCodeSync,
    [switch]$SkipDeps,
    [switch]$TestOnly,
    [switch]$AllowUnpushed,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$Nodes = @(
    @{ Name = "mdm";  IP = "172.30.128.50"; Hostname = "pflex-mdm";  Services = @("powerflex-mdm", "powerflex-mgmt"); Units = @("powerflex-mdm.service", "powerflex-mgmt.service") },
    @{ Name = "sds1"; IP = "172.30.128.51"; Hostname = "pflex-sds1"; Services = @("powerflex-sds"); Units = @("powerflex-sds1.service") },
    @{ Name = "sds2"; IP = "172.30.128.52"; Hostname = "pflex-sds2"; Services = @("powerflex-sds"); Units = @("powerflex-sds2.service") },
    @{ Name = "sdc1"; IP = "172.30.128.53"; Hostname = "pflex-sdc1"; Services = @("powerflex-sdc"); Units = @("powerflex-sdc1.service") },
    @{ Name = "sdc2"; IP = "172.30.128.54"; Hostname = "pflex-sdc2"; Services = @("powerflex-sdc"); Units = @("powerflex-sdc2.service") }
)

$Dns = "172.30.128.10"
$RepoRoot = "/opt/Powerflex_demo"
$LocalRepoRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..")).Path
$DeployRunId = [DateTime]::UtcNow.ToString("yyyyMMddHHmmss")

function Write-Header([string]$Text) {
    Write-Host "`n$('=' * 72)" -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host $('=' * 72) -ForegroundColor Cyan
}

function Write-Step([string]$Text) { Write-Host "[>] $Text" -ForegroundColor Yellow }
function Write-Info([string]$Text) { Write-Host "[i] $Text" -ForegroundColor DarkCyan }
function Write-Ok([string]$Text) { Write-Host "[OK] $Text" -ForegroundColor Green }
function Write-Err([string]$Text) { Write-Host "[ERR] $Text" -ForegroundColor Red }

function Invoke-Remote {
    param(
        [string]$IP,
        [string]$Command,
        [switch]$IgnoreFailure
    )

    $output = plink -batch -ssh -pw $Password root@$IP "$Command" 2>&1
    $code = $LASTEXITCODE
    if (-not $IgnoreFailure -and $code -ne 0) {
        throw "Remote command failed on $IP (exit=$code): $output"
    }
    return $output
}

function Copy-Remote {
    param(
        [string]$LocalPath,
        [string]$IP,
        [string]$RemotePath
    )

    pscp -batch -pw $Password $LocalPath root@${IP}:$RemotePath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Copy failed: $LocalPath -> $IP`:$RemotePath"
    }
}

function Get-LocalCommitInfo {
    param([string]$RepoPath)

    $branchName = (git -C $RepoPath rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branchName) {
        throw "Unable to determine local git branch in $RepoPath"
    }

    $commit = (git -C $RepoPath rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commit) {
        throw "Unable to determine local git commit in $RepoPath"
    }

    return @{ Branch = $branchName; Commit = $commit }
}

function Test-HeadPushed {
    param(
        [string]$RepoPath,
        [string]$BranchName,
        [string]$Commit
    )

    git -C $RepoPath rev-parse --abbrev-ref "$BranchName@{upstream}" *> $null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    git -C $RepoPath fetch --quiet *> $null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    git -C $RepoPath merge-base --is-ancestor $Commit "$BranchName@{upstream}" *> $null
    return ($LASTEXITCODE -eq 0)
}

Write-Header "PowerFlex Automated Deploy (Bootstrap)"
Write-Info "Target subnet: 172.30.128.0/24"
Write-Info "Mode: root SSH + systemd services"
Write-Info "Local repo: $LocalRepoRoot"

Write-Step "Preflight: checking required local tools"
foreach ($cmd in @("plink", "pscp", "git")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}
Write-Ok "Local tool check passed"

Write-Step "Preflight: resolving local commit metadata"
$commitInfo = Get-LocalCommitInfo -RepoPath $LocalRepoRoot
$LocalBranch = $commitInfo.Branch
$LocalCommit = $commitInfo.Commit
Write-Info "Local branch: $LocalBranch"
Write-Info "Local commit: $LocalCommit"

if ($Branch -and $LocalBranch -ne $Branch) {
    throw "Current local branch is '$LocalBranch' but -Branch '$Branch' was requested. Switch branch or pass matching -Branch."
}

if (-not $AllowUnpushed) {
    Write-Step "Preflight: verifying local HEAD is pushed to upstream"
    $isPushed = Test-HeadPushed -RepoPath $LocalRepoRoot -BranchName $LocalBranch -Commit $LocalCommit
    if (-not $isPushed) {
        throw "Local HEAD ($LocalCommit) is not confirmed on upstream. Push first, or use -AllowUnpushed to deploy local-only code."
    }
    Write-Ok "HEAD is present on upstream"
}

Write-Step "Preflight: checking SSH reachability"
$reachable = @()
foreach ($node in $Nodes) {
    try {
        $r = Invoke-Remote -IP $node.IP -Command "echo ok"
        if ($r -match "ok") {
            $reachable += $node
            Write-Ok "$($node.Name) ($($node.IP)) reachable"
        } else {
            Write-Err "$($node.Name) ($($node.IP)) did not return expected response"
        }
    } catch {
        Write-Err "$($node.Name) ($($node.IP)) unreachable: $_"
    }
}

if ($reachable.Count -eq 0) {
    throw "No nodes reachable"
}
if ($reachable.Count -ne $Nodes.Count -and -not $Force) {
    throw "Not all nodes reachable. Re-run with -Force to continue with partial cluster."
}

if ($TestOnly) {
    Write-Ok "TestOnly complete"
    exit 0
}

if (-not $SkipNetwork) {
    Write-Header "Phase 1: Network Baseline"
    $hostsBlock = ($Nodes | ForEach-Object { "$($_.IP) $($_.Hostname)" }) -join "`n"
    $hostsEscaped = $hostsBlock -replace "'", "'\\''"

    foreach ($node in $reachable) {
        Write-Step "Configuring hostname/hosts/resolver on $($node.Name)"
        $cmd = "set -e; hostnamectl set-hostname $($node.Hostname); printf '$hostsEscaped`n' > /etc/hosts; printf 'nameserver $Dns`nnameserver 8.8.8.8`n' > /etc/resolv.conf"
        Invoke-Remote -IP $node.IP -Command $cmd | Out-Null
        Write-Ok "$($node.Name) baseline network config applied"
    }
}

if (-not $SkipCodeSync) {
    Write-Header "Phase 2: Code Sync (Local Commit Archive)"
    $archiveFile = Join-Path $env:TEMP ("powerflex_sync_{0}_{1}.tar.gz" -f $LocalCommit.Substring(0, 8), $DeployRunId)
    if (Test-Path $archiveFile) {
        Remove-Item -Path $archiveFile -Force
    }

    Write-Step "Creating source archive from commit $LocalCommit"
    git -C $LocalRepoRoot archive --format=tar.gz -o $archiveFile $LocalCommit
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $archiveFile)) {
        throw "Failed to create local archive for commit $LocalCommit"
    }
    Write-Ok "Archive created: $archiveFile"

    foreach ($node in $reachable) {
        Write-Step "Uploading archive to $($node.Name)"
        $remoteArchive = "/tmp/powerflex_sync_${DeployRunId}.tar.gz"
        Copy-Remote -LocalPath $archiveFile -IP $node.IP -RemotePath $remoteArchive

        Write-Step "Applying synced code on $($node.Name)"
        $cmdTemplate = @'
set -e; backup=/tmp/powerflex_data___RUNID___; rm -rf "$backup"; mkdir -p "$backup"; if [ -d '___REPOROOT___/mdm/data' ]; then mkdir -p "$backup/mdm"; mv '___REPOROOT___/mdm/data' "$backup/mdm/data"; fi; if [ -d '___REPOROOT___/mgmt/data' ]; then mkdir -p "$backup/mgmt"; mv '___REPOROOT___/mgmt/data' "$backup/mgmt/data"; fi; rm -rf '___REPOROOT___'; mkdir -p '___REPOROOT___'; tar -xzf '___ARCHIVE___' -C '___REPOROOT___'; if [ -d "$backup/mdm/data" ]; then mkdir -p '___REPOROOT___/mdm'; mv "$backup/mdm/data" '___REPOROOT___/mdm/data'; fi; if [ -d "$backup/mgmt/data" ]; then mkdir -p '___REPOROOT___/mgmt'; mv "$backup/mgmt/data" '___REPOROOT___/mgmt/data'; fi; rm -rf "$backup" '___ARCHIVE___'; printf '%s\n' '___COMMIT___' > '___REPOROOT___/.deployed_commit'
'@
        $cmd = $cmdTemplate.Replace("___RUNID___", $DeployRunId).Replace("___REPOROOT___", $RepoRoot).Replace("___ARCHIVE___", $remoteArchive).Replace("___COMMIT___", $LocalCommit)
        Invoke-Remote -IP $node.IP -Command $cmd | Out-Null
        Write-Ok "$($node.Name) synced to commit $LocalCommit"
    }

    Remove-Item -Path $archiveFile -Force
    Write-Ok "Code sync complete on reachable nodes"
}

if (-not $SkipDeps) {
    Write-Header "Phase 3: Dependency Install"
    foreach ($node in $reachable) {
        Write-Step "Installing Python dependencies on $($node.Name)"
        $depsCmdTemplate = @'
set -e; cd '___REPOROOT___'; if [ ! -x '___PYBIN___' ]; then echo 'Missing Python interpreter: ___PYBIN___' >&2; exit 1; fi; '___PYBIN___' -m pip install -q --upgrade pip || echo 'WARN: pip upgrade skipped'; '___PYBIN___' -m pip install -q -r requirements.txt || echo 'WARN: requirements install skipped'; '___PYBIN___' -m pip install -q 'urllib3<2' || echo 'WARN: urllib3 pin skipped'; '___PYBIN___' -c "import fastapi, uvicorn, sqlalchemy, pydantic, requests, flask"
'@
        $cmd = $depsCmdTemplate.Replace("___REPOROOT___", $RepoRoot).Replace("___PYBIN___", $PythonBin)
        Invoke-Remote -IP $node.IP -Command $cmd | Out-Null
        Write-Ok "$($node.Name) dependencies installed"
    }

    Write-Step "Installing MGMT extras on mdm node"
    Invoke-Remote -IP "172.30.128.50" -Command "$PythonBin -m pip install -q bcrypt" | Out-Null
    Write-Ok "MGMT extras installed"
}

Write-Header "Phase 4: Unit Deployment"
$localDeployDir = Split-Path -Parent $MyInvocation.MyCommand.Path

foreach ($node in $reachable) {
    Write-Step "Deploying units on $($node.Name)"
    foreach ($unit in $node.Units) {
        $localUnit = Join-Path $localDeployDir $unit
        if (-not (Test-Path $localUnit)) {
            throw "Missing local unit file: $localUnit"
        }

        $remoteTargetName = switch ($unit) {
            "powerflex-sds1.service" { "powerflex-sds.service" }
            "powerflex-sds2.service" { "powerflex-sds.service" }
            "powerflex-sdc1.service" { "powerflex-sdc.service" }
            "powerflex-sdc2.service" { "powerflex-sdc.service" }
            default { $unit }
        }

        Copy-Remote -LocalPath $localUnit -IP $node.IP -RemotePath "/etc/systemd/system/$remoteTargetName"
    }

    Invoke-Remote -IP $node.IP -Command "systemctl daemon-reload" | Out-Null
    foreach ($svc in $node.Services) {
        Invoke-Remote -IP $node.IP -Command "systemctl enable $svc" | Out-Null
    }
    Write-Ok "$($node.Name) units enabled"
}

Write-Header "Phase 5: Database Init"
Write-Step "Initializing MDM database"
$dbInit = "set -e; cd '$RepoRoot'; mkdir -p '$RepoRoot/mdm/data' '$RepoRoot/mgmt/data'; '$PythonBin' -c 'from mdm.database import init_db; init_db()'"
Invoke-Remote -IP "172.30.128.50" -Command $dbInit | Out-Null
Write-Ok "MDM database initialized"

Write-Header "Phase 6: Service Restart"
Invoke-Remote -IP "172.30.128.50" -Command "systemctl restart powerflex-mdm; sleep 3; systemctl restart powerflex-mgmt" | Out-Null
Invoke-Remote -IP "172.30.128.51" -Command "systemctl restart powerflex-sds" | Out-Null
Invoke-Remote -IP "172.30.128.52" -Command "systemctl restart powerflex-sds" | Out-Null
Invoke-Remote -IP "172.30.128.53" -Command "systemctl restart powerflex-sdc" | Out-Null
Invoke-Remote -IP "172.30.128.54" -Command "systemctl restart powerflex-sdc" | Out-Null

Start-Sleep -Seconds 6

Write-Header "Phase 7: Validation"
foreach ($node in $reachable) {
    foreach ($svc in $node.Services) {
        $status = (Invoke-Remote -IP $node.IP -Command "systemctl is-active $svc" -IgnoreFailure).Trim()
        if ($status -eq "active") {
            Write-Ok "$($node.Name): $svc is active"
        } else {
            Write-Err "$($node.Name): $svc is $status"
        }
    }
}

$mdmHttp = (Invoke-Remote -IP "172.30.128.50" -Command "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health/" -IgnoreFailure).Trim()
$mgmtHttp = (Invoke-Remote -IP "172.30.128.50" -Command "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/" -IgnoreFailure).Trim()

Write-Info "MDM /health HTTP: $mdmHttp"
Write-Info "MGMT / HTTP: $mgmtHttp"

Write-Header "Deployment Complete"
Write-Host "MDM API : http://172.30.128.50:8001" -ForegroundColor Green
Write-Host "MGMT GUI: http://172.30.128.50:5000" -ForegroundColor Green
Write-Host "Deployed commit: $LocalCommit" -ForegroundColor Green
