param(
    [string]$Password = "root",
    [string]$RepoUrl = "https://github.com/Dalymar-0/Powerflex_demo.git",
    [string]$Branch = "main",
    [string]$PythonBin = "/opt/rh/rh-python38/root/usr/bin/python3",
    [switch]$SkipNetwork,
    [switch]$SkipRepoSync,
    [switch]$SkipDeps,
    [switch]$TestOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Nodes = @(
    @{ Name = "mdm";  IP = "172.30.128.50"; Hostname = "pflex-mdm";  Services = @("powerflex-mdm", "powerflex-mgmt"); Units = @("powerflex-mdm.service", "powerflex-mgmt.service") },
    @{ Name = "sds1"; IP = "172.30.128.51"; Hostname = "pflex-sds1"; Services = @("powerflex-sds"); Units = @("powerflex-sds1.service") },
    @{ Name = "sds2"; IP = "172.30.128.52"; Hostname = "pflex-sds2"; Services = @("powerflex-sds"); Units = @("powerflex-sds2.service") },
    @{ Name = "sdc1"; IP = "172.30.128.53"; Hostname = "pflex-sdc1"; Services = @("powerflex-sdc"); Units = @("powerflex-sdc1.service") },
    @{ Name = "sdc2"; IP = "172.30.128.54"; Hostname = "pflex-sdc2"; Services = @("powerflex-sdc"); Units = @("powerflex-sdc2.service") }
)

$Dns = "172.30.128.10"
$RepoRoot = "/opt/Powerflex_demo"

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

Write-Header "PowerFlex Deployment (Canonical)"
Write-Info "Target subnet: 172.30.128.0/24"
Write-Info "Mode: root SSH + systemd services"

Write-Step "Preflight: checking required local tools"
foreach ($cmd in @("plink", "pscp")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $cmd"
    }
}
Write-Ok "Local tool check passed"

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

if (-not $SkipRepoSync) {
    Write-Header "Phase 2: Repository Sync"
    foreach ($node in $reachable) {
        Write-Step "Syncing repository on $($node.Name)"
                $cmd = "set -e; if [ ! -d '$RepoRoot/.git' ]; then if [ -d '$RepoRoot' ]; then echo 'WARN: repo has no .git, using existing local files'; else git clone --branch '$Branch' '$RepoUrl' '$RepoRoot'; fi; else cd '$RepoRoot'; (git fetch --all --prune && git checkout '$Branch' && git reset --hard 'origin/$Branch') || echo 'WARN: git sync failed, using existing local repo'; fi"
        Invoke-Remote -IP $node.IP -Command $cmd | Out-Null
        Write-Ok "$($node.Name) repository ready"
    }
}

if (-not $SkipDeps) {
    Write-Header "Phase 3: Dependency Install"
    foreach ($node in $reachable) {
        Write-Step "Installing Python dependencies on $($node.Name)"
    $cmd = "set -e; cd '$RepoRoot'; if [ ! -x '$PythonBin' ]; then echo 'Missing Python interpreter: $PythonBin' >&2; exit 1; fi; '$PythonBin' -m pip install -q --upgrade pip || echo 'WARN: pip upgrade skipped'; '$PythonBin' -m pip install -q -r requirements.txt || echo 'WARN: requirements install skipped'; '$PythonBin' -m pip install -q 'urllib3<2' || echo 'WARN: urllib3 pin skipped'; '$PythonBin' - <<'PY'\nimport fastapi, uvicorn, sqlalchemy, pydantic, requests, flask\nprint('deps-ok')\nPY"
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
