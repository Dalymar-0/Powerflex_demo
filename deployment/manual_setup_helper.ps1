# PowerFlex Demo - Manual Setup Instructions
# Use this if automated upload requires too many passwords

Write-Host "========================================" -ForegroundColor Green
Write-Host "PowerFlex - Manual VM Setup Steps" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

$VMs = @(
    @{IP="172.30.128.50"; Name="pflex-mdm"},
    @{IP="172.30.128.51"; Name="pflex-sds1"},
    @{IP="172.30.128.52"; Name="pflex-sds2"},
    @{IP="172.30.128.53"; Name="pflex-sdc1"},
    @{IP="172.30.128.54"; Name="pflex-sdc2"}
)

Write-Host "`nStep 1: Upload scripts to each VM`n" -ForegroundColor Cyan

foreach ($VM in $VMs) {
    Write-Host "# $($VM.Name) ($($VM.IP))" -ForegroundColor Yellow
    Write-Host "scp deployment/enable_ssh.sh root@$($VM.IP):/tmp/"
    Write-Host "scp deployment/enable_redhat_repos.sh root@$($VM.IP):/tmp/"
    Write-Host ""
}

Write-Host "`nStep 2: SSH to each VM and run scripts`n" -ForegroundColor Cyan

$credPrompt = Read-Host "Do you have your RedHat username and password ready? (y/n)"
if ($credPrompt -eq 'y') {
    $rhUser = Read-Host "RedHat Username"
    $rhPass = Read-Host "RedHat Password" -AsSecureString
    $rhPassPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($rhPass))
    
    Write-Host "`nRun these commands on each VM:" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($VM in $VMs) {
        Write-Host "# $($VM.Name)" -ForegroundColor Yellow
        Write-Host "ssh root@$($VM.IP)"
        Write-Host "cd /tmp && chmod +x *.sh"
        Write-Host "./enable_ssh.sh"
        Write-Host "./enable_redhat_repos.sh `"$rhUser`" `"$rhPassPlain`""
        Write-Host "exit"
        Write-Host ""
    }
} else {
    Write-Host "`nRun these commands on each VM:" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($VM in $VMs) {
        Write-Host "# $($VM.Name)" -ForegroundColor Yellow
        Write-Host "ssh root@$($VM.IP)"
        Write-Host "cd /tmp && chmod +x *.sh && ./enable_ssh.sh && ./enable_redhat_repos.sh"
        Write-Host "exit"
        Write-Host ""
    }
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "One-liner for all VMs (copy/paste each):" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

foreach ($VM in $VMs) {
    Write-Host "`n# $($VM.Name)" -ForegroundColor Yellow
    Write-Host "ssh root@$($VM.IP) 'cd /tmp && ./enable_ssh.sh && echo Done with SSH setup'" -ForegroundColor White
}
