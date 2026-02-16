# VM Specifications & Network Design Guide

**Choose your deployment environment based on budget, learning goals, and time.**

---

## 🎯 Deployment Options Summary

| Option | Cost | Setup Time | Realism | Best For |
|--------|------|------------|---------|----------|
| **VirtualBox (Local)** | Free | 2-3 hours | Medium | Learning, testing, no budget |
| **AWS EC2** | ~$2.50/day | 1-2 hours | High | Portfolio, resume, realistic env |
| **Localhost Sim** | Free | 30 min | Low | Quick testing, code validation |
| **Hybrid (Local+Cloud)** | ~$1/day | 2 hours | Medium | Budget-conscious with some cloud |

---

## Option 1: VirtualBox (Local VMs) ⭐ **Recommended**

### Specs

| Component | vCPUs | RAM | Disk | OS | Purpose |
|-----------|-------|-----|------|-----|---------|
| **VM1: MDM+MGMT** | 2 | 4GB | 50GB | Ubuntu 22.04 | Control plane + GUI |
| **VM2: SDS1** | 2 | 3GB | 120GB | Ubuntu 22.04 | Data storage node 1 |
| **VM3: SDS2** | 2 | 3GB | 120GB | Ubuntu 22.04 | Data storage node 2 |
| **VM4: SDC1** | 1 | 2GB | 30GB | Ubuntu 22.04 | IO client node |
| **VM5: SDC2** (optional) | 1 | 2GB | 30GB | Ubuntu 22.04 | 2nd IO client |

**Total Host Requirements:**
- 16GB RAM minimum (20GB recommended)
- 250GB free disk space
- 8 CPU cores (or 4 with hyperthreading)
- VirtualBox 7.0+ or Hyper-V (Windows Pro)
- Windows 10/11, macOS, or Linux host

### Network Design

**VirtualBox Host-Only Network:**
```
Subnet: 192.168.56.0/24
Gateway: 192.168.56.1 (your host machine)

┌─────────────────────────────────────────────┐
│  Host: 192.168.56.1                          │
│  ├─ VM1 (MDM+MGMT): 192.168.56.10           │
│  ├─ VM2 (SDS1):      192.168.56.11          │
│  ├─ VM3 (SDS2):      192.168.56.12          │
│  └─ VM4 (SDC1):      192.168.56.13          │
└─────────────────────────────────────────────┘
```

**Adapter Configuration:**
- **Adapter 1:** Host-Only Adapter (vboxnet0 / 192.168.56.0/24)
- **Adapter 2** (optional): NAT (for internet access during setup)

### Setup Steps

**1. Install VirtualBox:**
```powershell
# Download from https://www.virtualbox.org/
# Or with Chocolatey:
choco install virtualbox
```

**2. Create Host-Only Network:**
```powershell
# VirtualBox > File > Host Network Manager
# Create network with:
#   IPv4 Address: 192.168.56.1
#   IPv4 Network Mask: 255.255.255.0
#   DHCP Server: Disabled
```

**3. Create VMs (PowerShell script):**
```powershell
# Save as deployment/create_virtualbox_vms.ps1

$ISO_PATH = "C:\ISOs\ubuntu-22.04-server-amd64.iso"  # Download first

# VM1 - MDM
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" createvm --name "PowerFlex-MDM" --ostype Ubuntu_64 --register
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "PowerFlex-MDM" --memory 4096 --cpus 2
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "PowerFlex-MDM" --nic1 hostonly --hostonlyadapter1 "VirtualBox Host-Only Ethernet Adapter"
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "PowerFlex-MDM" --nic2 nat
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" createhd --filename "$HOME\VirtualBox VMs\PowerFlex-MDM\PowerFlex-MDM.vdi" --size 51200
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storagectl "PowerFlex-MDM" --name "SATA" --add sata --controller IntelAhci
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storageattach "PowerFlex-MDM" --storagectl "SATA" --port 0 --device 0 --type hdd --medium "$HOME\VirtualBox VMs\PowerFlex-MDM\PowerFlex-MDM.vdi"
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storagectl "PowerFlex-MDM" --name "IDE" --add ide
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storageattach "PowerFlex-MDM" --storagectl "IDE" --port 0 --device 0 --type dvddrive --medium $ISO_PATH

# VM2 - SDS1
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" createvm --name "PowerFlex-SDS1" --ostype Ubuntu_64 --register
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "PowerFlex-SDS1" --memory 3072 --cpus 2
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "PowerFlex-SDS1" --nic1 hostonly --hostonlyadapter1 "VirtualBox Host-Only Ethernet Adapter"
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "PowerFlex-SDS1" --nic2 nat
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" createhd --filename "$HOME\VirtualBox VMs\PowerFlex-SDS1\PowerFlex-SDS1.vdi" --size 122880
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storagectl "PowerFlex-SDS1" --name "SATA" --add sata --controller IntelAhci
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storageattach "PowerFlex-SDS1" --storagectl "SATA" --port 0 --device 0 --type hdd --medium "$HOME\VirtualBox VMs\PowerFlex-SDS1\PowerFlex-SDS1.vdi"
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storagectl "PowerFlex-SDS1" --name "IDE" --add ide
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" storageattach "PowerFlex-SDS1" --storagectl "IDE" --port 0 --device 0 --type dvddrive --medium $ISO_PATH

# Repeat for SDS2, SDC1 (adjust names, IPs, specs)

Write-Host "VMs created. Install Ubuntu on each VM, then set static IPs:"
Write-Host "  VM1 (MDM):  192.168.56.10"
Write-Host "  VM2 (SDS1): 192.168.56.11"
Write-Host "  VM3 (SDS2): 192.168.56.12"
Write-Host "  VM4 (SDC1): 192.168.56.13"
```

