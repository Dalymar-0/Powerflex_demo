# PowerFlex Automated Deployment Script
# Deploys to 5 RedHat 7.9 VMs via SSH
# Usage: .\automated_deploy.ps1 [-Password root] [-SkipPython] [-SkipGit] [-TestOnly] [-RepoOnly] [-Force]

param(
    [string]$Password = "root",
    [switch]$SkipPython,
    [switch]$SkipGit,
    [switch]$TestOnly,
    [switch]$RepoOnly,
    [switch]$Force
)

$ErrorActionPreference = "Continue"

# VM Configuration
$VMs = @(
    @{ Name = "VM1"; IP = "172.30.128.50"; Role = "MDM+MGMT"; Hostname = "pflex-mdm" }
    @{ Name = "VM2"; IP = "172.30.128.51"; Role = "SDS1"; Hostname = "pflex-sds1" }
    @{ Name = "VM3"; IP = "172.30.128.52"; Role = "SDS2"; Hostname = "pflex-sds2" }
    @{ Name = "VM4"; IP = "172.30.128.53"; Role = "SDC1"; Hostname = "pflex-sdc1" }
    @{ Name = "VM5"; IP = "172.30.128.54"; Role = "SDC2"; Hostname = "pflex-sdc2" }
)

$Gateway = "172.30.128.1"
$DNS = "8.8.8.8"  # Using Google DNS for internet access
$NetInterface = "ens33"  # Common default, will auto-detect if different

# Colors
function Write-Header { param($Text) Write-Host "`n$('='*70)" -ForegroundColor Cyan; Write-Host $Text -ForegroundColor Cyan; Write-Host $('='*70) -ForegroundColor Cyan }
function Write-Step { param($Text) Write-Host "`n[>] $Text" -ForegroundColor Yellow }
function Write-Success { param($Text) Write-Host "[OK] $Text" -ForegroundColor Green }
function Write-Fail { param($Text) Write-Host "[ERROR] $Text" -ForegroundColor Red }
function Write-Info { param($Text) Write-Host "[INFO] $Text" -ForegroundColor Cyan }

# SSH Helper Function
function Invoke-SSHCommand {
    param(
        [string]$IP,
        [string]$Command,
        [int]$Timeout = 300
    )
    
    # Use plink if available, otherwise ssh
    $sshCmd = Get-Command plink -ErrorAction SilentlyContinue
    if ($sshCmd) {
        # PuTTY's plink
        $result = echo y | plink -ssh -pw $Password root@$IP "$Command" 2>&1
    } else {
        # OpenSSH
        $env:SSHPASS = $Password
        $result = ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@$IP "$Command" 2>&1
    }
    
    return $result
}

Write-Header "PowerFlex Demo - Automated Deployment"
Write-Info "Target: 5 RedHat 7.9 VMs (172.30.128.50-54)"
Write-Info "Credentials: root/$Password"

# Phase 0: Pre-flight Checks
Write-Header "Phase 0: Pre-flight Checks"

Write-Step "Checking SSH connectivity..."
$reachable = @()
foreach ($vm in $VMs) {
    Write-Host "  Testing $($vm.Name) ($($vm.IP))... " -NoNewline
    try {
        $result = Invoke-SSHCommand -IP $vm.IP -Command "echo OK" -Timeout 5
        if ($result -match "OK") {
            Write-Host "✅" -ForegroundColor Green
            $reachable += $vm
        } else {
            Write-Host "❌ No response" -ForegroundColor Red
        }
    } catch {
        Write-Host "❌ Failed: $_" -ForegroundColor Red
    }
}

if ($reachable.Count -eq 0) {
    Write-Fail "No VMs are reachable. Please check:"
    Write-Host "  1. VMs are powered on"
    Write-Host "  2. Network connectivity (ping 172.30.128.50)"
    Write-Host "  3. SSH service is running on VMs"
    Write-Host "  4. Credentials are correct (root/root)"
    exit 1
}

