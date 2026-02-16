# Phase 14: Multi-VM Deployment — Quick Start

**Time:** 6-8 hours  
**Deliverable:** 5-node distributed cluster running on separate VMs

---

## What You'll Build

```
┌─────────────────────────────────────────────────────────────┐
│                    VM1: MDM + MGMT                          │
│              (10.0.0.1 - Control Plane)                     │
│  - MDM API (8001): Topology, tokens, discovery             │
│  - MGMT GUI (5000): Dashboard, monitoring, alerts          │
└─────────────────────────────────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    ┌────▼────┐        ┌────▼────┐       ┌────▼────┐
    │  VM2    │        │  VM3    │       │  VM4    │
    │  SDS1   │        │  SDS2   │       │  SDC1   │
    │10.0.0.2 │        │10.0.0.3 │       │10.0.0.4 │
    ├─────────┤        ├─────────┤       ├─────────┤
    │ 9700    │◄──────►│ 9700    │       │ 8005    │
    │ 9100    │  Repl  │ 9100    │       │ 8003    │
    │ 9200    │        │ 9200    │       │ 8004    │
    └─────────┘        └─────────┘       └─────────┘
   Data Storage       Data Storage       IO Client
```

---

## Prerequisites

### VMs Required
- **5 Ubuntu 22.04 VMs** with static IPs (10.0.0.1-5)
- **SSH access** configured (passwordless with ssh-copy-id)
- **Firewall rules** allowing inter-VM communication
- **Network latency** <100ms between VMs

### Local Machine
- Python 3.10+ with PyYAML (`pip install pyyaml`)
- SSH client
- Git

---

## 3-Step Setup

### Step 1: Configure (5 minutes)

```powershell
# 1.1 Generate cluster secret
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"

# 1.2 Edit deployment/cluster_config.yaml
# Change these values:
#   - cluster.cluster_secret: <your generated secret>
#   - mdm.ip: <your MDM VM IP>
#   - sds_nodes[0].ip: <your SDS1 VM IP>
#   - sds_nodes[1].ip: <your SDS2 VM IP>
#   - sdc_nodes[0].ip: <your SDC VM IP>

# 1.3 Validate configuration
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe deployment/pre_deployment_check.py deployment/cluster_config.yaml
```

**Expected output:** `✓ All checks passed! Ready for deployment.`

---

### Step 2: Deploy Components (4-6 hours)

Follow the step-by-step guide in [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md):

**Timeline:**
- **Hour 1:** MDM deployment (VM1)
  - Install dependencies
  - Initialize database
  - Create systemd service
  - Verify API running

- **Hours 2-3:** SDS deployment (VM2, VM3)
  - Clone repo to each VM
  - Register with MDM discovery
  - Create storage directories
  - Start data servers

- **Hour 4:** SDC deployment (VM4)
  - Setup SDC environment
  - Register with MDM
  - Start NBD device server

- **Hour 5:** MGMT deployment (VM1)
  - Start Flask GUI
  - Configure monitoring
  - Setup alerting

---

### Step 3: Test & Validate (1-2 hours)