**4. Install Ubuntu on each VM:**
- Boot VM
- Install Ubuntu Server 22.04
- During network setup, configure static IP:
  - Address: 192.168.56.XX (per VM)
  - Gateway: 192.168.56.1
  - DNS: 8.8.8.8
- Install OpenSSH server
- Create user 'ubuntu' with password

**5. Setup SSH keys:**
```powershell
# Generate SSH key (if you don't have one)
ssh-keygen -t rsa -b 4096

# Copy to each VM
ssh-copy-id ubuntu@192.168.56.10  # MDM
ssh-copy-id ubuntu@192.168.56.11  # SDS1
ssh-copy-id ubuntu@192.168.56.12  # SDS2
ssh-copy-id ubuntu@192.168.56.13  # SDC1

# Test
ssh ubuntu@192.168.56.10
```

**6. Use cluster config:**
```powershell
# Copy VirtualBox config
cp deployment/cluster_config_virtualbox.yaml deployment/cluster_config.yaml

# Edit cluster_secret
# Then validate
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe deployment/pre_deployment_check.py deployment/cluster_config.yaml
```

---

## Option 2: AWS EC2 (Cloud VMs)

### Specs

| Component | Instance Type | vCPUs | RAM | Disk | Cost/hour |
|-----------|---------------|-------|-----|------|-----------|
| **MDM+MGMT** | t3.medium | 2 | 4GB | 50GB gp3 | $0.042 |
| **SDS1** | t3.small | 2 | 2GB | 120GB gp3 | $0.021 |
| **SDS2** | t3.small | 2 | 2GB | 120GB gp3 | $0.021 |
| **SDC1** | t3.micro | 2 | 1GB | 30GB gp3 | $0.010 |

**Total:** ~$0.094/hour = **$2.25/day** (24 hours) or **$0.70/session** (8-hour workday)

**Cost for Phase 14:** ~$15-30 (includes deployment + testing + buffer)

### Network Design

**AWS VPC Architecture:**
```
VPC: 10.0.0.0/16

Public Subnet: 10.0.1.0/24 (has internet gateway)
├─ NAT Gateway: 10.0.1.1
├─ MDM:  10.0.1.10 (elastic IP for SSH)
├─ SDS1: 10.0.1.11
├─ SDS2: 10.0.1.12
└─ SDC1: 10.0.1.13

Internet Gateway ──► Public Subnet ──► NAT Gateway
                         │
                         │ (Security Groups)
                         │
                         └──► EC2 Instances
```

**Security Group Rules:**
```yaml
Inbound:
  # SSH (from your IP only)
  - Port: 22
    Protocol: TCP
    Source: YOUR_IP/32
  
  # MDM API (internal only)
  - Port: 8001
    Protocol: TCP
    Source: 10.0.1.0/24
  
  # SDS ports (internal only)
  - Ports: 9100-9700
    Protocol: TCP
    Source: 10.0.1.0/24
  
  # SDC ports (internal only)
  - Ports: 8003-8005
    Protocol: TCP
    Source: 10.0.1.0/24
  
  # MGMT GUI (from your IP only)
  - Port: 5000
    Protocol: TCP
    Source: YOUR_IP/32

Outbound:
  - All traffic (0.0.0.0/0)
```