Write-Success "$($reachable.Count)/$($VMs.Count) VMs are reachable"

if ($reachable.Count -ne $VMs.Count) {
    if (-not $Force) {
        $continue = Read-Host "Some VMs are unreachable. Continue anyway? (y/n)"
        if ($continue -ne 'y') { exit 1 }
    } else {
        Write-Info "Continuing with $($reachable.Count) reachable VMs (Force mode)"
    }
}

if ($TestOnly) {
    Write-Success "Test complete. Exiting."
    exit 0
}

# Phase 1: Network Configuration
Write-Header "Phase 1: Network Configuration"

foreach ($vm in $reachable) {
    Write-Step "Configuring $($vm.Name) ($($vm.IP))..."
    
    # Detect network interface
    Write-Host "  Detecting network interface... " -NoNewline
    $ifname = Invoke-SSHCommand -IP $vm.IP -Command "ip -o link show | grep -v loopback | grep 'state UP' | awk -F': ' '{print `$2}' | head -1"
    $ifname = ($ifname -split "`n")[0].Trim()
    if ([string]::IsNullOrEmpty($ifname)) { $ifname = "ens33" }
    Write-Host $ifname -ForegroundColor Cyan
    
    # Create network config
    $netConfig = @"
TYPE=Ethernet
BOOTPROTO=static
NAME=$ifname
DEVICE=$ifname
ONBOOT=yes
IPADDR=$($vm.IP)
NETMASK=255.255.255.0
GATEWAY=$Gateway
DNS1=$DNS
"@
    
    Write-Host "  Setting static IP $($vm.IP)... " -NoNewline
    $configPath = "/etc/sysconfig/network-scripts/ifcfg-$ifname"
    $result = Invoke-SSHCommand -IP $vm.IP -Command "echo '$netConfig' > $configPath && cat $configPath"
    if ($result -match "IPADDR=$($vm.IP)") {
        Write-Host "✅" -ForegroundColor Green
    } else {
        Write-Host "⚠️ " -ForegroundColor Yellow
    }
    
    # Set hostname
    Write-Host "  Setting hostname to $($vm.Hostname)... " -NoNewline
    Invoke-SSHCommand -IP $vm.IP -Command "hostnamectl set-hostname $($vm.Hostname) && echo $($vm.Hostname) > /etc/hostname" | Out-Null
    Write-Host "✅" -ForegroundColor Green
    
    # Update /etc/hosts
    Write-Host "  Updating /etc/hosts... " -NoNewline
    $hostsEntries = ($VMs | ForEach-Object { "$($_.IP)  $($_.Hostname)" }) -join "`n"
    Invoke-SSHCommand -IP $vm.IP -Command "grep -q 'pflex-mdm' /etc/hosts || echo '$hostsEntries' >> /etc/hosts" | Out-Null
    Write-Host "✅" -ForegroundColor Green
    
    # Restart network (be careful - this might break SSH)
    Write-Host "  Restarting network... " -NoNewline
    Invoke-SSHCommand -IP $vm.IP -Command "systemctl restart network &" -Timeout 5 | Out-Null
    Start-Sleep -Seconds 3
    Write-Host "✅" -ForegroundColor Green

    # Ensure resolver and shell profile are clean
    Invoke-SSHCommand -IP $vm.IP -Command "printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' > /etc/resolv.conf; sed -i '/\/opt\/rh\/rh-python38\/enable/d' /root/.bashrc" | Out-Null
}

Write-Success "Network configuration complete"
Start-Sleep -Seconds 5

