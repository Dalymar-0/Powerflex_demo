# PowerFlex Demo - RedHat 7.9 Deployment Guide

**Environment:** 5 VMs, RedHat 7.9, VMnet3 (172.30.128.0/24), DHCP enabled  
**Credentials:** root/root  
**Date:** February 16, 2026

---

## 🎯 Deployment Overview

We'll deploy PowerFlex across 5 VMs:
- **VM1:** MDM + MGMT (Management + Control Plane)
- **VM2-3:** SDS nodes (Storage Data Servers)
- **VM4-5:** SDC nodes (Storage Data Clients)

---

## 📋 Phase 1: Initial Setup (All VMs)

### Step 1: Enable SSH Access (All VMs)

Before remote configuration, ensure SSH is enabled and running on all VMs.

**Option A: Run directly on console (first VM only, then use SSH for others):**

```bash
# On VM console (physical or VMware console access)
yum install -y openssh-server
systemctl enable sshd
systemctl start sshd
systemctl status sshd

# Configure root login
sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
systemctl restart sshd

# Open firewall (if enabled)
firewall-cmd --permanent --add-service=ssh
firewall-cmd --reload

# Get IP address
ip addr show | grep "inet 172.30.128"
```

**Option B: Use automated script (after uploading from Windows):**

Once you can SSH to VMs or upload via console, use the automated script:

```bash
cd /tmp
./enable_ssh.sh
```

**Verify SSH is working:**
```bash
# From Windows (PowerShell) or another Linux VM
ssh root@172.30.128.XX
```

---

### Step 2: Discover VM IP Addresses

SSH to each VM and get its DHCP IP:

```bash
# On each VM
ip addr show | grep "inet 172.30.128"
hostname
```

**Document your IPs:**
```
VM1 (MDM+MGMT): 172.30.128.___
VM2 (SDS1):     172.30.128.___
VM3 (SDS2):     172.30.128.___
VM4 (SDC1):     172.30.128.___
VM5 (SDC2):     172.30.128.___
```

### Step 3: Set Static IPs (Recommended)

On each VM, edit network config:

```bash
# Find your network interface name
ip link show

# Edit config (replace ens33 with your interface)
vi /etc/sysconfig/network-scripts/ifcfg-ens33
```

**VM1 (MDM+MGMT) - Set to 172.30.128.50:**
```ini
TYPE=Ethernet
BOOTPROTO=static
NAME=ens33
DEVICE=ens33
ONBOOT=yes
IPADDR=172.30.128.50
NETMASK=255.255.255.0
GATEWAY=172.30.128.1
DNS1=172.30.128.10
```

**VM2 (SDS1) - Set to 172.30.128.51:**
```ini
IPADDR=172.30.128.51
# (same other settings)
```

**VM3 (SDS2) - Set to 172.30.128.52:**
```ini
IPADDR=172.30.128.52
```

**VM4 (SDC1) - Set to 172.30.128.53:**
```ini
IPADDR=172.30.128.53
```

**VM5 (SDC2) - Set to 172.30.128.54:**
```ini
IPADDR=172.30.128.54
```

Restart network on each VM:
```bash
systemctl restart network
# Verify
ip addr show | grep 172.30.128
```

### Step 4: Set Hostnames

```bash
# VM1
hostmatch pflex-mdm
echo "pflex-mdm" > /etc/hostname

# VM2
hostnamectl set-hostname pflex-sds1
echo "pflex-sds1" > /etc/hostname

# VM3
hostnamectl set-hostname pflex-sds2
echo "pflex-sds2" > /etc/hostname

# VM4
hostnamectl set-hostname pflex-sdc1
echo "pflex-sdc1" > /etc/hostname

# VM5
hostnamectl set-hostname pflex-sdc2
echo "pflex-sdc2" > /etc/hostname
```

### Step 5: Update /etc/hosts (All VMs)

```bash
cat >> /etc/hosts << 'EOF'
172.30.128.50  pflex-mdm
172.30.128.51  pflex-sds1
172.30.128.52  pflex-sds2
172.30.128.53  pflex-sdc1
172.30.128.54  pflex-sdc2
EOF
```

