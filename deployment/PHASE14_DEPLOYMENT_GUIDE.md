# Phase 14: Multi-VM Deployment Guide
**PowerFlex Distributed Storage System**  
**Estimated Time:** 6-8 hours  
**Prerequisites:** 5 VMs (Ubuntu 22.04+) with network connectivity

---

## Overview

Deploy PowerFlex components across separate VMs to create a real distributed system:
- **VM1 (10.0.0.1):** MDM + MGMT
- **VM2 (10.0.0.2):** SDS1 (data node)
- **VM3 (10.0.0.3):** SDS2 (data node)
- **VM4 (10.0.0.4):** SDC1 (client node)
- **VM5 (10.0.0.5):** Optional 2nd SDC or test client

---

## Pre-Deployment Checklist

### 1. VM Requirements

**Each VM needs:**
- ✅ Ubuntu 22.04 LTS (or Debian 11+, Rocky Linux 8+)
- ✅ Python 3.13+ installed
- ✅ 2+ GB RAM (4GB recommended for MDM)
- ✅ 50+ GB disk (100GB+ for SDS nodes)
- ✅ Static IP address assigned
- ✅ SSH access configured
- ✅ Firewall ports open (see Network section)

**MDM VM (10.0.0.1):**
- 4 GB RAM
- 50 GB disk
- Ports: 8001 (MDM), 5000 (MGMT GUI)

**SDS VMs (10.0.0.2-3):**
- 2-4 GB RAM
- 100+ GB disk for storage
- Ports: 9700 (data), 9100 (control), 9200 (mgmt)

**SDC VMs (10.0.0.4-5):**
- 2 GB RAM
- 20 GB disk
- Ports: 8005 (NBD), 8003 (control), 8004 (mgmt)

### 2. Network Configuration

**Verify connectivity:**
```bash
# From MDM VM, ping all nodes
ping -c 3 10.0.0.2  # SDS1
ping -c 3 10.0.0.3  # SDS2
ping -c 3 10.0.0.4  # SDC1

# Check latency (should be <100ms)
ping -c 10 10.0.0.2 | tail -1
```

**Open firewall ports:**
```bash
# On MDM VM
sudo ufw allow 8001/tcp  # MDM API
sudo ufw allow 5000/tcp  # MGMT GUI

# On SDS VMs
sudo ufw allow 9700/tcp  # Data server
sudo ufw allow 9100/tcp  # Control API
sudo ufw allow 9200/tcp  # Management API

# On SDC VMs
sudo ufw allow 8005/tcp  # NBD device
sudo ufw allow 8003/tcp  # Control API
sudo ufw allow 8004/tcp  # Management API

# Enable firewall
sudo ufw enable
sudo ufw status
```

### 3. Generate Cluster Secret

**On your local machine:**
```powershell
# Generate 64-character hex secret
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Save this secret - you'll need it for all nodes!

### 4. Edit Configuration

**Edit `deployment/cluster_config.yaml`:**
```yaml
cluster:
  cluster_secret: "YOUR_GENERATED_SECRET_HERE"

mdm:
  ip: "10.0.0.1"  # Your MDM IP

sds_nodes:
  - ip: "10.0.0.2"  # Your SDS1 IP
  - ip: "10.0.0.3"  # Your SDS2 IP

sdc_nodes:
  - ip: "10.0.0.4"  # Your SDC1 IP
```

---

## Deployment Steps

### Step 1: MDM Deployment (VM1 - 10.0.0.1)

**1.1 Install Dependencies:**
```bash
# SSH into MDM VM
ssh ubuntu@10.0.0.1

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and tools
sudo apt install -y python3.13 python3.13-venv python3-pip git sqlite3

# Create project directory
sudo mkdir -p /opt/powerflex
sudo chown $USER:$USER /opt/powerflex
cd /opt/powerflex
```

**1.2 Clone Repository:**
```bash
# Clone from your repo (adjust URL)
git clone https://github.com/Dalymar-0/Powerflex_demo.git .

# Or copy files from local machine
# scp -r C:/Users/uid1944/Powerflex_demo/* ubuntu@10.0.0.1:/opt/powerflex/
```

**1.3 Setup Virtual Environment:**
```bash
cd /opt/powerflex

