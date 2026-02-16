# VMware Workstation + Rocky Linux 9 - Quick Reference

**Your Setup:** 5 VMs, VMware Workstation, Rocky Linux 9, Windows Host

---

## 📋 VM Configuration Summary

| VM# | Hostname | IP | RAM | Disk | Ports | Role |
|-----|----------|-----------|-----|------|-------|------|
| **1** | powerflex-mdm | 192.168.100.10 | 4GB | 50GB | 8001, 5000 | MDM + MGMT |
| **2** | powerflex-sds1 | 192.168.100.11 | 3GB | 120GB | 9700, 9100, 9200 | Storage Node 1 |
| **3** | powerflex-sds2 | 192.168.100.12 | 3GB | 120GB | 9700, 9100, 9200 | Storage Node 2 |
| **4** | powerflex-sdc1 | 192.168.100.13 | 2GB | 30GB | 8005, 8003, 8004 | IO Client 1 |
| **5** | powerflex-sdc2 | 192.168.100.14 | 2GB | 30GB | 8006, 8013, 8014 | IO Client 2 |

**Total Resources:** 8 vCPUs, 14GB RAM, 350GB disk

---

## 🌐 Network Configuration

```
VMware NAT Network (VMnet8)
Subnet: 192.168.100.0/24
Gateway: 192.168.100.2 (VMware NAT)
DNS: 192.168.100.2, 8.8.8.8

Host Machine: Windows
VMs: Rocky Linux 9
SSH User: rocky
```

---

## ⚡ Quick Setup Steps (TL;DR)

### 1. Download ISO (5 min)
```powershell
# Download Rocky Linux 9 Minimal (~2GB)
# https://rockylinux.org/download
# Save to: C:\ISOs\Rocky-9.3-x86_64-minimal.iso
```

### 2. Configure VMware Network (2 min)
```
VMware → Edit → Virtual Network Editor
VMnet8 (NAT): 192.168.100.0/24
DHCP: Disabled
```

### 3. Create 5 VMs (30 min)
```powershell
# Use deployment/create_vmware_vms.ps1 script
# Or manually create in VMware GUI
```

### 4. Install Rocky Linux on Each (1 hour = 5 VMs × 12 min)
```
Boot from ISO → Install → Set static IP → Create user 'rocky' → Reboot
```

### 5. Post-Install Config (30 min)
```bash
# On each VM:
sudo dnf update -y
sudo dnf install -y python3.11 python3-pip git

# Open firewall ports (MDM example):
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --permanent --add-port=5000/tcp
sudo firewall-cmd --reload

# Disable SELinux (testing only):
sudo setenforce 0
sudo sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config
```

### 6. Setup SSH Keys (5 min)
```powershell
# From Windows host:
ssh-keygen -t rsa -b 4096
ssh-copy-id rocky@192.168.100.10
ssh-copy-id rocky@192.168.100.11
ssh-copy-id rocky@192.168.100.12
ssh-copy-id rocky@192.168.100.13
ssh-copy-id rocky@192.168.100.14

# Test:
ssh rocky@192.168.100.10 hostname
```

### 7. Prepare Config (2 min)
```powershell
# Generate secret:
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"

# Copy config:
Copy-Item deployment/cluster_config_vmware.yaml deployment/cluster_config.yaml

# Edit cluster_secret in cluster_config.yaml
```

### 8. Validate (1 min)
```powershell
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe deployment/pre_deployment_check.py deployment/cluster_config.yaml
```

### 9. Deploy PowerFlex (4-6 hours)
```
Follow: deployment/PHASE14_DEPLOYMENT_GUIDE.md
With RedHat-specific commands from: deployment/VMWARE_REDHAT_GUIDE.md
```

**Total Setup Time:** ~2.5 hours (before PowerFlex deployment)

---

## 🔧 Common Commands

### VMware Management
```powershell
# List running VMs
& "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe" list

# Start VM
& "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe" start "D:\VMs\PowerFlex\PowerFlex-MDM\PowerFlex-MDM.vmx"

# Stop VM
& "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe" stop "D:\VMs\PowerFlex\PowerFlex-MDM\PowerFlex-MDM.vmx" soft
```