### Step 6: Test Connectivity (All VMs)

```bash
ping -c 2 pflex-mdm
ping -c 2 pflex-sds1
ping -c 2 pflex-sds2
ping -c 2 pflex-sdc1
ping -c 2 pflex-sdc2
```

### Step 7: Enable RedHat Repositories (All VMs)

Before installing packages, register with RedHat and enable required repositories.

**Option A: Upload all setup scripts at once (From Windows):**
```powershell
cd C:\Users\uid1944\Powerflex_demo\deployment
.\upload_repo_script.ps1
# This uploads both enable_ssh.sh and enable_redhat_repos.sh to all VMs
```

**Option B: Manual upload to each VM:**
```bash
# From your Windows machine (Git Bash or PowerShell with OpenSSH)
scp deployment/enable_ssh.sh root@172.30.128.50:/tmp/
scp deployment/enable_redhat_repos.sh root@172.30.128.50:/tmp/
# Repeat for other VMs (.51, .52, .53, .54)
```

**On each VM, run:**
```bash
cd /tmp

# First time setup - enable SSH if needed
chmod +x enable_ssh.sh
./enable_ssh.sh

# Then enable RedHat repos
chmod +x enable_redhat_repos.sh

# Option 1: Interactive (will prompt for credentials)
./enable_redhat_repos.sh

# Option 2: Pass credentials as arguments
./enable_redhat_repos.sh "your-redhat-username" "your-redhat-password"
```

The script will:
- Register with RedHat Subscription Manager
- Auto-attach available subscriptions
- Enable core RHEL 7 repositories
- Install EPEL repository
- Update repository cache

**Verify repositories are enabled:**
```bash
subscription-manager status
yum repolist
```

---

## 📋 Phase 2: Install Python 3.13+ (All VMs)

RedHat 7.9 comes with Python 2.7. We need Python 3.9+.

### Option A: Install from EPEL + SCL (Recommended)

```bash
# Enable EPEL and Software Collections
yum install -y epel-release centos-release-scl
yum install -y rh-python38 rh-python38-python-devel

# Enable Python 3.8
scl enable rh-python38 bash

# Make it permanent
echo "source /opt/rh/rh-python38/enable" >> ~/.bashrc
source ~/.bashrc

# Verify
python3 --version  # Should show Python 3.8+
```

### Option B: Build Python 3.11 from Source (If SCL unavailable)

```bash
# Install build dependencies
yum groupinstall -y "Development Tools"
yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel wget

# Download and build Python 3.11
cd /opt
wget https://www.python.org/ftp/python/3.11.7/Python-3.11.7.tgz
tar xzf Python-3.11.7.tgz
cd Python-3.11.7
./configure --enable-optimizations
make altinstall  # Use altinstall to not overwrite system python

# Create symlink
ln -sf /usr/local/bin/python3.11 /usr/local/bin/python3
ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip3

# Verify
python3 --version
```

### Install Required Packages

```bash
pip3 install --upgrade pip
pip3 install fastapi==0.128.5 uvicorn==0.40.0 sqlalchemy==2.0.46 pydantic==2.12.5 requests==2.32.5
```

---

## 📋 Phase 3: Install Git & Clone Repository

### On All VMs:

```bash
yum install -y git

# Clone repository
cd /opt
git clone https://github.com/Dalymar-0/Powerflex_demo.git
cd Powerflex_demo

# Verify Phase 15 migration is present
python3 test_sqlalchemy_migration.py
```

---

## 📋 Phase 4: Initialize Database (VM1 - MDM Only)

```bash
cd /opt/Powerflex_demo

# Initialize powerflex.db
python3 -c "from mdm.database import init_db; init_db()"

# Verify database exists
ls -lh powerflex.db
```

---

## 📋 Phase 5: Configure Each Component

### VM1 (MDM + MGMT):