# Create venv
python3.13 -m venv .venv

# Activate
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

**1.4 Initialize MDM Database:**
```bash
# Initialize powerflex.db
python -c "from mdm.database import init_mdm_database; init_mdm_database()"

# Verify
ls -lh mdm/data/powerflex.db
```

**1.5 Create Systemd Service:**
```bash
sudo tee /etc/systemd/system/powerflex-mdm.service > /dev/null <<'EOF'
[Unit]
Description=PowerFlex MDM Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/powerflex
Environment="PATH=/opt/powerflex/.venv/bin"
ExecStart=/opt/powerflex/.venv/bin/python -m uvicorn mdm.service:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

# Start service
sudo systemctl start powerflex-mdm

# Check status
sudo systemctl status powerflex-mdm

# Enable on boot
sudo systemctl enable powerflex-mdm
```

**1.6 Verify MDM Running:**
```bash
# Check logs
sudo journalctl -u powerflex-mdm -f

# Test API
curl http://127.0.0.1:8001/
curl http://127.0.0.1:8001/health

# Expected: {"service": "PowerFlex MDM", "status": "operational"}
```

### Step 2: SDS1 Deployment (VM2 - 10.0.0.2)

**2.1 Install Dependencies:**
```bash
# SSH into SDS1 VM
ssh ubuntu@10.0.0.2

# Install packages (same as MDM)
sudo apt update && sudo apt install -y python3.13 python3.13-venv git

# Clone repo
sudo mkdir -p /opt/powerflex
sudo chown $USER:$USER /opt/powerflex
cd /opt/powerflex
git clone https://github.com/Dalymar-0/Powerflex_demo.git .

# Setup venv
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2.2 Create Storage Directory:**
```bash
# Create storage root
sudo mkdir -p /var/powerflex/sds1
sudo chown $USER:$USER /var/powerflex/sds1

# Verify disk space
df -h /var/powerflex/sds1
```

**2.3 Register with MDM:**
```bash
# Test connectivity to MDM
curl http://10.0.0.1:8001/

# Register SDS node with MDM discovery
python -c "
import requests

mdm_url = 'http://10.0.0.1:8001'
cluster_secret = 'YOUR_CLUSTER_SECRET_HERE'

# Register discovery component
resp = requests.post(f'{mdm_url}/discovery/register', json={
    'component_type': 'sds',
    'component_id': 'sds-10.0.0.2',
    'address': '10.0.0.2',
    'ports': {'data': 9700, 'control': 9100, 'mgmt': 9200},
    'cluster_secret': cluster_secret,
    'capabilities': ['storage', 'data_server'],
    'metadata': {'storage_root': '/var/powerflex/sds1', 'capacity_gb': 100}
}, timeout=5)

print('Registration:', resp.status_code, resp.json())
"
```

**2.4 Create Protection Domain & Add SDS:**
```bash
# Create PD (run on MDM or from SDS1)
python -c "
import requests

mdm_url = 'http://10.0.0.1:8001'

# Create Protection Domain
pd = requests.post(f'{mdm_url}/pd/create', json={'name': 'PD1'}, timeout=5).json()
print('PD created:', pd['id'])

# Add SDS1 to PD
sds1 = requests.post(f'{mdm_url}/sds/add', json={
    'name': 'SDS1',
    'total_capacity_gb': 100,
    'devices': 'blk0,blk1,blk2',
    'protection_domain_id': pd['id'],
    'cluster_node_id': 'sds-10.0.0.2'
}, timeout=5).json()

print('SDS1 added:', sds1['id'])
"
```

**2.5 Create Systemd Service:**
```bash
sudo tee /etc/systemd/system/powerflex-sds.service > /dev/null <<'EOF'
[Unit]
Description=PowerFlex SDS Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/powerflex
Environment="PATH=/opt/powerflex/.venv/bin"
ExecStart=/opt/powerflex/.venv/bin/python scripts/run_sds_service.py \
    --sds-id 1 \
    --sds-ip 10.0.0.2 \
    --storage-root /var/powerflex/sds1 \
    --mdm-url http://10.0.0.1:8001 \
    --data-port 9700 \
    --control-port 9100 \
    --mgmt-port 9200
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl daemon-reload
sudo systemctl start powerflex-sds
sudo systemctl status powerflex-sds
sudo systemctl enable powerflex-sds
```

**2.6 Verify SDS Running:**
```bash
# Check logs
sudo journalctl -u powerflex-sds -f