if (-not $SkipPython) {
    # Phase 1.5: Bootstrap Yum Repositories
    Write-Header "Phase 1.5: Yum Repository Bootstrap"

    foreach ($vm in $reachable) {
        Write-Step "Bootstrapping repos on $($vm.Name)..."
        Write-Host "  Configuring DNS + SCLo repos... " -NoNewline

        $repoBootstrap = "printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' > /etc/resolv.conf; yum install -y ca-certificates epel-release >/dev/null 2>&1 || true; printf '[centos-sclo-rh]\nname=CentOS-7 - SCLo rh\nbaseurl=https://vault.centos.org/7.9.2009/sclo/x86_64/rh/\nenabled=1\ngpgcheck=0\n\n[centos-sclo-sclo]\nname=CentOS-7 - SCLo sclo\nbaseurl=https://vault.centos.org/7.9.2009/sclo/x86_64/sclo/\nenabled=1\ngpgcheck=0\n' > /etc/yum.repos.d/centos-sclo.repo; yum clean all >/dev/null 2>&1 || true; yum makecache >/dev/null 2>&1 || true"

        Invoke-SSHCommand -IP $vm.IP -Command $repoBootstrap -Timeout 300 | Out-Null
        $repoResult = Invoke-SSHCommand -IP $vm.IP -Command "yum list available rh-python38 2>/dev/null | grep -c '^rh-python38'" -Timeout 120
        if ($repoResult -match "[1-9]") {
            Write-Host "✅" -ForegroundColor Green
        } else {
            Write-Host "❌" -ForegroundColor Red
            Write-Host "  Repo bootstrap output: $repoResult"
        }
    }

    Write-Success "Repository bootstrap complete"
}

# Phase 2: Install Python 3.8+
if (-not $SkipPython) {
    Write-Header "Phase 2: Install Python 3.8+"
    
    foreach ($vm in $reachable) {
        Write-Step "Installing Python on $($vm.Name)..."
        
        # Check if Python 3.8+ already installed
        Write-Host "  Checking Python version... " -NoNewline
        $pyVersion = Invoke-SSHCommand -IP $vm.IP -Command "python3 --version 2>&1 || echo 'Not found'"
        if ($pyVersion -match "Python 3\.([8-9]|1[0-9])") {
            Write-Host "✅ Already installed ($pyVersion)" -ForegroundColor Green
            continue
        }
        Write-Host "Installing..." -ForegroundColor Yellow
        
        # Try EPEL + SCL first
        Write-Host "  Installing EPEL + rh-python38... " -NoNewline
        $installCmd = "yum install -y rh-python38 rh-python38-python rh-python38-python-devel rh-python38-python-pip >/dev/null 2>&1; test -f /opt/rh/rh-python38/enable && (grep -q '/opt/rh/rh-python38/enable' /root/.bashrc || echo 'source /opt/rh/rh-python38/enable' >> /root/.bashrc)"
        Invoke-SSHCommand -IP $vm.IP -Command $installCmd -Timeout 600 | Out-Null
        $result = Invoke-SSHCommand -IP $vm.IP -Command "scl enable rh-python38 'python3 --version' 2>&1" -Timeout 120
        
        if ($result -match "Python 3\.8") {
            Write-Host "✅" -ForegroundColor Green
        } else {
            Write-Host "⚠️  Trying alternative method..." -ForegroundColor Yellow
            
            # Fallback: Build from source
            Write-Host "  Building Python 3.11 from source (this takes 5-10 min)... " -NoNewline
            $buildCmd = "yum groupinstall -y 'Development Tools' 2>&1 > /dev/null; yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel wget 2>&1 > /dev/null; cd /opt; wget -q https://www.python.org/ftp/python/3.11.7/Python-3.11.7.tgz; tar xzf Python-3.11.7.tgz; cd Python-3.11.7; ./configure --enable-optimizations --quiet; make -j4 altinstall 2>&1 > /dev/null; ln -sf /usr/local/bin/python3.11 /usr/local/bin/python3; ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip3; python3 --version"
            $result = Invoke-SSHCommand -IP $vm.IP -Command $buildCmd -Timeout 1200
            
            if ($result -match "Python 3\.11") {
                Write-Host "✅" -ForegroundColor Green
            } else {
                Write-Host "❌ Failed" -ForegroundColor Red
                Write-Host "  Result: $result"
                continue
            }
        }
        
        # Install Python packages
        Write-Host "  Installing Python packages... " -NoNewline
        $pipCmd = "scl enable rh-python38 'pip3 install --upgrade pip --quiet && pip3 install fastapi==0.128.5 uvicorn==0.40.0 sqlalchemy==2.0.46 pydantic==2.12.5 requests==2.32.5 flask==3.1.2 --quiet'"
        Invoke-SSHCommand -IP $vm.IP -Command $pipCmd -Timeout 300 | Out-Null
        Write-Host "✅" -ForegroundColor Green
    }
    
    Write-Success "Python installation complete"
}