```bash
cd /opt/Powerflex_demo

# Create systemd service for MDM
cat > /etc/systemd/system/powerflex-mdm.service << 'EOF'
[Unit]
Description=PowerFlex MDM Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Powerflex_demo
Environment="POWERFLEX_MDM_API_PORT=8001"
Environment="POWERFLEX_MDM_BIND_HOST=0.0.0.0"
ExecStart=/usr/local/bin/python3 scripts/run_mdm_service.py --host 0.0.0.0 --port 8001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Create systemd service for MGMT GUI
cat > /etc/systemd/system/powerflex-mgmt.service << 'EOF'
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
ExecStart=/usr/local/bin/python3 flask_gui.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start services
systemctl daemon-reload
systemctl enable powerflex-mdm
systemctl enable powerflex-mgmt
systemctl start powerflex-mdm
systemctl start powerflex-mgmt

# Check status
systemctl status powerflex-mdm
systemctl status powerflex-mgmt
```

### VM2-3 (SDS Nodes):

```bash
cd /opt/Powerflex_demo

# Create storage directory
mkdir -p /data/powerflex/sds
chmod 755 /data/powerflex/sds

# Create systemd service
cat > /etc/systemd/system/powerflex-sds.service << 'EOF'
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
ExecStart=/usr/local/bin/python3 scripts/run_sds_service.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable powerflex-sds
systemctl start powerflex-sds
systemctl status powerflex-sds
```

### VM4-5 (SDC Nodes):

```bash
cd /opt/Powerflex_demo

# Create systemd service
cat > /etc/systemd/system/powerflex-sdc.service << 'EOF'
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
ExecStart=/usr/local/bin/python3 scripts/run_sdc_service.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable powerflex-sdc
systemctl start powerflex-sdc
systemctl status powerflex-sdc
```

---

## 📋 Phase 6: Firewall Configuration (All VMs)

```bash
# Open required ports
firewall-cmd --permanent --add-port=8001/tcp   # MDM API (VM1)
firewall-cmd --permanent --add-port=5000/tcp   # MGMT GUI (VM1)
firewall-cmd --permanent --add-port=9100/tcp   # SDS Control (VM2-3)
firewall-cmd --permanent --add-port=9700/tcp   # SDS Data (VM2-3)
firewall-cmd --permanent --add-port=8003/tcp   # SDC Control (VM4-5)
firewall-cmd --permanent --add-port=8005/tcp   # SDC Device (VM4-5)
firewall-cmd --reload

# Verify
firewall-cmd --list-all
```

**Or disable firewall for testing:**
```bash
systemctl stop firewalld
systemctl disable firewalld
```

---

## 📋 Phase 7: Bootstrap Cluster (From Windows Dev Machine)

```powershell
# Test MDM API from Windows
Invoke-RestMethod -Uri "http://172.30.128.50:8001/pd/list"

# Create Protection Domain
$pd = Invoke-RestMethod -Uri "http://172.30.128.50:8001/pd/create" -Method Post -ContentType "application/json" -Body '{"name":"PD_Main"}'

# Add SDS nodes
$sds1 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sds/add" -Method Post -ContentType "application/json" -Body (@{
    name = "SDS1"
    total_capacity_gb = 100
    devices = "/data/powerflex/sds"
    protection_domain_id = $pd.id
} | ConvertTo-Json)

$sds2 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sds/add" -Method Post -ContentType "application/json" -Body (@{
    name = "SDS2"
    total_capacity_gb = 100
    devices = "/data/powerflex/sds"
    protection_domain_id = $pd.id
} | ConvertTo-Json)

# Create Storage Pool
$pool = Invoke-RestMethod -Uri "http://172.30.128.50:8001/pool/create" -Method Post -ContentType "application/json" -Body (@{
    name = "Pool_Main"
    pd_id = $pd.id
    protection_policy = "two_copies"
    total_capacity_gb = 200
} | ConvertTo-Json)

# Add SDC nodes
$sdc1 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sdc/add" -Method Post -ContentType "application/json" -Body '{"name":"SDC1"}'

$sdc2 = Invoke-RestMethod -Uri "http://172.30.128.50:8001/sdc/add" -Method Post -ContentType "application/json" -Body '{"name":"SDC2"}'

# Create a test volume
$vol = Invoke-RestMethod -Uri "http://172.30.128.50:8001/vol/create" -Method Post -ContentType "application/json" -Body (@{
    name = "TestVolume1"
    size_gb = 10
    provisioning = "thin"
    pool_id = $pool.id
} | ConvertTo-Json)

Write-Host "✅ Cluster bootstrapped!" -ForegroundColor Green
Write-Host "Volume ID: $($vol.id)"
```

