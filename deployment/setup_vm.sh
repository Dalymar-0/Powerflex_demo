#!/bin/bash
# PowerFlex Demo - All-in-One VM Setup Script
# Run this script ON each VM (not from Windows)
# Usage: curl -O <url-to-this-script> && bash setup_vm.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}PowerFlex VM - Complete Setup${NC}"
echo -e "${GREEN}========================================${NC}"

# Must run as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}✗ Please run as root${NC}"
    exit 1
fi

# Step 1: Enable SSH
echo -e "\n${YELLOW}▶ Step 1: Configuring SSH...${NC}"
yum install -y openssh-server &>/dev/null
systemctl enable sshd &>/dev/null
systemctl start sshd &>/dev/null

# Configure SSH for root login
sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl restart sshd

# Open firewall if active
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=ssh &>/dev/null
    firewall-cmd --reload &>/dev/null
fi

echo -e "${GREEN}✓ SSH enabled and configured${NC}"

# Step 2: RedHat Subscription (optional - requires credentials)
echo -e "\n${YELLOW}▶ Step 2: RedHat Subscription Setup${NC}"
echo -n "Do you want to register with RedHat now? (y/n): "
read -r REGISTER

if [ "$REGISTER" = "y" ] || [ "$REGISTER" = "Y" ]; then
    echo -n "RedHat Username: "
    read -r RH_USER
    echo -n "RedHat Password: "
    read -sr RH_PASS
    echo ""
    
    echo "Registering with RedHat..."
    subscription-manager unregister &>/dev/null || true
    subscription-manager clean &>/dev/null
    
    if subscription-manager register --username="$RH_USER" --password="$RH_PASS" --auto-attach; then
        echo -e "${GREEN}✓ Registration successful${NC}"
        
        # Enable repositories
        subscription-manager repos --enable=rhel-7-server-rpms &>/dev/null
        subscription-manager repos --enable=rhel-7-server-optional-rpms &>/dev/null
        subscription-manager repos --enable=rhel-7-server-extras-rpms &>/dev/null
        echo -e "${GREEN}✓ Repositories enabled${NC}"
        
        # Install EPEL
        yum install -y epel-release &>/dev/null
        echo -e "${GREEN}✓ EPEL installed${NC}"
        
        # Update cache
        yum clean all &>/dev/null
        yum makecache fast &>/dev/null
        echo -e "${GREEN}✓ Repository cache updated${NC}"
    else
        echo -e "${RED}✗ Registration failed${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Skipping RedHat registration${NC}"
    echo "  You can run later: ./enable_redhat_repos.sh"
fi

# Display summary
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Hostname: $(hostname)"
echo -e "IP Address: $(ip addr show | grep 'inet 172.30.128' | awk '{print $2}' | cut -d/ -f1)"
echo -e "SSH Status: $(systemctl is-active sshd)"
echo -e "Subscription: $(subscription-manager status 2>/dev/null | grep 'Overall Status' || echo 'Not registered')"

echo -e "\n${YELLOW}Next: SSH to this machine from Windows or another VM${NC}"