### SSH Quick Access
```powershell
# SSH to MDM
ssh rocky@192.168.100.10

# SSH to SDS1
ssh rocky@192.168.100.11

# SSH and run command
ssh rocky@192.168.100.10 "systemctl status firewalld"

# Copy files to VM
scp -r C:\Users\uid1944\Powerflex_demo rocky@192.168.100.10:/tmp/
```

### RedHat Package Management
```bash
# Update system
sudo dnf update -y

# Install package
sudo dnf install -y python3-pip

# Search package
dnf search python3

# List installed
dnf list installed | grep python

# Remove package
sudo dnf remove package-name
```

### Firewall Management
```bash
# Check status
sudo firewall-cmd --state

# List all rules
sudo firewall-cmd --list-all

# Add port
sudo firewall-cmd --permanent --add-port=8001/tcp

# Remove port
sudo firewall-cmd --permanent --remove-port=8001/tcp

# Reload (apply changes)
sudo firewall-cmd --reload

# Disable firewall (testing only)
sudo systemctl stop firewalld
sudo systemctl disable firewalld
```

### System Monitoring
```bash
# CPU usage
top
htop  # if installed

# Memory
free -h

# Disk usage
df -h

# Network
ip addr
ss -tuln

# Process list
ps aux | grep python

# Service status
systemctl status powerflex-mdm
journalctl -u powerflex-mdm -f
```

---

## 🐛 Troubleshooting Cheat Sheet

### VMs Can't Ping Each Other
```bash
# Check firewall
sudo firewall-cmd --list-all

# Temporarily disable to test
sudo systemctl stop firewalld

# Check IP
ip addr show

# Check routing
ip route

# Restart network
sudo nmcli con down "System eth0"
sudo nmcli con up "System eth0"
```

### No Internet Access from VMs
```bash
# Check DNS
cat /etc/resolv.conf

# Test connectivity
ping 8.8.8.8  # Google DNS (should work)
ping google.com  # Needs DNS

# Fix DNS
sudo nmcli con mod "System eth0" ipv4.dns "8.8.8.8 192.168.100.2"
sudo nmcli con down "System eth0" && sudo nmcli con up "System eth0"

# Check VMware NAT service (on Windows host)
# Services → VMware NAT Service → Restart
```

### SSH Connection Refused
```bash
# Check SSH service on VM
sudo systemctl status sshd
sudo systemctl start sshd

# Check SSH port
ss -tuln | grep 22

# Check firewall
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload

# From Windows host, check connectivity
Test-NetConnection -ComputerName 192.168.100.10 -Port 22
```

### Python Import Errors
```bash
# Check Python version
python3 --version

# Check pip
pip3 --version

# Reinstall package
pip3 install --upgrade --force-reinstall package-name

# Check installed packages
pip3 list
```

### Service Won't Start
```bash
# Check logs
sudo journalctl -u powerflex-mdm -n 50

# Check service file
sudo systemctl cat powerflex-mdm

# Check permissions
ls -lh /opt/powerflex

# Fix ownership
sudo chown -R rocky:rocky /opt/powerflex

# Reload systemd
sudo systemctl daemon-reload

# Restart service
sudo systemctl restart powerflex-mdm
```

---

## 📊 Monitoring During Deployment

### Check All VMs Status (from Windows host)
```powershell
# PowerShell script
$vms = @(
    @{Name="MDM";  IP="192.168.100.10"; Port=8001},
    @{Name="SDS1"; IP="192.168.100.11"; Port=9700},
    @{Name="SDS2"; IP="192.168.100.12"; Port=9700},
    @{Name="SDC1"; IP="192.168.100.13"; Port=8005},
    @{Name="SDC2"; IP="192.168.100.14"; Port=8006}
)

foreach ($vm in $vms) {
    $ping = Test-Connection -ComputerName $vm.IP -Count 1 -Quiet
    $port = Test-NetConnection -ComputerName $vm.IP -Port $vm.Port -WarningAction SilentlyContinue
    Write-Host "$($vm.Name) ($($vm.IP)): Ping=$ping, Port $($vm.Port)=$($port.TcpTestSucceeded)"
}
```