### Setup Steps

**1. Create infrastructure (Manual):**
```bash
# AWS Console steps:
1. VPC → Create VPC
   - Name: powerflex-vpc
   - CIDR: 10.0.0.0/16

2. Subnets → Create Subnet
   - Name: powerflex-subnet
   - CIDR: 10.0.1.0/24
   - Enable public IPs

3. Internet Gateway → Create
   - Attach to powerflex-vpc

4. Security Group → Create
   - Name: powerflex-sg
   - Add rules above

5. Key Pair → Create
   - Name: powerflex-demo
   - Download powerflex-demo.pem

6. EC2 → Launch Instances (repeat 4x)
   Instance 1 (MDM):
     - AMI: Ubuntu 22.04 LTS
     - Type: t3.medium
     - Subnet: powerflex-subnet
     - Private IP: 10.0.1.10
     - Disk: 50GB gp3
     - Security Group: powerflex-sg
     - Key: powerflex-demo
   
   Instance 2 (SDS1):
     - Type: t3.small
     - Private IP: 10.0.1.11
     - Disk: 120GB gp3
   
   (Repeat for SDS2, SDC1)
```

**2. Configure cluster_config.yaml:**
```powershell
cp deployment/cluster_config_aws.yaml deployment/cluster_config.yaml

# Fill in public IPs from AWS console
# Set ssh_key path to your .pem file
```

**3. Setup SSH:**
```powershell
# Use AWS .pem key
chmod 600 ~/.ssh/powerflex-demo.pem  # Unix
# Or in Windows: Right-click .pem → Properties → Security → Remove all except your user

# Test connection
ssh -i ~/.ssh/powerflex-demo.pem ubuntu@<MDM_PUBLIC_IP>
```

**4. Run pre-deployment check:**
```powershell
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe deployment/pre_deployment_check.py deployment/cluster_config.yaml
```

---

## Option 3: Localhost Simulation (Quick Test)

**For:** Code validation, quick testing without VMs

**Setup:**
```powershell
# Edit cluster_config.yaml
# Set all IPs to 127.0.0.1
# Use different ports:

mdm:
  ip: "127.0.0.1"
  port: 8001

sds_nodes:
  - ip: "127.0.0.1"
    data_port: 9700
    control_port: 9100
    mgmt_port: 9200
  
  - ip: "127.0.0.1"
    data_port: 9701  # Different ports!
    control_port: 9101
    mgmt_port: 9201

sdc_nodes:
  - ip: "127.0.0.1"
    nbd_port: 8005
    control_port: 8003
    mgmt_port: 8004
```

**Run in separate terminals:**
```powershell
# Terminal 1: MDM
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_mdm_service.py

# Terminal 2: SDS1
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_sds_service.py --sds-id 1 --sds-ip 127.0.0.1 --data-port 9700

# Terminal 3: SDS2
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_sds_service.py --sds-id 2 --sds-ip 127.0.0.1 --data-port 9701 --control-port 9101 --mgmt-port 9201

# Terminal 4: SDC
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_sdc_service.py --sdc-id 1 --sdc-ip 127.0.0.1
```

**Limitations:**
- Not truly distributed (same host)
- Can't test network failures
- Less impressive for portfolio

---

## Recommendation by Goal

### Goal: Enterprise/Production Simulation
**Use:** VMware Workstation + Rocky Linux (Option 1A) ⭐  
**Why:** Industry-standard hypervisor, RedHat ecosystem, professional experience

### Goal: Learn Distributed Systems (Free)
**Use:** VirtualBox + Ubuntu (Option 1B)  
**Why:** Real network, failure scenarios, no cost

### Goal: Portfolio/Resume (Cloud)
**Use:** AWS EC2 (Option 2)  
**Why:** Realistic, can demo live, industry-standard

### Goal: Quick Code Testing
**Use:** Localhost (Option 3)  
**Why:** Fast setup, no VM overhead

### Goal: Budget + Some Realism
**Use:** Hybrid (MDM local, SDS/SDC cloud)  
**Why:** Only pay for storage nodes (~$1/day)

---

## Next Steps

**Choose your option, then:**

1. **Setup infrastructure** (VMs or cloud)
2. **Configure cluster_config.yaml** with real IPs
3. **Run pre-deployment check**
4. **Follow PHASE14_DEPLOYMENT_GUIDE.md**

**Which option works best for you?** I can help with:
- VirtualBox VM creation script
- AWS Terraform automation
- Localhost testing setup
- Hybrid deployment configuration