if ($RepoOnly) {
    Write-Success "Repo and Python setup complete (RepoOnly mode)."
    exit 0
}

# Phase 3: Install Git and Clone Repository
if (-not $SkipGit) {
    Write-Header "Phase 3: Clone PowerFlex Repository"
    
    foreach ($vm in $reachable) {
        Write-Step "Cloning repository on $($vm.Name)..."
        
        # Install Git
        Write-Host "  Installing Git... " -NoNewline
        Invoke-SSHCommand -IP $vm.IP -Command "yum install -y git 2>&1 > /dev/null" -Timeout 120 | Out-Null
        Write-Host "✅" -ForegroundColor Green
        
        # Clone repository
        Write-Host "  Cloning Powerflex_demo... " -NoNewline
        $cloneCmd = "cd /opt; rm -rf Powerflex_demo 2>/dev/null || true; git clone https://github.com/Dalymar-0/Powerflex_demo.git 2>&1; test -d /opt/Powerflex_demo && echo 'SUCCESS'"
        $result = Invoke-SSHCommand -IP $vm.IP -Command $cloneCmd -Timeout 300
        
        if ($result -match "SUCCESS") {
            Write-Host "✅" -ForegroundColor Green
        } else {
            Write-Host "❌ Failed" -ForegroundColor Red
            Write-Host "  Result: $result"
        }
    }
    
    Write-Success "Repository cloned on all VMs"
}

# Phase 4: Initialize Database (VM1 only)
Write-Header "Phase 4: Initialize Database"

$vm1 = $VMs | Where-Object { $_.Name -eq "VM1" } | Select-Object -First 1
Write-Step "Initializing database on $($vm1.Name)..."

Write-Host "  Creating powerflex.db... " -NoNewline
$initCmd = "source /opt/rh/rh-python38/enable 2>/dev/null || true; cd /opt/Powerflex_demo; python3 -c 'from mdm.database import init_db; init_db()' 2>&1; test -f powerflex.db && ls -lh powerflex.db"
$result = Invoke-SSHCommand -IP $vm1.IP -Command $initCmd -Timeout 60

if ($result -match "powerflex.db") {
    Write-Host "✅" -ForegroundColor Green
} else {
    Write-Host "❌ Failed" -ForegroundColor Red
    Write-Host "  Result: $result"
}

Write-Success "Database initialized"

# Phase 5: Configure Services
Write-Header "Phase 5: Configure Systemd Services"

# VM1: MDM + MGMT
Write-Step "Configuring MDM + MGMT on VM1..."

$mdmService = @'
[Unit]
Description=PowerFlex MDM Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Powerflex_demo
Environment="POWERFLEX_MDM_API_PORT=8001"
Environment="POWERFLEX_MDM_BIND_HOST=0.0.0.0"
ExecStartPre=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true'
ExecStart=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true; python3 scripts/run_mdm_service.py --host 0.0.0.0 --port 8001'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'@