```bash
# 3.1 Check cluster health
curl http://10.0.0.1:8001/health/components

# Expected: All components ACTIVE with recent heartbeats

# 3.2 Create test volume
python -c "
import requests, base64, time

mdm = 'http://10.0.0.1:8001'

# Get IDs (adjust if needed)
pool_id = 1
sdc_id = 1

# Create 10GB volume
vol = requests.post(f'{mdm}/vol/create', json={
    'name': f'TestVol_{int(time.time())}',
    'size_gb': 10,
    'provisioning': 'thin',
    'pool_id': pool_id
}).json()

print(f'Volume {vol[\"id\"]} created')

# Map to SDC
requests.post(f'{mdm}/vol/map', params={
    'volume_id': vol['id'],
    'sdc_id': sdc_id,
    'access_mode': 'readWrite'
})

# Write test data
data = b'PowerFlex Distributed Storage Working!'
requests.post(f'{mdm}/vol/{vol[\"id\"]}/io/write', json={
    'sdc_id': sdc_id,
    'offset_bytes': 0,
    'data_b64': base64.b64encode(data).decode()
})

# Read back
resp = requests.post(f'{mdm}/vol/{vol[\"id\"]}/io/read', json={
    'sdc_id': sdc_id,
    'offset_bytes': 0,
    'length_bytes': len(data)
}).json()

read_data = base64.b64decode(resp['data_b64'])
print(f'Read: {read_data}')
print(f'Match: {read_data == data}')
"

# 3.3 Test failure recovery
# Stop SDS1
ssh ubuntu@10.0.0.2 "sudo systemctl stop powerflex-sds"

# Wait 30s
sleep 30

# Check health (SDS1 should be STALE)
curl http://10.0.0.1:8001/health/components

# Try read (should still work from SDS2)
# ... repeat read test above ...

# Restart SDS1
ssh ubuntu@10.0.0.2 "sudo systemctl start powerflex-sds"

# Verify recovery
sleep 10
curl http://10.0.0.1:8001/health/components
```

---

## Success Criteria

✅ **Phase 14 Complete When:**
1. All 5 systemd services running (`systemctl status powerflex-*`)
2. All components sending heartbeats (`/health/components` shows ACTIVE)
3. Volume creation works across VMs
4. Write on SDS1 → Read from SDS2 (replication working)
5. Failure test passes (SDS1 down → alert → restart → recovered)
6. MGMT GUI accessible at http://10.0.0.1:5000

---

## Common Issues

### Issue: Pre-deployment check fails

**Problem:** `✗ SSH Access` fails for VM  
**Solution:**
```bash
# Copy SSH key to VM
ssh-copy-id ubuntu@10.0.0.2

# Or manually
cat ~/.ssh/id_rsa.pub | ssh ubuntu@10.0.0.2 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### Issue: MDM service won't start

**Problem:** `systemctl status powerflex-mdm` shows failed  
**Solution:**
```bash
# Check logs
sudo journalctl -u powerflex-mdm -n 50

# Common causes:
# 1. Port 8001 already in use
sudo lsof -i :8001
sudo kill <PID>

# 2. Database not initialized
cd /opt/powerflex
source .venv/bin/activate
python -c "from mdm.database import init_mdm_database; init_mdm_database()"

# 3. Permission issues
sudo chown -R ubuntu:ubuntu /opt/powerflex
```

### Issue: SDS not registering heartbeat

**Problem:** `/health/components` shows SDS missing  
**Solution:**
```bash
# On SDS VM
sudo journalctl -u powerflex-sds -f

# Check:
# 1. MDM URL correct in systemd service
sudo systemctl cat powerflex-sds

# 2. Network connectivity
telnet 10.0.0.1 8001

# 3. Cluster secret matches MDM
# Re-register with correct secret
```

### Issue: IO operations fail

**Problem:** Volume write/read returns 500 error  
**Solution:**
```bash
# 1. Check SDS data ports open
telnet 10.0.0.2 9700
telnet 10.0.0.3 9700

# 2. Check token generation
curl http://10.0.0.1:8001/token/request?volume_id=1&operation=read

# 3. Check chunk directories
ssh ubuntu@10.0.0.2 "ls -lh /var/powerflex/sds1/chunks/"