---

## 📋 Phase 8: Access Management GUI

Open browser on Windows:
```
http://172.30.128.50:5000
```

Default credentials (if authentication enabled):
- Username: admin
- Password: admin

---

## 🔍 Troubleshooting

### Check Service Status (On Each VM)

```bash
# VM1
systemctl status powerflex-mdm
systemctl status powerflex-mgmt
journalctl -u powerflex-mdm -n 50 --no-pager

# VM2-3
systemctl status powerflex-sds
journalctl -u powerflex-sds -n 50 --no-pager

# VM4-5
systemctl status powerflex-sdc
journalctl -u powerflex-sdc -n 50 --no-pager
```

### Test Network Connectivity

```bash
# From VM2/3/4/5, test MDM connectivity
curl http://172.30.128.50:8001/pd/list

# From Windows
Test-NetConnection -ComputerName 172.30.128.50 -Port 8001
Test-NetConnection -ComputerName 172.30.128.50 -Port 5000
```

### Check Logs

```bash
# MDM logs
tail -f /opt/Powerflex_demo/logs/mdm.log

# SDS logs
tail -f /opt/Powerflex_demo/logs/sds.log

# Or journalctl
journalctl -f -u powerflex-mdm
```

### Common Issues

**1. Port Already in Use:**
```bash
netstat -tulpn | grep 8001
# Kill the process if needed
kill -9 <PID>
```

**2. Python Import Errors:**
```bash
# Verify Python path
which python3
python3 -c "import sys; print(sys.path)"

# Reinstall dependencies
pip3 install --force-reinstall fastapi uvicorn sqlalchemy
```

**3. Database Locked:**
```bash
# Stop all services
systemctl stop powerflex-mdm powerflex-mgmt

# Remove lock file
rm -f /opt/Powerflex_demo/powerflex.db-journal

# Restart
systemctl start powerflex-mdm powerflex-mgmt
```

**4. SELinux Issues (If enabled):**
```bash
# Check SELinux status
getenforce

# Temporarily disable for testing
setenforce 0

# Or configure properly
setsebool -P httpd_can_network_connect 1
```

---

## 📊 Verification Checklist

- [ ] All VMs have static IPs (172.30.128.50-54)
- [ ] All VMs can ping each other
- [ ] Python 3.8+ installed on all VMs
- [ ] Repository cloned to /opt/Powerflex_demo on all VMs
- [ ] MDM service running on VM1
- [ ] MGMT GUI accessible at http://172.30.128.50:5000
- [ ] SDS services running on VM2-3
- [ ] SDC services running on VM4-5
- [ ] Cluster bootstrapped (PD, Pool, Volume created)
- [ ] No errors in service logs

---

## 🎯 Next Steps

Once deployment is complete:
1. **Test IO Operations:** Create volumes, map to SDC, write/read data
2. **Monitor Health:** Check cluster status in GUI
3. **Performance Testing:** Benchmark read/write throughput
4. **High Availability:** Test node failure scenarios
5. **Documentation:** Document your specific network/storage config

---

## 📞 Quick Reference

**Management Endpoints:**
- MDM API: http://172.30.128.50:8001
- MGMT GUI: http://172.30.128.50:5000
- API Docs: http://172.30.128.50:8001/docs

**VM Roles:**
```
VM1 (172.30.128.50): MDM + MGMT  [Control + GUI]
VM2 (172.30.128.51): SDS1        [Storage Node 1]
VM3 (172.30.128.52): SDS2        [Storage Node 2]
VM4 (172.30.128.53): SDC1        [Client Node 1]
VM5 (172.30.128.54): SDC2        [Client Node 2]
```

**Service Commands:**
```bash
systemctl start/stop/restart powerflex-{mdm|mgmt|sds|sdc}
systemctl status powerflex-{mdm|mgmt|sds|sdc}
journalctl -u powerflex-{mdm|mgmt|sds|sdc} -f
```

---

**Ready to deploy? Start with Phase 1 and work through systematically!**
