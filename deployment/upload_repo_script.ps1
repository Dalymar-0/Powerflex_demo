# PowerFlex Demo - Upload Setup Scripts to All VMs
# Run from Windows to distribute enable_ssh.sh and enable_redhat_repos.sh scripts

$VMs = @(
    @{IP="172.30.128.50"; Name="pflex-mdm"},
    @{IP="172.30.128.51"; Name="pflex-sds1"},
    @{IP="172.30.128.52"; Name="pflex-sds2"},
    @{IP="172.30.128.53"; Name="pflex-sdc1"},
    @{IP="172.30.128.54"; Name="pflex-sdc2"}
)

$Scripts = @(
    "$PSScriptRoot\enable_ssh.sh",
    "$PSScriptRoot\enable_redhat_repos.sh"
)

$SSHUser = "root"

Write-Host "========================================" -ForegroundColor Green
Write-Host "PowerFlex - Upload Setup Scripts to VMs" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

# Check if scripts exist
foreach ($Script in $Scripts) {
    if (-not (Test-Path $Script)) {
        Write-Host "✗ Script not found: $Script" -ForegroundColor Red
        exit 1
    }
}

# Check if scp is available (comes with Git for Windows or OpenSSH)
$scpPath = Get-Command scp -ErrorAction SilentlyContinue
if (-not $scpPath) {
    Write-Host "✗ scp command not found. Install Git for Windows or OpenSSH." -ForegroundColor Red
    Write-Host "  Download: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}

Write-Host "`nUploading setup scripts to all VMs..." -ForegroundColor Cyan
Write-Host "Scripts: enable_ssh.sh, enable_redhat_repos.sh`n" -ForegroundColor White

foreach ($VM in $VMs) {
    Write-Host "`n[$($VM.Name) - $($VM.IP)]" -ForegroundColor Yellow
    
    # Test connectivity
    $ping = Test-Connection -ComputerName $VM.IP -Count 1 -Quiet -ErrorAction SilentlyContinue
    if (-not $ping) {
        Write-Host "  ✗ Cannot reach $($VM.IP)" -ForegroundColor Red
        continue
    }
    
    # Upload each script
    $allSuccess = $true
    foreach ($Script in $Scripts) {
        $scriptName = Split-Path $Script -Leaf
        Write-Host "  Uploading $scriptName..." -NoNewline
        $result = scp -o StrictHostKeyChecking=no $Script "${SSHUser}@$($VM.IP):/tmp/" 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host " ✓" -ForegroundColor Green
        } else {
            Write-Host " ✗" -ForegroundColor Red
            $allSuccess = $false
        }
    }
    
    if ($allSuccess) {
        # Make all scripts executable
        Write-Host "  Making scripts executable..." -NoNewline
        ssh -o StrictHostKeyChecking=no "${SSHUser}@$($VM.IP)" "chmod +x /tmp/*.sh" 2>&1 | Out-Null
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host " ✓" -ForegroundColor Green
            Write-Host "  ${GREEN}Ready!${NC} Scripts in /tmp/" -ForegroundColor Cyan
        } else {
            Write-Host " ✗" -ForegroundColor Red
        }
    }
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "Upload Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nNext Steps:" -ForegroundColor Cyan
Write-Host "`n1. SSH to each VM:" -ForegroundColor White
Write-Host "   ssh root@<VM_IP>" -ForegroundColor Yellow
Write-Host "`n2. First, enable SSH (if not already accessible):" -ForegroundColor White
Write-Host "   cd /tmp" -ForegroundColor Yellow
Write-Host "   ./enable_ssh.sh" -ForegroundColor Yellow
Write-Host "`n3. Then, enable RedHat repositories:" -ForegroundColor White
Write-Host "   ./enable_redhat_repos.sh" -ForegroundColor Yellow
Write-Host "   # Or with credentials:" -ForegroundColor Gray
Write-Host "   ./enable_redhat_repos.sh ""username"" ""password""" -ForegroundColor Yellow
