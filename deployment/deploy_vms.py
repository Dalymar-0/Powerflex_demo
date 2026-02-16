import paramiko
import time
import argparse
import sys
import threading

# Configuration
VMS = [
    {"ip": "172.30.128.50", "name": "pflex-mdm"},
    {"ip": "172.30.128.51", "name": "pflex-sds1"},
    {"ip": "172.30.128.52", "name": "pflex-sds2"},
    {"ip": "172.30.128.53", "name": "pflex-sdc1"},
    {"ip": "172.30.128.54", "name": "pflex-sdc2"}
]

SSH_USER = "root"
SSH_PASS = "root"  # Default password

def run_setup(vm, rh_user, rh_pass):
    ip = vm["ip"]
    name = vm["name"]
    print(f"[{name}] Connecting to {ip}...")
    
    # Escape single quotes for bash
    rh_user_e = rh_user.replace("'", "'\\''")
    rh_pass_e = rh_pass.replace("'", "'\\''")
    
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=SSH_USER, password=SSH_PASS, timeout=10)
        
        # Create setup script content
        setup_script = f"""#!/bin/bash
# set -e
exec > >(tee /var/log/setup_vm.log) 2>&1

echo "=== STARTING SETUP for {name} ==="

yum_retry() {{
    for i in {{1..5}}; do
        yum "$@" && return 0
        echo "  Yum failed, retrying ($i/5)..."
        sleep 5
    done
    return 1
}}

# 1. SSH Config
echo "[1/4] Configuring SSH..."
if ! rpm -q openssh-server >/dev/null; then
    yum_retry install -y openssh-server
fi
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl enable sshd
systemctl restart sshd

# 2. Firewall
echo "[2/4] Configuring Firewall..."
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=ssh
    firewall-cmd --reload
fi

# 3. RedHat Registration
echo "[3/4] Registering RedHat..."
if [ ! -z "{rh_user}" ] && [ ! -z "{rh_pass}" ]; then
    if ! subscription-manager status | grep -q "Overall Status: Current"; then
        subscription-manager unregister || true
        subscription-manager clean
        subscription-manager register --username="{rh_user}" --password="{rh_pass}" --auto-attach --force
    else
        echo "  Already registered."
    fi
else
    echo "  Skipping registration (no credentials provided)."
fi

# 4. Repos
echo "[4/4] Enabling Repos..."
subscription-manager repos --enable=rhel-7-server-rpms \
    --enable=rhel-7-server-optional-rpms \
    --enable=rhel-7-server-extras-rpms

# Clear yum cache to ensure repo lists are fresh
yum clean all

# Install EPEL (try package first, fallback to manual curl download)
if ! yum_retry install -y epel-release; then
    echo "  Package install failed, trying manual download from archive..."
    # Try archive URL for RHEL 7 EPEL as stable URL might vary
    curl --retry 5 --retry-delay 5 -k -L -o /tmp/epel-release.rpm https://archives.fedoraproject.org/pub/archive/epel/7/x86_64/Packages/e/epel-release-7-14.noarch.rpm
    if [ -f /tmp/epel-release.rpm ] && [ $(stat -c%s /tmp/epel-release.rpm) -gt 1000 ]; then
        yum_retry install -y /tmp/epel-release.rpm
    else
        echo "  Failed to download valid EPEL rpm."
        if yum list available python3-pip >/dev/null 2>&1; then
             echo "  python3-pip found in base repos, proceeding without EPEL-RELEASE package."
        else
             echo "  WARNING: EPEL failed and python3-pip missing. You may need to install EPEL manually."
        fi
    fi
fi

# Modify EPEL to skip if unavailable (prevents yum die on bad mirror)
if [ -f /etc/yum.repos.d/epel.repo ]; then
    sed -i '/\\[epel\\]/a skip_if_unavailable=1' /etc/yum.repos.d/epel.repo
fi

yum_retry makecache fast

# 5. Install Python 3
echo "[5/5] Installing Python 3..."
if ! rpm -q python3 >/dev/null && ! rpm -q python36 >/dev/null; then
    yum_retry install -y python3 python3-pip || yum_retry install -y python36 python36-pip
fi
python3 --version || python3.6 --version

echo "=== SYSTEM READY ==="

echo "=== SETUP COMPLETE for {name} ==="
"""
        
        # Upload script
        print(f"[{name}] Uploading setup script...")
        ftp = client.open_sftp()
        f = ftp.file('/tmp/automated_setup.sh', 'w')
        f.write(setup_script)
        f.close()
        ftp.close()
        
        # Execute script
        print(f"[{name}] Executing setup (this may take 2-5 mins)...")
        stdin, stdout, stderr = client.exec_command("chmod +x /tmp/automated_setup.sh && /tmp/automated_setup.sh")
        
        # Stream output
        exit_status = stdout.channel.recv_exit_status()
        
        if exit_status == 0:
            print(f"[{name}] ✅ SUCCESS")
        else:
            print(f"[{name}] ❌ FAILED")
            print(stdout.read().decode())
            print(stderr.read().decode())
            
        client.close()
        
    except Exception as e:
        print(f"[{name}] ❌ ERROR: {str(e)}")

def main():
    if len(sys.argv) < 3:
        try:
            import getpass
            print("\n=== PowerFlex Automated Deployment ===")
            print("Please provide RedHat credentials for registration.")
            rh_user = input("RedHat Username (Press Enter to skip registration if already done): ").strip()
            if not rh_user:
                print("Skipping registration (assuming already done).")
                rh_pass = ""
            else:
                rh_pass = getpass.getpass("RedHat Password: ").strip()
        except ImportError:
            print("Error: getpass module not found.")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(1)
    else:
        rh_user = sys.argv[1]
        rh_pass = sys.argv[2]
    
    threads = []
    print(f"\nStarting deployment to {len(VMS)} VMs in parallel...")
    
    for vm in VMS:
        t = threading.Thread(target=run_setup, args=(vm, rh_user, rh_pass))
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()
        
    print("\nAll tasks finished.")

if __name__ == "__main__":
    main()
