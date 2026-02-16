# PowerFlex Demo - Deployment Scripts Quick Reference

## 📁 Available Scripts

### 1. enable_ssh.sh
**Location:** `deployment/enable_ssh.sh`  
**Purpose:** Enable and configure SSH on RedHat 7.9 VMs  
**Usage:** Run on each VM to enable remote SSH access

```bash
# On VM (as root)
cd /tmp
./enable_ssh.sh
```

**What it does:**
- Installs openssh-server (if not present)
- Enables root login
- Enables password authentication
- Starts and enables sshd service
- Opens firewall port 22
- Shows IP addresses for SSH connection

---

### 2. enable_redhat_repos.sh
**Location:** `deployment/enable_redhat_repos.sh`  
**Purpose:** Register with RedHat Subscription Manager and enable repositories  
**Usage:** Run on each VM after SSH is enabled

```bash
# Interactive mode (prompts for credentials)
cd /tmp
./enable_redhat_repos.sh

# Or with credentials as arguments
./enable_redhat_repos.sh "your-redhat-username" "your-redhat-password"
```

**What it does:**
- Registers system with RedHat Subscription Manager
- Auto-attaches available subscriptions
- Enables RHEL 7 core repositories (rpms, optional, extras)
- Installs EPEL repository
- Updates repository cache
- Displays enabled repos and subscription status

---

### 3. upload_repo_script.ps1
**Location:** `deployment/upload_repo_script.ps1`  
**Purpose:** Upload both setup scripts to all 5 VMs at once  
**Platform:** Windows PowerShell  
**Usage:** Run from Windows to distribute scripts to all VMs

```powershell
# From Windows
cd C:\Users\uid1944\Powerflex_demo\deployment
.\upload_repo_script.ps1
```

**Prerequisites:**
- Git for Windows (includes scp/ssh) or OpenSSH for Windows
- Network connectivity to all VMs
- Root SSH access to all VMs

**What it does:**
- Tests connectivity to all 5 VMs (172.30.128.50-54)
- Uploads enable_ssh.sh to each VM
- Uploads enable_redhat_repos.sh to each VM
- Sets executable permissions on uploaded scripts
- Displays next steps instructions

**VM targets:**
```
172.30.128.50 - pflex-mdm  (MDM + MGMT)
172.30.128.51 - pflex-sds1 (Storage)
172.30.128.52 - pflex-sds2 (Storage)
172.30.128.53 - pflex-sdc1 (Client)
172.30.128.54 - pflex-sdc2 (Client)
```

---

## 🚀 Deployment Workflow

### Step 1: Initial Console Access
If SSH is not yet working, use VMware console to access VM1:

```bash
# On VM1 console
yum install -y openssh-server
systemctl enable --now sshd
ip addr show | grep 172.30.128
```

### Step 2: Upload Scripts from Windows
Once you can SSH to at least one VM:

```powershell
# From Windows PowerShell
cd C:\Users\uid1944\Powerflex_demo\deployment
.\upload_repo_script.ps1
```

### Step 3: Enable SSH on All VMs
SSH to each VM and enable SSH service:

```bash
ssh root@172.30.128.50
cd /tmp
./enable_ssh.sh
exit

# Repeat for other VMs
ssh root@172.30.128.51
cd /tmp && ./enable_ssh.sh && exit

# ... etc for .52, .53, .54
```

### Step 4: Enable RedHat Repos on All VMs
With your RedHat subscription credentials:

```bash
ssh root@172.30.128.50
cd /tmp
./enable_redhat_repos.sh "username" "password"
exit

# Repeat for all VMs
# Or run interactively and paste credentials each time
```

### Step 5: Verify Setup
Check that repos are enabled:

```bash
# On each VM
subscription-manager status
yum repolist
yum search python38
```

---

## 🔍 Troubleshooting

### Upload script fails with "scp not found"
Install Git for Windows: https://git-scm.com/download/win  
Or install OpenSSH for Windows:
```powershell
# Windows 10/11
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

### Cannot SSH to VMs
1. Check if SSH is running: `systemctl status sshd`
2. Check firewall: `firewall-cmd --list-services`
3. Verify IP: `ip addr show`
4. Test from VM: `ssh root@localhost`

### RedHat registration fails
1. Verify credentials are correct
2. Check internet connectivity: `ping access.redhat.com`
3. Check if already registered: `subscription-manager status`
4. Unregister and retry: `subscription-manager unregister && subscription-manager clean`

### Repository list is empty
```bash
# Force refresh
subscription-manager refresh
yum clean all
yum makecache fast
yum repolist
```

---

## 📋 Quick Commands

### Check SSH Status
```bash
systemctl status sshd
netstat -tulpn | grep :22
```

### Check Subscription Status
```bash
subscription-manager status
subscription-manager list --available
subscription-manager repos --list-enabled
```

### Test Package Installation
```bash
# After repos are enabled
yum search python38
yum install -y python38
python3.8 --version
```

### Upload Single Script Manually
```bash
# From Windows to specific VM
scp deployment/enable_ssh.sh root@172.30.128.50:/tmp/
```

### Run Script in One Line (SSH from Windows)
```powershell
# Windows PowerShell
ssh root@172.30.128.50 "cd /tmp && ./enable_ssh.sh"
```

---

## 📞 Support

See full deployment guide: [REDHAT79_DEPLOYMENT_GUIDE.md](REDHAT79_DEPLOYMENT_GUIDE.md)

Repository: https://github.com/Dalymar-0/Powerflex_demo