# Test data port
nc -zv 10.0.0.2 9700

# Check heartbeat (on MDM)
# ssh ubuntu@10.0.0.1
# curl http://127.0.0.1:8001/health/components
```

### Step 3: SDS2 Deployment (VM3 - 10.0.0.3)

**Repeat Step 2 with these changes:**
- IP: 10.0.0.3
- component_id: 'sds-10.0.0.3'
- sds_id: 2
- storage_root: /var/powerflex/sds2
- name: 'SDS2'

### Step 4: SDC Deployment (VM4 - 10.0.0.4)

**4.1 Install Dependencies:**
```bash
ssh ubuntu@10.0.0.4

sudo apt update && sudo apt install -y python3.13 python3.13-venv git
sudo mkdir -p /opt/powerflex
sudo chown $USER:$USER /opt/powerflex
cd /opt/powerflex
git clone https://github.com/Dalymar-0/Powerflex_demo.git .

python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**4.2 Register & Add SDC:**
```bash
python -c "
import requests

mdm_url = 'http://10.0.0.1:8001'

# Register with discovery
requests.post(f'{mdm_url}/discovery/register', json={
    'component_type': 'sdc',
    'component_id': 'sdc-10.0.0.4',
    'address': '10.0.0.4',
    'ports': {'nbd': 8005, 'control': 8003, 'mgmt': 8004},
    'cluster_secret': 'YOUR_SECRET'
}, timeout=5)

# Add SDC
sdc = requests.post(f'{mdm_url}/sdc/add', json={
    'name': 'SDC1',
    'cluster_node_id': 'sdc-10.0.0.4'
}, timeout=5).json()

print('SDC1 added:', sdc['id'])
"
```

**4.3 Create Systemd Service:**
```bash
sudo tee /etc/systemd/system/powerflex-sdc.service > /dev/null <<'EOF'
[Unit]
Description=PowerFlex SDC Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/powerflex
Environment="PATH=/opt/powerflex/.venv/bin"
ExecStart=/opt/powerflex/.venv/bin/python scripts/run_sdc_service.py \
    --sdc-id 1 \
    --sdc-ip 10.0.0.4 \
    --mdm-url http://10.0.0.1:8001 \
    --nbd-port 8005 \
    --control-port 8003 \
    --mgmt-port 8004
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start powerflex-sdc
sudo systemctl status powerflex-sdc
sudo systemctl enable powerflex-sdc
```

### Step 5: MGMT Deployment (Back on VM1 - 10.0.0.1)

```bash
# On MDM VM
cd /opt/powerflex

# Create systemd service
sudo tee /etc/systemd/system/powerflex-mgmt.service > /dev/null <<'EOF'
[Unit]
Description=PowerFlex MGMT GUI
After=powerflex-mdm.service
Requires=powerflex-mdm.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/powerflex
Environment="PATH=/opt/powerflex/.venv/bin"
Environment="POWERFLEX_MDM_BASE_URL=http://127.0.0.1:8001"
ExecStart=/opt/powerflex/.venv/bin/python -m flask --app mgmt.service run --host 0.0.0.0 --port 5000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start powerflex-mgmt
sudo systemctl status powerflex-mgmt
sudo systemctl enable powerflex-mgmt
```

---

## Testing & Validation

### Test 1: Cluster Health

```bash
# From your local machine or MDM
curl http://10.0.0.1:8001/health
curl http://10.0.0.1:8001/health/components

# Expected: All components ACTIVE with recent heartbeats
```

### Test 2: Create Topology