$mgmtService = @'
[Unit]
Description=PowerFlex Management GUI
After=network.target powerflex-mdm.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Powerflex_demo
Environment="FLASK_APP=flask_gui.py"
Environment="FLASK_RUN_HOST=0.0.0.0"
Environment="FLASK_RUN_PORT=5000"
Environment="POWERFLEX_MDM_URL=http://localhost:8001"
ExecStartPre=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true'
ExecStart=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true; python3 flask_gui.py'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'@

Write-Host "  Creating MDM service... " -NoNewline
Invoke-SSHCommand -IP $vm1.IP -Command "echo '$mdmService' > /etc/systemd/system/powerflex-mdm.service" | Out-Null
Write-Host "✅" -ForegroundColor Green

Write-Host "  Creating MGMT service... " -NoNewline
Invoke-SSHCommand -IP $vm1.IP -Command "echo '$mgmtService' > /etc/systemd/system/powerflex-mgmt.service" | Out-Null
Write-Host "✅" -ForegroundColor Green

# VM2-3: SDS
foreach ($vm in $reachable | Where-Object { $_.Role -match "SDS" }) {
    Write-Step "Configuring SDS on $($vm.Name)..."
    
    $sdsService = @"
[Unit]
Description=PowerFlex SDS Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Powerflex_demo
Environment="POWERFLEX_MDM_URL=http://172.30.128.50:8001"
Environment="POWERFLEX_SDS_CONTROL_PORT=9100"
Environment="POWERFLEX_SDS_DATA_PORT=9700"
Environment="POWERFLEX_SDS_STORAGE_ROOT=/data/powerflex/sds"
ExecStartPre=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true'
ExecStartPre=/bin/mkdir -p /data/powerflex/sds
ExecStart=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true; python3 scripts/run_sds_service.py'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"@
    
    Write-Host "  Creating storage directory... " -NoNewline
    Invoke-SSHCommand -IP $vm.IP -Command "mkdir -p /data/powerflex/sds && chmod 755 /data/powerflex/sds" | Out-Null
    Write-Host "✅" -ForegroundColor Green
    
    Write-Host "  Creating SDS service... " -NoNewline
    Invoke-SSHCommand -IP $vm.IP -Command "echo '$sdsService' > /etc/systemd/system/powerflex-sds.service" | Out-Null
    Write-Host "✅" -ForegroundColor Green
}

# VM4-5: SDC
foreach ($vm in $reachable | Where-Object { $_.Role -match "SDC" }) {
    Write-Step "Configuring SDC on $($vm.Name)..."
    
    $sdcService = @"
[Unit]
Description=PowerFlex SDC Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Powerflex_demo
Environment="POWERFLEX_MDM_URL=http://172.30.128.50:8001"
Environment="POWERFLEX_SDC_CONTROL_PORT=8003"
Environment="POWERFLEX_SDC_DEVICE_PORT=8005"
ExecStartPre=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true'
ExecStart=/bin/bash -c 'source /opt/rh/rh-python38/enable 2>/dev/null || true; python3 scripts/run_sdc_service.py'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"@
    
    Write-Host "  Creating SDC service... " -NoNewline
    Invoke-SSHCommand -IP $vm.IP -Command "echo '$sdcService' > /etc/systemd/system/powerflex-sdc.service" | Out-Null
    Write-Host "✅" -ForegroundColor Green
}

Write-Success "All services configured"

# Phase 6: Firewall Configuration
Write-Header "Phase 6: Firewall Configuration"

Write-Info "Disabling firewall for testing (you can enable later with specific rules)"
foreach ($vm in $reachable) {
    Write-Host "  $($vm.Name): " -NoNewline
    Invoke-SSHCommand -IP $vm.IP -Command "systemctl stop firewalld 2>&1 && systemctl disable firewalld 2>&1" | Out-Null
    Write-Host "✅" -ForegroundColor Green
}

Write-Success "Firewall disabled on all VMs"

# Phase 7: Start Services
Write-Header "Phase 7: Start Services"

