# PowerFlex Demo - Fully Automated VM Setup
# Run this to setup all 5 VMs automatically

param(
    [string]$RedHatUsername,
    [string]$RedHatPassword
)

$VMs = @(
    @{IP="172.30.128.50"; Name="pflex-mdm"},
    @{IP="172.30.128.51"; Name="pflex-sds1"},
    @{IP="172.30.128.52"; Name="pflex-sds2"},
    @{IP="172.30.128.53"; Name="pflex-sdc1"},
    @{IP="172.30.128.54"; Name="pflex-sdc2"}
)

Write-Host "========================================" -ForegroundColor Green
Write-Host "PowerFlex - Automated VM Setup" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

if (-not $RedHatUsername) {
    $RedHatUsername = Read-Host "`nRedHat Username"
}
if (-not $RedHatPassword) {
    $RedHatPasswordSecure = Read-Host "RedHat Password" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($RedHatPasswordSecure)
    $RedHatPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

Write-Host "[OK] Starting deployment...`n" -ForegroundColor Green

# Check for PuTTY tools (supports password authentication)
$pscpPath = Get-Command pscp -ErrorAction SilentlyContinue
$plinkPath = Get-Command plink -ErrorAction SilentlyContinue

if (-not $pscpPath) {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "ERROR: Automated SSH requires PuTTY" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "`nDownload PuTTY from: https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html" -ForegroundColor Yellow
    Write-Host "Or install via: winget install PuTTY.PuTTY" -ForegroundColor Yellow
    Write-Host "`nAlternatively, use manual method:" -ForegroundColor Cyan
    Write-Host "  deployment\manual_setup_helper.ps1" -ForegroundColor White
    exit 1
}

$SSHPassword = "root"
Write-Host "[OK] Using PuTTY tools for automation`n" -ForegroundColor Green

$setupScript = @"
#!/bin/bash
RH_USER='$RedHatUsername'
RH_PASS='$RedHatPassword'
echo "[1/5] SSH setup..."
yum install -y openssh-server >/dev/null 2>&1
systemctl enable sshd >/dev/null 2>&1
systemctl start sshd >/dev/null 2>&1
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl restart sshd >/dev/null 2>&1
echo "[2/5] RedHat registration..."
subscription-manager unregister >/dev/null 2>&1 || true
subscription-manager register --username="`$RH_USER" --password="`$RH_PASS" --auto-attach >/dev/null 2>&1
echo "[3/5] Enable repos..."
subscription-manager repos --enable=rhel-7-server-rpms >/dev/null 2>&1
subscription-manager repos --enable=rhel-7-server-optional-rpms >/dev/null 2>&1
subscription-manager repos --enable=rhel-7-server-extras-rpms >/dev/null 2>&1
echo "[4/5] Install EPEL..."
yum install -y epel-release >/dev/null 2>&1
echo "[5/5] Update cache..."
yum clean all >/dev/null 2>&1
yum makecache fast >/dev/null 2>&1
echo "=== Setup Complete ==="
"@

$scriptPath = "$PSScriptRoot\automated_setup.sh"
Set-Content -Path $scriptPath -Value $setupScript -Encoding UTF8
Write-Host "[OK] Script created`n" -ForegroundColor Green

foreach ($VM in $VMs) {
    Write-Host ">>> $($VM.Name) ($($VM.IP))" -ForegroundColor Yellow
    
    $ping = Test-Connection -ComputerName $VM.IP -Count 1 -Quiet -ErrorAction SilentlyContinue
    if (-not $ping) {
        Write-Host "  [SKIP] Cannot reach VM`n" -ForegroundColor Red
        continue
    }
    
    try {
        # Accept host key first time
        Write-Host "  Accepting host key..." -NoNewline
        echo y | plink -pw $SSHPassword "root@$($VM.IP)" "exit" 2>&1 | Out-Null
        Write-Host " OK" -ForegroundColor Green
        
        Write-Host "  Uploading..." -NoNewline
        $result = pscp -batch -pw $SSHPassword $scriptPath "root@$($VM.IP):/tmp/automated_setup.sh" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host " FAILED" -ForegroundColor Red
            Write-Host "  Error: $result`n" -ForegroundColor Red
            continue
        }
        Write-Host " OK" -ForegroundColor Green
        
        Write-Host "  Executing..." -ForegroundColor Cyan
        $output = plink -batch -pw $SSHPassword "root@$($VM.IP)" "chmod +x /tmp/automated_setup.sh; bash /tmp/automated_setup.sh" 2>&1
        $output | ForEach-Object { Write-Host "    $_" }
        Write-Host "  [DONE]`n" -ForegroundColor Green
    }
    catch {
        Write-Host "  [ERROR] $_`n" -ForegroundColor Red
    }
}

Write-Host "========================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Test: ssh root@172.30.128.50" -ForegroundColor Cyan
