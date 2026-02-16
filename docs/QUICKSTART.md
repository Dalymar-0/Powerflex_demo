"""
PowerFlex Demo — Quick Start Guide (Phase 10.5+)
================================================

This guide shows how to start the new architecture services.

SERVICES OVERVIEW
-----------------

1. MDM (Metadata Manager) — Port 8001
   - Central control plane
   - Volume/PD/Pool/SDS/SDC management
   - Token authority
   - Health monitoring
   - Package: mdm/

2. MGMT (Management GUI) — Port 5000
   - Web dashboard
   - Component monitoring
   - Alert management
   - Package: mgmt/

3. SDS (Storage Data Server) — Ports 9700+, 9100+, 9200+
   - Data storage backend
   - TCP data handler
   - HTTP control/mgmt APIs
   - Package: sds/

4. SDC (Storage Data Client) — Ports 8003, 8004, 8005
   - Block device client
   - NBD protocol server
   - Volume mapping
   - Package: sdc/

STARTING SERVICES
-----------------

## 1. Start MDM Service

```powershell
# Kill any existing MDM process
$conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }

# Start MDM
cd C:\Users\uid1944\Powerflex_demo
.venv\Scripts\python.exe scripts\run_mdm_service.py --host 0.0.0.0 --port 8001
```

Verify:
```powershell
curl http://127.0.0.1:8001/
# Should return: {"service":"mdm","message":"PowerFlex MDM control-plane service running (restructured)"}
```

## 2. Start MGMT Service

```powershell
cd C:\Users\uid1944\Powerflex_demo
.venv\Scripts\python.exe scripts\run_mgmt_service.py
```

Verify:
```powershell
curl http://127.0.0.1:5000/
# Should return HTML dashboard
```

Access GUI: http://127.0.0.1:5000

## 3. Start SDS Service (Optional - for data plane testing)

```powershell
cd C:\Users\uid1944\Powerflex_demo

# SDS Node 1
.venv\Scripts\python.exe scripts\run_sds_service.py `
  --sds-id 1 `
  --sds-ip 127.0.0.1 `
  --storage-root ./vm_storage/sds1 `
  --data-port 9701 `
  --control-port 9101 `
  --mgmt-port 9201

# SDS Node 2 (in separate terminal)
.venv\Scripts\python.exe scripts\run_sds_service.py `
  --sds-id 2 `
  --sds-ip 127.0.0.2 `
  --storage-root ./vm_storage/sds2 `
  --data-port 9702 `
  --control-port 9102 `
  --mgmt-port 9202
```

## 4. Start SDC Service (Optional - for NBD testing)

```powershell
cd C:\Users\uid1944\Powerflex_demo

.venv\Scripts\python.exe scripts\run_sdc_service.py `
  --sdc-id 1 `
  --address 127.0.0.1 `
  --nbd-port 8005 `
  --control-port 8003 `
  --mgmt-port 8004
```

TESTING
-------

## Quick Architecture Test

```powershell
.venv\Scripts\python.exe scripts\test_new_architecture.py
```

Expected output:
```
============================================================
SUCCESS! New architecture is fully functional!
============================================================
Created topology: PD → 2xSDS → Pool → Volume → SDC
Volume ID 5 mapped to SDC 28
```

## Full Integration Test

```powershell
.venv\Scripts\python.exe scripts\test_phase10_integration.py
```

Expected pass rate: 62.5% (15/24 tests)

## Manual API Test

```powershell
.venv\Scripts\python.exe -c "
import requests, time, base64
b = 'http://127.0.0.1:8001'
t = str(int(time.time()))

# Bootstrap
resp = requests.post(f'{b}/cluster/bootstrap/minimal', json={'prefix': 'test-'+t})
print(f'Bootstrap: {resp.status_code}')

# Create PD
pd = requests.post(f'{b}/pd/create', json={'name': 'TestPD_'+t}).json()
print(f'PD created: {pd[\"id\"]}')

# Register SDS node
requests.post(f'{b}/cluster/nodes/register', json={
    'node_id': 'test-sds-1',
    'name': 'Test SDS 1',
    'capabilities': ['SDS'],
    'address': '127.0.0.1',
    'port': 9701
})

# Add SDS
sds = requests.post(f'{b}/sds/add', json={
    'name': 'TestSDS_'+t,
    'total_capacity_gb': 64,
    'devices': 'blk0',
    'protection_domain_id': pd['id'],
    'cluster_node_id': 'test-sds-1'
}).json()
print(f'SDS created: {sds[\"id\"]}')

# Create Pool
pool = requests.post(f'{b}/pool/create', json={
    'name': 'TestPool_'+t,
    'pd_id': pd['id'],
    'protection_policy': 'two_copies',
    'total_capacity_gb': 128
}).json()
print(f'Pool created: {pool[\"id\"]}')

# Create Volume (the critical test!)
vol = requests.post(f'{b}/vol/create', json={
    'name': 'TestVol_'+t,
    'size_gb': 0.1,  # 100 MB
    'provisioning': 'thin',
    'pool_id': pool['id']
}).json()
print(f'Volume created: {vol[\"id\"]}')
print('SUCCESS: Volume creation working!')
"
```

TROUBLESHOOTING
---------------

### Port 8001 already in use
```powershell
$conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $proc = Get-Process -Id $conn.OwningProcess
    Write-Host "MDM on port 8001: PID $($conn.OwningProcess) ($($proc.Name))"
    Stop-Process -Id $conn.OwningProcess -Force
}
```

### Database locked errors
```powershell
# Close all Python processes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Restart MDM
.venv\Scripts\python.exe scripts\run_mdm_service.py
```

### Volume creation fails with "No space left on device"
```powershell
# Check disk space
Get-PSDrive C | Select-Object @{Name="Free(GB)";Expression={[math]::Round($_.Free/1GB,2)}}

# Clean old volumes
Get-ChildItem vm_storage -Recurse -Filter "vol_*.img" | Remove-Item -Force

# Clean database
.venv\Scripts\python.exe -c "
import sqlite3
conn = sqlite3.connect('powerflex.db')
cur = conn.cursor()
cur.execute('DELETE FROM volume_mappings')
cur.execute('DELETE FROM replicas')
cur.execute('DELETE FROM chunks')
cur.execute('DELETE FROM volumes')
conn.commit()
cur.execute('VACUUM')
conn.close()
print('Database cleaned')
"
```

### Import errors
```powershell
# Make sure you're in project root
cd C:\Users\uid1944\Powerflex_demo

# Verify virtual environment
.venv\Scripts\python.exe -c "import sys; print('Python:', sys.executable)"

# Test imports
.venv\Scripts\python.exe -c "from mdm.service import app; print('MDM OK')"
.venv\Scripts\python.exe -c "from mgmt.service import app; print('MGMT OK')"
```

### MGMT service returns 500 errors
This is currently expected. The MGMT service calls MDM health endpoints that
return 500 errors. The service is functional but some data won't load.

To verify MGMT is running:
```powershell
curl http://127.0.0.1:5000/
# Should return HTML even if with errors
```

ENVIRONMENT VARIABLES
---------------------

MDM Service:
- POWERFLEX_MDM_API_PORT (default: 8001)
- POWERFLEX_MDM_BIND_HOST (default: 0.0.0.0)

MGMT Service:
- POWERFLEX_MDM_BASE_URL (default: http://127.0.0.1:8001)
- POWERFLEX_GUI_PORT (default: 5000)
- POWERFLEX_GUI_BIND_HOST (default: 0.0.0.0)

SDS Service:
- MDM_URL (default: http://127.0.0.1:8001)

SDC Service:
- POWERFLEX_MDM_ADDRESS (default: 127.0.0.1)
- POWERFLEX_MDM_PORT (default: 8001)

DEVELOPMENT WORKFLOW
--------------------

1. Start MDM in background terminal
2. Start MGMT in separate terminal (optional)
3. Run integration tests
4. Make changes to code
5. Restart affected services
6. Rerun tests

For active development:
```powershell
# Terminal 1: MDM
.venv\Scripts\python.exe scripts\run_mdm_service.py

# Terminal 2: Tests
.venv\Scripts\python.exe scripts\test_phase10_integration.py
# Make changes, then Ctrl+C and rerun
```

CURRENT ARCHITECTURE STATUS
----------------------------

✅ Working:
- MDM service from mdm/ package
- MGMT service from mgmt/ package
- Volume creation (was Phase 10 blocker!)
- Full topology creation (PD → SDS → Pool → SDC)
- Health monitoring (partial)
- Discovery & registration
- Token authority endpoints

⚠️  Partial:
- MGMT dashboard (500 errors on some endpoints)
- Volume IO operations (write validation issues)
- Health components endpoint (500 error)

❌ Not Yet Implemented:
- Physical SDS service deployment
- Physical SDC service deployment
- NBD device testing
- Multi-VM deployment

NEXT STEPS
----------

To reach 90%+ pass rate:
1. Fix /health/components endpoint (mdm/api/health.py)
2. Fix volume write validation (mdm/api/volume.py)
3. Implement /metrics/cluster endpoint
4. Fix data integrity test authentication

DOCUMENTATION
-------------

- Architecture: docs/REFORM_PLAN.md
- Phase 10.5 Success: docs/PHASE10.5_ARCHITECTURE_ACTIVATION_SUCCESS.md
- Phase 10 Summary: docs/PHASE10_SUMMARY.md
- This Guide: docs/QUICKSTART.md

HELPFUL COMMANDS
----------------

# Check all services
netstat -ano | findstr "8001 5000 9701 9702 8003"

# View MDM logs
.venv\Scripts\python.exe -c "import requests; print(requests.get('http://127.0.0.1:8001/').json())"

# View health status
.venv\Scripts\python.exe -c "import requests, json; print(json.dumps(requests.get('http://127.0.0.1:8001/health').json(), indent=2))"

# Count volumes in DB
.venv\Scripts\python.exe -c "import sqlite3; conn=sqlite3.connect('powerflex.db'); cur=conn.cursor(); cur.execute('SELECT COUNT(*) FROM volumes'); print(f'Volumes: {cur.fetchone()[0]}'); conn.close()"

# Check disk space
Get-PSDrive C | Select-Object @{Name="Free(GB)";Expression={[math]::Round($_.Free/1GB,2)}}, @{Name="Used(GB)";Expression={[math]::Round($_.Used/1GB,2)}}

---
Last Updated: 2026-02-13
Architecture: Phase 1-9 activated ✅
Test Pass Rate: 62.5% (15/24)
"""