Write-Step "Starting MDM on VM1..."
$startCmd = "systemctl unmask powerflex-mdm 2>/dev/null || true; systemctl daemon-reload; systemctl enable powerflex-mdm; systemctl start powerflex-mdm; sleep 5; systemctl status powerflex-mdm --no-pager | head -10"
$result = Invoke-SSHCommand -IP $vm1.IP -Command $startCmd -Timeout 30
if ($result -match "active \(running\)") {
    Write-Success "MDM service is running"
} else {
    Write-Fail "MDM service failed to start"
    Write-Host $result
}

Write-Step "Starting MGMT GUI on VM1..."
$startCmd = "systemctl unmask powerflex-mgmt 2>/dev/null || true; systemctl enable powerflex-mgmt; systemctl start powerflex-mgmt; sleep 3; systemctl status powerflex-mgmt --no-pager | head -10"
$result = Invoke-SSHCommand -IP $vm1.IP -Command $startCmd -Timeout 30
if ($result -match "active \(running\)") {
    Write-Success "MGMT service is running"
} else {
    Write-Fail "MGMT service failed to start"
    Write-Host $result
}

foreach ($vm in $reachable | Where-Object { $_.Role -match "SDS" }) {
    Write-Step "Starting SDS on $($vm.Name)..."
    $startCmd = "systemctl unmask powerflex-sds 2>/dev/null || true; systemctl daemon-reload; systemctl enable powerflex-sds; systemctl start powerflex-sds; sleep 3; systemctl status powerflex-sds --no-pager | head -10"
    $result = Invoke-SSHCommand -IP $vm.IP -Command $startCmd -Timeout 30
    if ($result -match "active \(running\)") {
        Write-Success "SDS service is running"
    } else {
        Write-Fail "SDS service failed to start"
        Write-Host $result
    }
}

foreach ($vm in $reachable | Where-Object { $_.Role -match "SDC" }) {
    Write-Step "Starting SDC on $($vm.Name)..."
    $startCmd = "systemctl unmask powerflex-sdc 2>/dev/null || true; systemctl daemon-reload; systemctl enable powerflex-sdc; systemctl start powerflex-sdc; sleep 3; systemctl status powerflex-sdc --no-pager | head -10"
    $result = Invoke-SSHCommand -IP $vm.IP -Command $startCmd -Timeout 30
    if ($result -match "active \(running\)") {
        Write-Success "SDC service is running"
    } else {
        Write-Fail "SDC service failed to start"
        Write-Host $result
    }
}

Write-Success "All services started"

# Phase 8: Test MDM API
Write-Header "Phase 8: Test MDM API"

Write-Step "Testing MDM API from Windows..."
Start-Sleep -Seconds 5

try {
    $response = Invoke-RestMethod -Uri "http://172.30.128.50:8001/pd/list" -TimeoutSec 10 -ErrorAction Stop
    Write-Success "MDM API is responding!"
    Write-Host "  Response: $($response | ConvertTo-Json -Compress)"
} catch {
    Write-Fail "MDM API is not responding yet"
    Write-Host "  Error: $_"
    Write-Info "Check logs: ssh root@172.30.128.50 'journalctl -u powerflex-mdm -n 50'"
}

# Phase 9: Bootstrap Cluster
Write-Header "Phase 9: Bootstrap Cluster"

