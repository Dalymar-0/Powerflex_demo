#!/bin/bash
RH_USER='dalymarouan@gmail.com'
RH_PASS='gg*xXxG,j4Crh!U'
echo "[1/5] SSH setup..."
yum install -y openssh-server >/dev/null 2>&1
systemctl enable sshd >/dev/null 2>&1
systemctl start sshd >/dev/null 2>&1
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl restart sshd >/dev/null 2>&1
echo "[2/5] RedHat registration..."
subscription-manager unregister >/dev/null 2>&1 || true
subscription-manager register --username="$RH_USER" --password="$RH_PASS" --auto-attach >/dev/null 2>&1
echo "[3/5] Enable repos..."
subscription-manager repos --enable=rhel-7-server-rpms >/dev/null 2>&1
subscription-manager repos --enable=rhel-7-server-optional-rpms >/dev/null 2>&1
subscription-manager repos --enable=rhel-7-server-extras-rpms >/dev/null 2>&1
echo "[4/5] Install EPEL..."
yum install -y epel-release >/dev/null 2>&1
echo "[5/5] Update cache..."
yum clean all >/dev/null 2>&1
yum makecache fast >/dev/null 2>&1
echo "=== Setup Complete ==="