### Check MDM Health (once running)
```powershell
# From Windows host
curl http://192.168.100.10:8001/health
curl http://192.168.100.10:8001/health/components
```

### Watch Logs Live
```bash
# On each VM
sudo journalctl -u powerflex-mdm -f  # MDM
sudo journalctl -u powerflex-sds -f  # SDS
sudo journalctl -u powerflex-sdc -f  # SDC
sudo journalctl -u powerflex-mgmt -f  # MGMT
```

---

## 📁 File Locations Reference

### On VMs
```
/opt/powerflex/              # Project root
/opt/powerflex/.venv/        # Python virtual environment
/opt/powerflex/mdm/          # MDM code
/opt/powerflex/sds/          # SDS code
/opt/powerflex/sdc/          # SDC code
/opt/powerflex/mgmt/         # MGMT code

/var/powerflex/sds1/         # SDS storage (VM2/VM3)
/var/log/powerflex/          # Application logs
/var/backups/powerflex/      # Backups

/etc/systemd/system/powerflex-*.service  # Systemd services

/opt/powerflex/mdm/data/powerflex.db     # MDM database
/opt/powerflex/sds/data/sds_local.db     # SDS database
/opt/powerflex/sdc/data/sdc_chunks.db    # SDC database
/opt/powerflex/mgmt/data/mgmt.db         # MGMT database
```

### On Windows Host
```
C:\Users\uid1944\Powerflex_demo\                # Code
C:\Users\uid1944\Powerflex_demo\deployment\     # Deployment configs
D:\VMs\PowerFlex\                                # VMware VM files
C:\ISOs\                                         # ISO files
```

---

## ✅ Pre-Deployment Checklist

Before starting Phase 14 deployment:

- [ ] Downloaded Rocky Linux 9 ISO
- [ ] VMware Workstation installed and licensed
- [ ] VMnet8 (NAT) network configured (192.168.100.0/24)
- [ ] 5 VMs created (MDM, SDS1, SDS2, SDC1, SDC2)
- [ ] Rocky Linux installed on all 5 VMs
- [ ] Static IPs configured (192.168.100.10-14)
- [ ] SSH service running on all VMs
- [ ] Firewall ports opened on all VMs
- [ ] SELinux set to permissive
- [ ] Python 3.11 installed on all VMs
- [ ] SSH keys copied from host to all VMs
- [ ] Passwordless SSH working to all VMs
- [ ] cluster_config.yaml edited with cluster_secret
- [ ] Pre-deployment check passed
- [ ] All VMs can ping each other
- [ ] All VMs can access internet
- [ ] Host can SSH to all VMs

**If all checked ✅, you're ready for Phase 14 deployment!**

---

## 🚀 Next Steps

1. **Read:** [VMWARE_REDHAT_GUIDE.md](VMWARE_REDHAT_GUIDE.md) - Full setup guide
2. **Deploy:** [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md) - Component deployment
3. **Test:** Run integration tests from deployment guide
4. **Celebrate:** You've built a distributed storage system!

**Estimated time remaining:** 4-6 hours (Phase 14 deployment)

---

## 💡 Tips & Best Practices

**Take snapshots before major steps:**
```
VMware → VM → Snapshot → Take Snapshot
Name: "After OS Install", "After MDM Deploy", etc.
```

**Use VM cloning to save time:**
```
Install Rocky on VM2 → Configure → Clone to VM3
Only change IP and hostname on VM3
```

**Keep a terminal open to each VM:**
```
Tab 1: SSH to MDM (192.168.100.10)
Tab 2: SSH to SDS1 (192.168.100.11)
Tab 3: SSH to SDS2 (192.168.100.12)
Tab 4: SSH to SDC1 (192.168.100.13)
Tab 5: SSH to SDC2 (192.168.100.14)
```

**Monitor resources during deployment:**
- VMware Workstation → VM → Power → Performance Monitor
- Watch CPU, RAM, disk, network usage

**Save your cluster_secret somewhere safe:**
```powershell
# Save to file
"YOUR_CLUSTER_SECRET_HERE" | Out-File deployment/cluster_secret.txt
```

Good luck! 🎯