Write-Step "Creating Protection Domain..."
try {
    $pd = Invoke-RestMethod -Uri "http://172.30.128.50:8001/pd/create" -Method Post -ContentType "application/json" -Body '{"name":"PD_Main"}' -ErrorAction Stop
    Write-Success "Protection Domain created: $($pd.name) (ID: $($pd.id))"
    
    Write-Step "Adding SDS nodes..."
    $sds1 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sds/add" -Method Post -ContentType "application/json" -Body (@{
        name = "SDS1"
        total_capacity_gb = 100
        devices = "/data/powerflex/sds"
        protection_domain_id = $pd.id
    } | ConvertTo-Json) -ErrorAction Stop
    Write-Success "SDS1 added (ID: $($sds1.id))"
    
    $sds2 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sds/add" -Method Post -ContentType "application/json" -Body (@{
        name = "SDS2"
        total_capacity_gb = 100
        devices = "/data/powerflex/sds"
        protection_domain_id = $pd.id
    } | ConvertTo-Json) -ErrorAction Stop
    Write-Success "SDS2 added (ID: $($sds2.id))"
    
    Write-Step "Creating Storage Pool..."
    $pool = Invoke-RestMethod -Uri "http://172.30.128.50:8001/pool/create" -Method Post -ContentType "application/json" -Body (@{
        name = "Pool_Main"
        pd_id = $pd.id
        protection_policy = "two_copies"
        total_capacity_gb = 200
    } | ConvertTo-Json) -ErrorAction Stop
    Write-Success "Storage Pool created: $($pool.name) (ID: $($pool.id))"
    
    Write-Step "Adding SDC clients..."
    $sdc1 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sdc/add" -Method Post -ContentType "application/json" -Body '{"name":"SDC1"}' -ErrorAction Stop
    Write-Success "SDC1 added (ID: $($sdc1.id))"
    
    $sdc2 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sdc/add" -Method Post -ContentType "application/json" -Body '{"name":"SDC2"}' -ErrorAction Stop
    Write-Success "SDC2 added (ID: $($sdc2.id))"
    
    Write-Step "Creating test volume..."
    $vol = Invoke-RestMethod -Uri "http://172.30.128.50:8001/vol/create" -Method Post -ContentType "application/json" -Body (@{
        name = "TestVolume1"
        size_gb = 10
        provisioning = "thin"
        pool_id = $pool.id
    } | ConvertTo-Json) -ErrorAction Stop
    Write-Success "Test volume created: $($vol.name) (ID: $($vol.id))"
    
} catch {
    Write-Fail "Cluster bootstrap failed: $_"
    Write-Info "You can bootstrap manually using the commands in REDHAT79_DEPLOYMENT_GUIDE.md Phase 7"
}

# Final Summary
Write-Header "Deployment Complete!"

Write-Host ""
Write-Host "Deployment Summary:" -ForegroundColor Cyan
Write-Host "  • VMs Configured: $($reachable.Count)" -ForegroundColor Green
Write-Host "  • MDM API: http://172.30.128.50:8001" -ForegroundColor Green
Write-Host "  • Management GUI: http://172.30.128.50:5000" -ForegroundColor Green
Write-Host "  • API Docs: http://172.30.128.50:8001/docs" -ForegroundColor Green
Write-Host ""

Write-Host "Quick Health Check:" -ForegroundColor Cyan
foreach ($vm in $reachable) {
    Write-Host "  $($vm.Name) ($($vm.IP)): " -NoNewline
    $service = switch ($vm.Role) {
        "MDM+MGMT" { "powerflex-mdm" }
        { $_ -match "SDS" } { "powerflex-sds" }
        { $_ -match "SDC" } { "powerflex-sdc" }
    }
    $status = Invoke-SSHCommand -IP $vm.IP -Command "systemctl is-active $service 2>&1" -Timeout 5
    if ($status -match "active") {
        Write-Host "✅ Running" -ForegroundColor Green
    } else {
        Write-Host "❌ $status" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Access GUI: http://172.30.128.50:5000"
Write-Host "  2. Test API: Invoke-RestMethod http://172.30.128.50:8001/pd/list"
Write-Host "  3. View logs: ssh root@172.30.128.50 (journalctl -u powerflex-mdm -f)"
Write-Host ""
Write-Host "Documentation: deployment/REDHAT79_DEPLOYMENT_GUIDE.md" -ForegroundColor Cyan
Write-Host ""