```bash
python -c "
import requests

mdm = 'http://10.0.0.1:8001'

# Should already have PD from deployment
pd_list = requests.get(f'{mdm}/pd/list').json()
pd_id = pd_list[0]['id']

# Create pool
pool = requests.post(f'{mdm}/pool/create', json={
    'name': 'TestPool',
    'pd_id': pd_id,
    'protection_policy': 'two_copies',
    'total_capacity_gb': 200
}).json()

print('Pool created:', pool['id'])
"
```

### Test 3: Volume Creation & IO

```bash
python -c "
import requests, base64

mdm = 'http://10.0.0.1:8001'

# Get pool_id and sdc_id from previous steps
pool_id = 1
sdc_id = 1

# Create volume
vol = requests.post(f'{mdm}/vol/create', json={
    'name': 'TestVol',
    'size_gb': 10,
    'provisioning': 'thin',
    'pool_id': pool_id
}).json()
vol_id = vol['id']
print(f'Volume created: {vol_id}')

# Map volume
requests.post(f'{mdm}/vol/map', params={
    'volume_id': vol_id,
    'sdc_id': sdc_id,
    'access_mode': 'readWrite'
})
print('Volume mapped')

# Write data
data = b'Hello from distributed PowerFlex!'
requests.post(f'{mdm}/vol/{vol_id}/io/write', json={
    'sdc_id': sdc_id,
    'offset_bytes': 0,
    'data_b64': base64.b64encode(data).decode()
})
print('Data written')

# Read data
read_resp = requests.post(f'{mdm}/vol/{vol_id}/io/read', json={
    'sdc_id': sdc_id,
    'offset_bytes': 0,
    'length_bytes': len(data)
}).json()

read_data = base64.b64decode(read_resp['data_b64'])
print(f'Data read: {read_data}')
print(f'Match: {read_data == data}')
"
```

### Test 4: Cross-VM Verification

```bash
# On SDS1 (10.0.0.2) - Check chunk files
ls -lh /var/powerflex/sds1/chunks/vol_1/

# On SDS2 (10.0.0.3) - Should have replicas
ls -lh /var/powerflex/sds2/chunks/vol_1/

# Both should have same chunk files (replica copies)
```

### Test 5: Failure Scenario

```bash
# Stop SDS1
ssh ubuntu@10.0.0.2 "sudo systemctl stop powerflex-sds"

# Wait 30 seconds (staleness threshold)
sleep 30

# Check health - SDS1 should show STALE
curl http://10.0.0.1:8001/health/components

# Try read - should still work from SDS2
curl http://10.0.0.1:5000/health

# Restart SDS1
ssh ubuntu@10.0.0.2 "sudo systemctl start powerflex-sds"

# Wait for recovery
sleep 10

# Check health - SDS1 should show ACTIVE again
curl http://10.0.0.1:8001/health/components
```

---

## Troubleshooting

### Issue: Cannot reach MDM from SDS

```bash
# Check firewall
sudo ufw status

# Test connectivity
telnet 10.0.0.1 8001

# Check MDM logs
ssh ubuntu@10.0.0.1
sudo journalctl -u powerflex-mdm -n 100
```

### Issue: SDS not registering heartbeat

```bash
# Check SDS logs
sudo journalctl -u powerflex-sds -f

# Verify MDM URL in service file
sudo systemctl cat powerflex-sds

# Restart SDS
sudo systemctl restart powerflex-sds
```

### Issue: IO operations failing

```bash
# Check token generation
curl http://10.0.0.1:8001/token/request

# Check SDS data port
telnet 10.0.0.2 9700
telnet 10.0.0.3 9700

# Check chunk files
ls -lh /var/powerflex/sds1/chunks/
```

---

## Success Criteria

✅ **Phase 14 Complete when:**
- All 5 services running and healthy
- Heartbeats working (check `/health/components`)
- Volume IO working (write on SDS1, read from SDS2)
- Failure test passing (SDS1 down → alert → recovered)
- MGMT GUI accessible at http://10.0.0.1:5000

---

## Next Steps

After Phase 14:
- **Phase 15:** SQLAlchemy 2.0 migration (clean technical debt)
- **Phase 16:** Performance optimization (connection pooling, token caching)
- **Phase 17:** Advanced testing (chaos testing, rebuild engine)

See `docs/STRATEGY_ROADMAP.md` for full roadmap.
