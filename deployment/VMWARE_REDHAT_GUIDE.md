# VMware Workstation + RedHat Deployment Guide

**Phase 14: Multi-VM Deployment with VMware Workstation & Rocky Linux**

---

## 🖥️ VM Specifications

### Host Requirements
- **RAM:** 16GB minimum (20GB recommended)
- **Disk:** 250GB free space
- **CPU:** 8 cores (or 4 cores with hyperthreading)
- **Software:** VMware Workstation 17 Pro (or 16 Pro)
- **OS:** Windows 10/11, Linux, or macOS

### VM Specs

| VM | Role | vCPUs | RAM | Disk | OS |
|----|------|-------|-----|------|-----|
| **VM1** | MDM+MGMT | 2 | 4GB | 50GB | Rocky Linux 9 |
| **VM2** | SDS1 | 2 | 3GB | 120GB | Rocky Linux 9 |
| **VM3** | SDS2 | 2 | 3GB | 120GB | Rocky Linux 9 |
| **VM4** | SDC1 | 1 | 2GB | 30GB | Rocky Linux 9 |
| **VM5** | SDC2 | 1 | 2GB | 30GB | Rocky Linux 9 |

**Total:** 8 vCPUs, 14GB RAM, 350GB disk

**Why Rocky Linux 9?**
- ✅ Free RHEL clone (100% binary compatible)
- ✅ Production-grade (used by enterprises)
- ✅ Better for resume/portfolio than Ubuntu
- ✅ No subscription needed (unlike RHEL)
- ✅ 10-year support lifecycle

**Alternatives:**
- **AlmaLinux 9** (another RHEL clone, CentOS replacement)
- **RHEL 9** (requires developer subscription, but free for testing)
- **CentOS Stream 9** (rolling release, less stable)

---

## 🌐 Network Design

### VMware Network Options

**Option 1: NAT Network (Recommended) ⭐**
```
Network: VMnet8 (NAT)
Subnet: 192.168.100.0/24
Gateway: 192.168.100.2 (VMware NAT gateway)
DNS: 192.168.100.2

VM1 (MDM):  192.168.100.10
VM2 (SDS1): 192.168.100.11
VM3 (SDS2): 192.168.100.12
VM4 (SDC1): 192.168.100.13
VM5 (SDC2): 192.168.100.14
```

**Pros:**
- VMs can access internet (for package installation)
- VMs can communicate with each other
- Host can access VMs

**Option 2: Host-Only Network**
```
Network: VMnet1 (Host-Only)
Subnet: 192.168.137.0/24
Gateway: 192.168.137.1

VM1 (MDM):  192.168.137.10
VM2 (SDS1): 192.168.137.11
VM3 (SDS2): 192.168.137.12
VM4 (SDC1): 192.168.137.13
VM5 (SDC2): 192.168.137.14
```

**Pros:**
- Isolated from external network
- More secure for testing

**Cons:**
- No internet access (harder to install packages)
- Need to setup NAT or use ISO packages

---

## 📋 Step-by-Step Setup

### Step 1: Download Rocky Linux ISO (5 minutes)

```powershell
# Download Rocky Linux 9 Minimal ISO (~2GB)
# URL: https://rockylinux.org/download
# Or direct link:
# https://download.rockylinux.org/pub/rocky/9/isos/x86_64/Rocky-9.3-x86_64-minimal.iso

# Save to:
$ISO_PATH = "C:\ISOs\Rocky-9.3-x86_64-minimal.iso"

# Verify download (optional)
Get-FileHash $ISO_PATH -Algorithm SHA256
```

---

### Step 2: Install VMware Workstation (if not installed)

**Download VMware Workstation 17 Pro:**
- https://www.vmware.com/products/workstation-pro.html
- 30-day trial (or use VMware Player free version)

**License:**
- VMware Workstation Pro: $$$
- VMware Workstation Player: Free (limited features, but sufficient)

---

### Step 3: Configure VMware Virtual Network

**3.1 Open Virtual Network Editor:**
```
VMware Workstation → Edit → Virtual Network Editor
(Click "Change Settings" if prompted for admin rights)
```

