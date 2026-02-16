#!/bin/bash
# PowerFlex Demo - RedHat Repository Activation Script
# Run this on each RedHat 7.9 VM to enable repositories
# Usage: ./enable_redhat_repos.sh [username] [password]

set -e  # Exit on error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}PowerFlex - RedHat Repository Setup${NC}"
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
    print_error "Please run as root (sudo ./enable_redhat_repos.sh)"
    exit 1
fi

# Get credentials
if [ -z "$1" ] || [ -z "$2" ]; then
    echo -e "${YELLOW}RedHat Subscription Credentials Required${NC}"
    echo -n "RedHat Username/Email: "
    read RH_USERNAME
    echo -n "RedHat Password: "
    read -s RH_PASSWORD
    echo ""
else
    RH_USERNAME="$1"
    RH_PASSWORD="$2"
fi

# Step 1: Unregister if already registered
echo -e "\n${YELLOW}[1/6] Checking registration status...${NC}"
if subscription-manager status &>/dev/null; then
    print_warning "System already registered. Unregistering first..."
    subscription-manager unregister || true
    subscription-manager clean
fi
print_status "Ready to register"

# Step 2: Register with RedHat
echo -e "\n${YELLOW}[2/6] Registering with RedHat Subscription Manager...${NC}"
subscription-manager register --username="$RH_USERNAME" --password="$RH_PASSWORD" --auto-attach
if [ $? -eq 0 ]; then
    print_status "Registration successful"
else
    print_error "Registration failed. Check credentials."
    exit 1
fi

# Step 3: Attach subscription
echo -e "\n${YELLOW}[3/6] Attaching subscription...${NC}"
subscription-manager attach --auto
print_status "Subscription attached"

# Step 4: Enable required repositories for RHEL 7.9
echo -e "\n${YELLOW}[4/6] Enabling required repositories...${NC}"
subscription-manager repos --enable=rhel-7-server-rpms
subscription-manager repos --enable=rhel-7-server-optional-rpms
subscription-manager repos --enable=rhel-7-server-extras-rpms
print_status "Core repositories enabled"

# Step 5: Install EPEL repository
echo -e "\n${YELLOW}[5/6] Installing EPEL repository...${NC}"
yum install -y epel-release
print_status "EPEL repository installed"

# Step 6: Update repository cache
echo -e "\n${YELLOW}[6/6] Updating repository cache...${NC}"
yum clean all
yum makecache fast
print_status "Repository cache updated"

# Display enabled repositories
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Enabled Repositories:${NC}"
echo -e "${GREEN}========================================${NC}"
subscription-manager repos --list-enabled | grep -E "(Repo ID|Repo Name)" | head -20

# Display system status
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Subscription Status:${NC}"
echo -e "${GREEN}========================================${NC}"
subscription-manager status

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "You can now install packages using yum."
echo -e "Example: ${YELLOW}yum install -y python38${NC}"
echo -e "\nTo verify: ${YELLOW}yum repolist${NC}"