# 4. Check SDS logs for errors
ssh ubuntu@10.0.0.2 "sudo journalctl -u powerflex-sds -n 100"
```

---

## Deployment Verification Checklist

Copy this checklist and check off as you complete each task:

### Pre-Deployment
- [ ] 5 VMs provisioned with Ubuntu 22.04
- [ ] Static IPs assigned (10.0.0.1-5)
- [ ] SSH keys copied to all VMs
- [ ] Firewall ports opened on all VMs
- [ ] Cluster secret generated
- [ ] `cluster_config.yaml` edited with real IPs
- [ ] Pre-deployment check passed

### MDM Deployment (VM1)
- [ ] Dependencies installed
- [ ] Repo cloned to /opt/powerflex
- [ ] Virtual environment created
- [ ] Database initialized (powerflex.db exists)
- [ ] Systemd service created
- [ ] Service started and enabled
- [ ] API responding (curl http://127.0.0.1:8001/)

### SDS1 Deployment (VM2)
- [ ] Dependencies installed
- [ ] Repo cloned
- [ ] Virtual environment created
- [ ] Storage directory created (/var/powerflex/sds1)
- [ ] Registered with MDM discovery
- [ ] Added to Protection Domain
- [ ] Systemd service created
- [ ] Service started and enabled
- [ ] Data port open (nc -zv 10.0.0.2 9700)

### SDS2 Deployment (VM3)
- [ ] Dependencies installed
- [ ] Repo cloned
- [ ] Virtual environment created
- [ ] Storage directory created (/var/powerflex/sds2)
- [ ] Registered with MDM discovery
- [ ] Added to Protection Domain
- [ ] Systemd service created
- [ ] Service started and enabled
- [ ] Data port open (nc -zv 10.0.0.3 9700)

### SDC Deployment (VM4)
- [ ] Dependencies installed
- [ ] Repo cloned
- [ ] Virtual environment created
- [ ] Registered with MDM discovery
- [ ] Added to MDM
- [ ] Systemd service created
- [ ] Service started and enabled
- [ ] NBD port open (nc -zv 10.0.0.4 8005)

### MGMT Deployment (VM1)
- [ ] Systemd service created
- [ ] Service started and enabled
- [ ] GUI accessible (http://10.0.0.1:5000)
- [ ] Can login to dashboard
- [ ] Metrics page shows all components

### Integration Testing
- [ ] All components show ACTIVE in /health/components
- [ ] Pool created successfully
- [ ] Volume created successfully
- [ ] Volume mapped to SDC
- [ ] Write test passed
- [ ] Read test passed
- [ ] Cross-VM data verification (chunks on both SDS nodes)

### Failure Testing
- [ ] SDS1 stop detected (status changes to STALE)
- [ ] Alert generated for SDS1 failure
- [ ] Read operations still work (from SDS2)
- [ ] SDS1 restart successful
- [ ] SDS1 status returns to ACTIVE
- [ ] No data loss after recovery

---

## Portfolio Showcase

After completing Phase 14, you'll have:

✅ **Deployed a 5-node distributed cluster**  
✅ **Demonstrated cross-VM replication**  
✅ **Tested failure and recovery scenarios**  
✅ **Implemented heartbeat monitoring**  
✅ **Built management dashboard for multi-VM cluster**

**Talking points for interviews:**
- "Deployed PowerFlex across 5 VMs with automated discovery and registration"
- "Implemented distributed replication with automatic failover between SDS nodes"
- "Built monitoring dashboard that tracks health across network-partitioned components"
- "Tested failure scenarios: network partition, process crash, and auto-recovery"

---

## Next Steps After Phase 14

**Recommended path:**
1. **Phase 15** (5-7 hours): SQLAlchemy 2.0 migration
   - Clean up technical debt
   - Modernize database layer
   - Improve query performance

**Optional enhancements:**
2. **Phase 16** (8-10 hours): Performance optimization
   - Connection pooling
   - Token caching
   - Batch operations

3. **Phase 17** (6-8 hours): Advanced testing
   - Chaos engineering
   - Load testing
   - Rebuild engine validation

4. **Phase 18** (10-12 hours): Production hardening
   - TLS/SSL
   - Rate limiting
   - Comprehensive observability

See [STRATEGY_ROADMAP.md](../docs/STRATEGY_ROADMAP.md) for full roadmap.

---

## Need Help?

- **Detailed guide:** [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md)
- **Configuration:** [cluster_config.yaml](cluster_config.yaml)
- **Validation:** `python deployment/pre_deployment_check.py deployment/cluster_config.yaml`
- **Architecture:** [REFORM_PLAN.md](../docs/REFORM_PLAN.md)

**Ready to start?** Run the pre-deployment check first! 🚀