**3.2 Setup NAT Network (VMnet8):**
```
Network: VMnet8
Type: NAT
Subnet: 192.168.100.0
Subnet Mask: 255.255.255.0

NAT Settings:
  Gateway IP: 192.168.100.2
  
DHCP Settings:
  Disable DHCP (we'll use static IPs)
```

**3.3 (Optional) Create Custom Network:**
```
Network: VMnet2
Type: Host-Only
Subnet: 192.168.101.0
Subnet Mask: 255.255.255.0
```

---

### Step 4: Create VMs (PowerShell Automation)

**Save as:** `deployment/create_vmware_vms.ps1`

```powershell
# VMware Workstation VM Creation Script
# Requires: vmrun.exe from VMware Workstation installation

$VMWARE_PATH = "C:\Program Files (x86)\VMware\VMware Workstation"
$ISO_PATH = "C:\ISOs\Rocky-9.3-x86_64-minimal.iso"
$VM_DIR = "D:\VMs\PowerFlex"  # Adjust for your disk

# Create VM directory
New-Item -ItemType Directory -Path $VM_DIR -Force

# VM1 - MDM+MGMT
$vm1_dir = "$VM_DIR\PowerFlex-MDM"
New-Item -ItemType Directory -Path $vm1_dir -Force

# Create VMX file for VM1
@"
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "21"
vmci0.present = "TRUE"
hpet0.present = "TRUE"
displayName = "PowerFlex-MDM"
guestOS = "rhel9-64"
memsize = "4096"
numvcpus = "2"
cpuid.coresPerSocket = "2"

# Disk
scsi0.present = "TRUE"
scsi0.virtualDev = "lsilogic"
scsi0:0.present = "TRUE"
scsi0:0.fileName = "PowerFlex-MDM.vmdk"
scsi0:0.deviceType = "scsi-hardDisk"

# Network - NAT (VMnet8)
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000e"
ethernet0.addressType = "generated"

# CD-ROM for ISO
ide0:0.present = "TRUE"
ide0:0.deviceType = "cdrom-image"
ide0:0.fileName = "$ISO_PATH"

# USB Controller
usb.present = "TRUE"
ehci.present = "TRUE"
"@ | Out-File -FilePath "$vm1_dir\PowerFlex-MDM.vmx" -Encoding ASCII

# Create virtual disk for VM1
& "$VMWARE_PATH\vmware-vdiskmanager.exe" -c -s 50GB -a lsilogic -t 0 "$vm1_dir\PowerFlex-MDM.vmdk"

Write-Host "VM1 (MDM) created at: $vm1_dir"

# Repeat for VM2-VM5 (SDS1, SDS2, SDC1, SDC2)
# Adjust memsize, disk size, and names accordingly

# VM2 - SDS1
$vm2_dir = "$VM_DIR\PowerFlex-SDS1"
New-Item -ItemType Directory -Path $vm2_dir -Force
@"
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "21"
displayName = "PowerFlex-SDS1"
guestOS = "rhel9-64"
memsize = "3072"
numvcpus = "2"
scsi0.present = "TRUE"
scsi0.virtualDev = "lsilogic"
scsi0:0.present = "TRUE"
scsi0:0.fileName = "PowerFlex-SDS1.vmdk"
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000e"
ide0:0.present = "TRUE"
ide0:0.deviceType = "cdrom-image"
ide0:0.fileName = "$ISO_PATH"
"@ | Out-File -FilePath "$vm2_dir\PowerFlex-SDS1.vmx" -Encoding ASCII
& "$VMWARE_PATH\vmware-vdiskmanager.exe" -c -s 120GB -a lsilogic -t 0 "$vm2_dir\PowerFlex-SDS1.vmdk"

Write-Host "VM2 (SDS1) created at: $vm2_dir"

# Continue for VM3, VM4, VM5...
Write-Host ""
Write-Host "All VMs created! Open VMware Workstation and:"
Write-Host "  1. File → Open → Navigate to each .vmx file"
Write-Host "  2. Power on each VM"
Write-Host "  3. Install Rocky Linux with static IPs"
```

---

### Step 5: Install Rocky Linux on Each VM

**5.1 Boot VM1 (MDM):**
1. VMware Workstation → Open → `PowerFlex-MDM.vmx`
2. Power on VM
3. Select "Install Rocky Linux 9"

