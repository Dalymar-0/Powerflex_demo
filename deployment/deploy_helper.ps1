# PowerFlex Deployment Helper - RedHat 7.9
# Run from Windows to configure VMs

$VMs = @{
    "VM1_MDM"  = "172.30.128.50"
    "VM2_SDS1" = "172.30.128.51"
    "VM3_SDS2" = "172.30.128.52"
    "VM4_SDC1" = "172.30.128.53"
    "VM5_SDC2" = "172.30.128.54"
}

$Credential = @{
    Username = "root"
    Password = "root"
}

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "PowerFlex Demo - RedHat 7.9 Deployment Helper" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# Test 1: Check connectivity to all VMs
Write-Host "📡 Step 1: Testing VM Connectivity..." -ForegroundColor Yellow
$reachable = @()
$unreachable = @()

foreach ($vm in $VMs.GetEnumerator()) {
    Write-Host "  Testing $($vm.Key) ($($vm.Value))..." -NoNewline
    if (Test-Connection -ComputerName $vm.Value -Count 1 -Quiet -ErrorAction SilentlyContinue) {
        Write-Host " ✅" -ForegroundColor Green
        $reachable += $vm
    } else {
        Write-Host " ❌" -ForegroundColor Red
        $unreachable += $vm
    }
}

if ($unreachable.Count -gt 0) {
    Write-Host ""
    Write-Host "⚠️  Warning: $($unreachable.Count) VMs are unreachable:" -ForegroundColor Red
    $unreachable | ForEach-Object { Write-Host "   • $($_.Key) ($($_.Value))" -ForegroundColor Red }
    Write-Host ""
    $continue = Read-Host "Continue anyway? (y/n)"
    if ($continue -ne 'y') {
        exit 1
    }
}

Write-Host ""
Write-Host "✅ $($reachable.Count) VMs are reachable" -ForegroundColor Green
Write-Host ""

# Test 2: Check MDM API port
Write-Host "🔌 Step 2: Checking MDM API Availability..." -ForegroundColor Yellow
Write-Host "  Testing http://172.30.128.50:8001..." -NoNewline
Start-Sleep -Seconds 1

try {
    $response = Invoke-RestMethod -Uri "http://172.30.128.50:8001/pd/list" -TimeoutSec 5 -ErrorAction Stop
    Write-Host " ✅ API is UP!" -ForegroundColor Green
    Write-Host "  Response: $($response | ConvertTo-Json -Compress -Depth 1)"
} catch {
    Write-Host " ❌ Not responding" -ForegroundColor Red
    Write-Host ""
    Write-Host "⚠️  MDM API is not running yet. You need to:" -ForegroundColor Yellow
    Write-Host "   1. SSH to VM1 (172.30.128.50)" -ForegroundColor Yellow
    Write-Host "   2. Follow REDHAT79_DEPLOYMENT_GUIDE.md Phase 1-5" -ForegroundColor Yellow
    Write-Host "   3. Start MDM service: systemctl start powerflex-mdm" -ForegroundColor Yellow
    Write-Host ""
    $continue = Read-Host "Skip API test and continue? (y/n)"
    if ($continue -ne 'y') {
        exit 1
    }
}

Write-Host ""

# Test 3: Check MGMT GUI
Write-Host "🖥️  Step 3: Checking Management GUI..." -ForegroundColor Yellow
Write-Host "  Testing http://172.30.128.50:5000..." -NoNewline

try {
    $response = Invoke-WebRequest -Uri "http://172.30.128.50:5000" -TimeoutSec 5 -ErrorAction Stop
    Write-Host " ✅ GUI is UP!" -ForegroundColor Green
} catch {
    Write-Host " ❌ Not responding" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "📋 Next Steps:" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# Generate SSH commands for easy copy-paste
Write-Host "🔐 SSH Commands (copy/paste into PuTTY or terminal):" -ForegroundColor Green
Write-Host ""
Write-Host "VM1 (MDM+MGMT):" -ForegroundColor Yellow
Write-Host "  ssh root@172.30.128.50  # Password: root"
Write-Host ""
Write-Host "VM2 (SDS1):" -ForegroundColor Yellow
Write-Host "  ssh root@172.30.128.51  # Password: root"
Write-Host ""
Write-Host "VM3 (SDS2):" -ForegroundColor Yellow
Write-Host "  ssh root@172.30.128.52  # Password: root"
Write-Host ""
Write-Host "VM4 (SDC1):" -ForegroundColor Yellow
Write-Host "  ssh root@172.30.128.53  # Password: root"
Write-Host ""
Write-Host "VM5 (SDC2):" -ForegroundColor Yellow
Write-Host "  ssh root@172.30.128.54  # Password: root"
Write-Host ""

# Generate cluster bootstrap script
Write-Host "🚀 After deployment, run this to bootstrap cluster:" -ForegroundColor Green
Write-Host ""
Write-Host @"
# Create Protection Domain
`$pd = Invoke-RestMethod -Uri 'http://172.30.128.50:8001/pd/create' -Method Post -ContentType 'application/json' -Body '{  "name":"PD_Main"}'

# Add SDS Nodes
`$sds1 = Invoke-RestMethod -Uri 'http://172.30.128.50:8001/sds/add' -Method Post -ContentType 'application/json' -Body (@{
    name = 'SDS1'
    total_capacity_gb = 100
    devices = '/data/powerflex/sds'
    protection_domain_id = `$pd.id
} | ConvertTo-Json)

`$sds2 = Invoke-RestMethod -Uri 'http://172.30.128.50:8001/sds/add' -Method Post -ContentType 'application/json' -Body (@{
    name = 'SDS2'
    total_capacity_gb = 100
    devices = '/data/powerflex/sds'
    protection_domain_id = `$pd.id
} | ConvertTo-Json)

# Create Storage Pool
`$pool = Invoke-RestMethod -Uri 'http://172.30.128.50:8001/pool/create' -Method Post -ContentType 'application/json' -Body (@{
    name = 'Pool_Main'
    pd_id = `$pd.id
    protection_policy = 'two_copies'
    total_capacity_gb = 200
} | ConvertTo-Json)

# Add SDC Clients
`$sdc1 = Invoke-RestMethod -Uri 'http://172.30.128.50:8001/sdc/add' -Method Post -ContentType 'application/json' -Body '{"name":"SDC1"}'
`$sdc2 = Invoke-RestMethod -Uri 'http://172.30.128.50:8001/sdc/add' -Method Post -ContentType 'application/json' -Body '{"name":"SDC2"}'

Write-Host '✅ Cluster initialized!' -ForegroundColor Green
"@ -ForegroundColor Gray

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "📖 Full Guide: deployment/REDHAT79_DEPLOYMENT_GUIDE.md" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
