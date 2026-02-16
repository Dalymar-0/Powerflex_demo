#!/bin/bash
# PowerFlex Demo - Enable SSH on RedHat 7.9 VMs
# Run this on each RedHat 7.9 VM to enable SSH access
# Usage: ./enable_ssh.sh

set -e  # Exit on error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}PowerFlex - SSH Setup${NC}"
echo -e "${GREEN}========================================${NC}"

# Function to print status
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root (sudo ./enable_ssh.sh)"
    exit 1
fi

# Step 1: Install OpenSSH Server (if not installed)
echo -e "\n${YELLOW}[1/6] Checking OpenSSH Server installation...${NC}"
if ! rpm -q openssh-server &>/dev/null; then
    print_warning "OpenSSH Server not installed. Installing..."
    yum install -y openssh-server
    print_status "OpenSSH Server installed"
else
    print_status "OpenSSH Server already installed"
fi

# Step 2: Configure SSH settings
echo -e "\n${YELLOW}[2/6] Configuring SSH settings...${NC}"
SSHD_CONFIG="/etc/ssh/sshd_config"

# Backup original config
if [ ! -f "${SSHD_CONFIG}.backup" ]; then
    cp $SSHD_CONFIG ${SSHD_CONFIG}.backup
    print_status "Config backed up to ${SSHD_CONFIG}.backup"
fi

# Enable root login (needed for PowerFlex deployment)
if grep -q "^#PermitRootLogin" $SSHD_CONFIG; then
    sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' $SSHD_CONFIG
elif grep -q "^PermitRootLogin" $SSHD_CONFIG; then
    sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' $SSHD_CONFIG
else
    echo "PermitRootLogin yes" >> $SSHD_CONFIG
fi
print_status "Root login enabled"

# Enable password authentication
if grep -q "^#PasswordAuthentication" $SSHD_CONFIG; then
    sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication yes/' $SSHD_CONFIG
elif grep -q "^PasswordAuthentication" $SSHD_CONFIG; then
    sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' $SSHD_CONFIG
else
    echo "PasswordAuthentication yes" >> $SSHD_CONFIG
fi
print_status "Password authentication enabled"

# Step 3: Enable SSH service
echo -e "\n${YELLOW}[3/6] Enabling SSH service...${NC}"
systemctl enable sshd
print_status "SSH service enabled (will start on boot)"

# Step 4: Start SSH service
echo -e "\n${YELLOW}[4/6] Starting SSH service...${NC}"
systemctl restart sshd
if systemctl is-active --quiet sshd; then
    print_status "SSH service is running"
else
    print_error "SSH service failed to start"
    systemctl status sshd
    exit 1
fi

# Step 5: Configure firewall
echo -e "\n${YELLOW}[5/6] Configuring firewall...${NC}"
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=ssh
    firewall-cmd --reload
    print_status "SSH port (22) opened in firewall"
else
    print_warning "Firewall not active (firewalld not running)"
fi

# Step 6: Display SSH status
echo -e "\n${YELLOW}[6/6] Verifying SSH configuration...${NC}"
SSH_PORT=$(grep "^Port" $SSHD_CONFIG | awk '{print $2}')
if [ -z "$SSH_PORT" ]; then
    SSH_PORT=22
fi

# Get IP addresses
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}SSH Configuration Summary:${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "SSH Port: ${YELLOW}${SSH_PORT}${NC}"
echo -e "Root Login: ${YELLOW}Enabled${NC}"
echo -e "Password Auth: ${YELLOW}Enabled${NC}"
echo -e "\nIP Addresses on this machine:"
ip addr show | grep "inet " | grep -v "127.0.0.1" | awk '{print "  " $2}' | sed 's/\/.*//'

# Display service status
echo -e "\n${GREEN}Service Status:${NC}"
systemctl status sshd --no-pager | head -5

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ SSH Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\nYou can now SSH to this machine from another system:"
echo -e "${YELLOW}  ssh root@<ip-address>${NC}"
echo -e "\nTo test from another VM or Windows:"
echo -e "${YELLOW}  ssh root@\$(hostname -I | awk '{print \$1}')${NC}"