**5.2 Installation Settings:**

**Language:** English (United States)

**Installation Destination:**
- Select disk
- Automatic partitioning
- Click "Done"

**Network & Hostname:**
- **Hostname:** powerflex-mdm
- **Ethernet:** Click "ON" to enable
- Click "Configure..."
  - **IPv4 Settings:**
    - Method: Manual
    - Address: `192.168.100.10`
    - Netmask: `255.255.255.0`
    - Gateway: `192.168.100.2`
    - DNS: `8.8.8.8,192.168.100.2`
  - Click "Save"
- Click "Done"

**Root Password:**
- Set a strong password (you'll need this for SSH)

**User Creation:**
- Username: `rocky` (or your preference)
- Make user administrator: ✓
- Set password

**Software Selection:**
- Base Environment: **Minimal Install**
- Add "Standard" add-on

**Begin Installation** → Wait 5-10 minutes → **Reboot**

**5.3 Repeat for VM2-VM5:**
| VM | Hostname | IP |
|----|----------|-----|
| VM1 | powerflex-mdm | 192.168.100.10 |
| VM2 | powerflex-sds1 | 192.168.100.11 |
| VM3 | powerflex-sds2 | 192.168.100.12 |
| VM4 | powerflex-sdc1 | 192.168.100.13 |
| VM5 | powerflex-sdc2 | 192.168.100.14 |

---

### Step 6: Post-Install Configuration (All VMs)

**SSH into each VM** (or use VMware console):

**6.1 Update system:**
```bash
sudo dnf update -y
```

**6.2 Install Python 3.11+ and tools:**
```bash
# Python 3.11 (Rocky 9 default)
sudo dnf install -y python3.11 python3-pip git wget curl vim

# Development tools
sudo dnf groupinstall -y "Development Tools"

# Create python3 symlink
sudo alternatives --set python3 /usr/bin/python3.11
```

**6.3 Configure firewall (firewalld, not ufw):**
```bash
# Start firewalld
sudo systemctl start firewalld
sudo systemctl enable firewalld

# Open ports based on role:

# MDM VM:
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --permanent --add-port=5000/tcp

# SDS VMs:
sudo firewall-cmd --permanent --add-port=9100/tcp
sudo firewall-cmd --permanent --add-port=9200/tcp
sudo firewall-cmd --permanent --add-port=9700/tcp

# SDC VMs:
sudo firewall-cmd --permanent --add-port=8003/tcp
sudo firewall-cmd --permanent --add-port=8004/tcp
sudo firewall-cmd --permanent --add-port=8005/tcp
sudo firewall-cmd --permanent --add-port=8013/tcp
sudo firewall-cmd --permanent --add-port=8014/tcp
sudo firewall-cmd --permanent --add-port=8006/tcp

# Reload firewall
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-all
```

**6.4 Disable SELinux (temporary, for testing):**
```bash
# Check current mode
getenforce  # Should show "Enforcing"

# Set to permissive (non-persistent)
sudo setenforce 0

# Set to permissive (persistent across reboots)
sudo sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config

# Verify
getenforce  # Should show "Permissive"
```

*Note: In production, you'd configure proper SELinux contexts instead of disabling it.*

---

### Step 7: Setup SSH Keys from Host

**From your Windows host:**

```powershell
# Generate SSH key (if you don't have one)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa

# Copy SSH key to each VM
# (Enter password when prompted)
ssh-copy-id rocky@192.168.100.10  # MDM
ssh-copy-id rocky@192.168.100.11  # SDS1
ssh-copy-id rocky@192.168.100.12  # SDS2
ssh-copy-id rocky@192.168.100.13  # SDC1
ssh-copy-id rocky@192.168.100.14  # SDC2

# Test passwordless SSH
ssh rocky@192.168.100.10 "hostname"
# Should print: powerflex-mdm
```

---

### Step 8: Prepare Cluster Configuration

**8.1 Generate cluster secret:**
```powershell
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"
```

**8.2 Copy VMware config:**
```powershell
Copy-Item deployment/cluster_config_vmware.yaml deployment/cluster_config.yaml
```

**8.3 Edit cluster_config.yaml:**
```yaml
cluster:
  cluster_secret: "YOUR_GENERATED_SECRET_HERE"

# IPs should already be correct (192.168.100.10-14)
# Adjust if you used different subnet
```

**8.4 Run pre-deployment check:**
```powershell
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe deployment/pre_deployment_check.py deployment/cluster_config.yaml
```

**Expected output:**
```
✓ Local Prerequisites
✓ Network Connectivity
✓ SSH Access
✓ Configuration

✓ All checks passed! Ready for deployment.
```

---

### Step 9: Deploy PowerFlex Components

**Follow [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md)** with these RedHat-specific changes:

**Package installation commands:**
```bash
# Instead of apt:
sudo dnf install -y python3-pip git sqlite

# Instead of ufw:
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --reload
```

**Systemd service files:** (same as Ubuntu, no changes needed)

**Python virtual environment:**
```bash
cd /opt/powerflex
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 🎯 VMware-Specific Features

### VM Snapshots (Backup Before Changes)
```
VMware Workstation → VM → Snapshot → Take Snapshot
Name: "After OS Install" or "Before PowerFlex Deploy"
```

**Use snapshots to:**
- Backup before major changes
- Test failure scenarios
- Quick rollback if something breaks

### VM Cloning (Fast SDS Node Creation)
```
1. Install Rocky Linux on VM2 (SDS1)
2. Configure network, firewall, SSH
3. VMware → VM → Manage → Clone
4. Clone to VM3 (SDS2)
5. Only change: IP address and hostname
```

Saves 15 minutes per additional VM!

### Network Packet Capture
```
VMware → Edit → Virtual Network Editor → VMnet8 → Properties
Enable "Promiscuous Mode" for packet sniffing with Wireshark
```

Useful for debugging network issues.

---

## 📊 Resource Monitoring

**Inside each VM:**
```bash
# CPU usage
top

# Memory usage
free -h

# Disk usage
df -h

# Network stats
ip addr
ss -tuln | grep LISTEN
```

**From VMware Workstation:**
- VM → Power → Performance Monitor
- View real-time CPU, RAM, disk, network usage

---

## ⚠️ Troubleshooting

### Issue: VMs can't reach internet

**Solution:**
```bash
# Check VMware NAT service
# Windows: Services → VMware NAT Service → Start

# In VM, check DNS
cat /etc/resolv.conf
# Should have: nameserver 192.168.100.2

# Test connectivity
ping 8.8.8.8
ping google.com

# If DNS broken:
sudo nmcli con mod "System eth0" ipv4.dns "8.8.8.8 192.168.100.2"
sudo nmcli con down "System eth0" && sudo nmcli con up "System eth0"
```

### Issue: Firewall blocking connections

**Check firewalld:**
```bash
sudo firewall-cmd --list-all
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --reload
```

### Issue: SELinux blocking Python execution

**Check logs:**
```bash
sudo ausearch -m avc -ts recent
```

**Quick fix (testing only):**
```bash
sudo setenforce 0
```

**Proper fix (production):**
```bash
# Allow Python to bind to custom ports
sudo semanage port -a -t http_port_t -p tcp 8001
sudo semanage port -a -t http_port_t -p tcp 9700
# etc.
```

---

## 🚀 Next Steps

**After VM setup complete:**

1. **Follow Phase 14 deployment guide:** [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md)
2. **Deploy MDM** (VM1): 30 minutes
3. **Deploy SDS nodes** (VM2, VM3): 1 hour
4. **Deploy SDC nodes** (VM4, VM5): 45 minutes
5. **Run integration tests:** 30 minutes

**Total Phase 14 time:** 6-8 hours (including VM setup)

---

## ✅ Success Criteria

- [ ] 5 Rocky Linux VMs running in VMware
- [ ] All VMs on 192.168.100.0/24 network
- [ ] SSH access from host to all VMs
- [ ] Firewall ports open on all VMs
- [ ] SELinux in permissive mode
- [ ] Pre-deployment check passes
- [ ] Ready to deploy PowerFlex components

**Questions?** Refer to:
- [VM_SPECS_GUIDE.md](VM_SPECS_GUIDE.md) - General VM requirements
- [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md) - PowerFlex deployment steps
- [QUICKSTART.md](QUICKSTART.md) - Phase 14 overview
