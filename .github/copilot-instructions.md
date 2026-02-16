# PowerFlex Demo — Copilot Instructions

## Project Overview

**PowerFlex Demo** is a Python-based distributed storage system demonstrating Dell PowerFlex/ScaleIO architecture patterns. The project implements a modular, component-based design with 4 independent services (MDM, SDS, SDC, MGMT) that can run on separate VMs or co-locate on a single host.

---

## 📋 Master Architecture Plan

**ALWAYS read `docs/REFORM_PLAN.md` before making changes.**

The REFORM_PLAN.md is the **authoritative source of truth** for:
- Component architecture (MDM, SDS, SDC, MGMT)
- Port maps and communication protocols
- IO authorization token flow
- Database schemas (5 databases, 45 tables)
- NBD-like device protocol
- Component discovery & registration
- Threading & concurrency model
- Implementation phases (1-10)
- Deployment automation

If the user asks about architecture, design decisions, or implementation strategy, **refer to REFORM_PLAN.md first**.

---

## 🛠 Tech Stack

### Core Dependencies (already installed in `.venv`)

```python
# Web frameworks
fastapi==0.128.5          # HTTP APIs for MDM, SDS, SDC (control/mgmt planes)
uvicorn==0.40.0           # ASGI server for FastAPI apps
flask==3.1.2              # MGMT GUI (session-based HTML dashboard)

# Database & ORM
sqlalchemy==2.0.46        # ORM for all 5 SQLite databases
sqlite3 (stdlib)          # 5 databases: powerflex.db, sds_local.db (per node), 
                          # sdc_chunks.db (per node), mgmt.db

# Data validation
pydantic==2.12.5          # Request/response models, token schemas

# HTTP client
requests==2.32.5          # Heartbeats, token fetch, discovery, MGMT polling

# Standard library (no extra pip installs needed)
socket, threading         # TCP servers (SDS data port, SDC NBD device port)
hmac, hashlib             # IO token signing (HMAC-SHA256)
uuid                      # Token IDs (uuid4)
json                      # Socket protocol (newline-delimited JSON frames)
base64                    # Binary data encoding for IO payloads
datetime                  # Token expiry, timestamps
logging                   # Per-component loggers
queue                     # Background task queues
os, pathlib               # File operations, config
```

**Python version:** 3.13+
**Command prefix:** `C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe`

### NO new dependencies required
The entire architecture runs on what's already installed. Do NOT suggest adding:
- `asyncio` (we use threading, not async/await)
- `celery` (overkill, use threading.Thread)
- `redis` (no external cache, SQLite + in-memory dicts)
- `jwt` / `cryptography` (stdlib hmac is sufficient)
- `docker` (runs natively, no containers)

---

## 🏗 Current Project Structure

```
Powerflex_demo/
├── app/                          ← Current code (to be refactored per REFORM_PLAN)
│   ├── models.py                 ← SQLAlchemy models (central DB)
│   ├── database.py               ← DB init + migrations
│   ├── config.py                 ← Env-backed config
│   ├── logic.py                  ← Service integration layer
│   ├── startup_profile.py        ← Boot-time role/port validation
│   ├── main.py                   ← MDM FastAPI app (legacy)
│   ├── mdm_service.py            ← MDM service entrypoint
│   ├── sdc_service.py            ← SDC service entrypoint
│   ├── api/                      ← REST API modules
│   │   ├── volume.py             ← Volume CRUD + IO (needs refactor)
│   │   ├── pd.py, pool.py, sds.py, sdc.py, cluster.py, etc.
│   ├── services/                 ← Business logic
│   │   ├── storage_engine.py
│   │   ├── volume_manager.py
│   │   ├── rebuild_engine.py
│   └── distributed/              ← Network components
│       ├── sds_socket_server.py  ← SDS data handler (TCP)
│       ├── sdc_socket_client.py  ← SDC→SDS client
│       ├── capability_sdc.py     ← SDC runtime
│       └── socket_protocol.py    ← Framed JSON protocol
├── flask_gui.py                  ← MGMT GUI (Flask)
├── scripts/                      ← Launch + utility scripts
│   ├── run_mdm_service.py
│   ├── run_sds_service.py
│   ├── run_sdc_service.py
│   ├── run_gui_service.py
│   └── ...
├── docs/
│   └── REFORM_PLAN.md            ← **THE MASTER PLAN** (read this first!)
├── .venv/                        ← Python virtual environment
├── powerflex.db                  ← Central MDM database
├── requirements.txt
└── README.md
```

---

## 🎯 Target Architecture (from REFORM_PLAN.md Phase 1)

After Phase 1 restructure, the project will look like:

```
Powerflex_demo/
├── mdm/                    ← MDM package (runs standalone on its VM)
│   ├── service.py          ← FastAPI app
│   ├── models.py           ← powerflex.db models
│   ├── token_authority.py  ← IO token signing
│   ├── discovery.py        ← Registration API
│   └── api/ (pd, pool, sds, sdc, volume, cluster, metrics, rebuild, token, heartbeat, discovery)
├── sds/                    ← SDS package (runs standalone on its VM)
│   ├── service.py          ← Multi-listener launcher
│   ├── data_handler.py     ← TCP socket server (port 9700+n)
│   ├── control_app.py      ← FastAPI control (port 9100+n)
│   ├── mgmt_app.py         ← FastAPI mgmt (port 9200+n)
│   ├── models.py           ← sds_local.db models
│   ├── token_verifier.py   ← Verify IO tokens
│   └── ...
├── sdc/                    ← SDC package (runs standalone on its VM)
│   ├── service.py
│   ├── nbd_server.py       ← NBD-like device server (port 8005)
│   ├── data_handler.py     ← IO execution to SDS
│   ├── control_app.py      ← FastAPI control (port 8003)
│   ├── mgmt_app.py         ← FastAPI mgmt (port 8004)
│   ├── models.py           ← sdc_chunks.db models
│   └── token_manager.py    ← Request tokens from MDM
├── mgmt/                   ← MGMT package (runs standalone on its VM)
│   ├── service.py          ← Flask GUI
│   ├── models.py           ← mgmt.db models (users, sessions, alerts, monitoring)
│   ├── auth.py
│   ├── monitor.py          ← Poll all component mgmt ports
│   ├── alerts.py
│   └── templates/
├── shared/                 ← Shared utilities (installed on every VM)
│   ├── socket_protocol.py
│   ├── token_utils.py
│   ├── discovery_client.py
│   └── heartbeat_client.py
└── scripts/
    ├── deploy_cluster.py   ← Master deployment orchestrator
    ├── run_mdm.py, run_sds.py, run_sdc.py, run_mgmt.py
    └── ...
```

---

## 🔑 Key Architecture Principles

1. **MDM is the only writer to `powerflex.db`.**  
   No other component touches the central database.

2. **Every IO transaction requires a token.**  
   SDC→MDM (get token) → SDC→SDS (execute with token) → SDS→MDM (ACK transaction).

3. **MGMT has its own database (`mgmt.db`).**  
   Separate from powerflex.db. MGMT polls all components for health/stats.

4. **Each component is independently deployable.**  
   No shared DB files, no shared memory. All communication over TCP/HTTP.

5. **MDM is the discovery registry.**  
   All components register with MDM on boot via HTTP POST to `/discovery/register`.

6. **IO execution belongs in SDC only.**  
   MDM generates plans + tokens. SDS stores bytes. SDC orchestrates the IO.

7. **NBD-like protocol for VM data serving.**  
   SDC port 8005 exposes volumes to apps/VMs as block devices.

8. **Token signing uses stdlib HMAC-SHA256.**  
   No external crypto libraries. Shared secret distributed during registration.

9. **Multi-listener pattern for SDS/SDC.**  
   Each runs 3 HTTP/TCP servers in separate threads (data, control, mgmt).

10. **Co-location is supported.**  
    Same codebase runs on 4 VMs or 1 VM with different ports.

---

## 🚀 Development Workflow

### Starting the system (current monolithic mode)

```powershell
# 1. Stop any existing MDM process
$conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }

# 2. Start MDM API
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# 3. Start GUI (separate terminal)
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe flask_gui.py

# 4. Start SDS socket server (if testing data plane)
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_sds_socket_node.py --host 127.0.0.1 --port 9700 --storage-root ./vm_storage/socket_sds
```

### Running component services (when available)

```powershell
# MDM
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_mdm_service.py

# SDS
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_sds_service.py

# SDC
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_sdc_service.py

# MGMT
C:/Users/uid1944/Powerflex_demo/.venv/Scripts/python.exe scripts/run_gui_service.py
```

---

## 📐 Implementation Phases (from REFORM_PLAN.md)

When making changes, follow the phase sequence:

**Phase 1** — Restructure code into `mdm/`, `sds/`, `sdc/`, `mgmt/`, `shared/` packages  
**Phase 2** — Discovery & registration (MDM discovery API, cluster_secret)  
**Phase 3** — Separate MGMT database (`mgmt.db` with users, sessions, alerts)  
**Phase 4** — IO authorization tokens (sign, verify, ACK chain)  
**Phase 5** — SDS multi-listener service (data + control + mgmt)  
**Phase 6** — SDC NBD device server + token management  
**Phase 7** — MDM heartbeat receiver + health monitor  
**Phase 8** — IO path separation (remove IO execution from MDM)  
**Phase 9** — MGMT GUI + alerts + monitoring  
**Phase 10** — Integration & end-to-end testing  

**Current status:** Pre-Phase 1 (monolithic `app/` structure still in place)

---

## 🧪 Testing Patterns

### API smoke test
```python
import requests, base64, time

MDM = "http://127.0.0.1:8001"
t = str(int(time.time()))

# Create topology
pd = requests.post(f"{MDM}/pd/create", json={"name": f"PD_{t}"}).json()
sds1 = requests.post(f"{MDM}/sds/add", json={"name": f"SDS1_{t}", "total_capacity_gb": 256, "devices": "blk0", "protection_domain_id": pd["id"]}).json()
pool = requests.post(f"{MDM}/pool/create", json={"name": f"POOL_{t}", "pd_id": pd["id"], "protection_policy": "two_copies", "total_capacity_gb": 256}).json()
sdc = requests.post(f"{MDM}/sdc/add", json={"name": f"SDC_{t}"}).json()
vol = requests.post(f"{MDM}/vol/create", json={"name": f"VOL_{t}", "size_gb": 1, "provisioning": "thin", "pool_id": pool["id"]}).json()

# Map + IO
requests.post(f"{MDM}/vol/map", params={"volume_id": vol["id"], "sdc_id": sdc["id"], "access_mode": "readWrite"})
payload = base64.b64encode(b"test-data").decode()
requests.post(f"{MDM}/vol/{vol['id']}/io/write", json={"sdc_id": sdc["id"], "offset_bytes": 0, "data_b64": payload})
read_resp = requests.post(f"{MDM}/vol/{vol['id']}/io/read", json={"sdc_id": sdc["id"], "offset_bytes": 0, "length_bytes": 9}).json()
assert base64.b64decode(read_resp["data_b64"]) == b"test-data"
```

---

## 💡 Common Tasks

### When the user asks to add a new API endpoint:
1. Check REFORM_PLAN.md — which component owns this operation?
2. Add to appropriate `api/` module (mdm, sds, sdc, or mgmt)
3. Update models if DB changes needed
4. Add validation with Pydantic models
5. Test with requests snippet

### When implementing IO token auth:
1. Read REFORM_PLAN.md §3 (IO Authorization Token Protocol)
2. Use `hmac` + `hashlib` from stdlib (no external deps)
3. Token structure defined in REFORM_PLAN.md §3.2
4. Verification logic in REFORM_PLAN.md §3.3

### When adding a background thread:
```python
import threading, time

def worker_loop():
    while True:
        # do work
        time.sleep(10)

thread = threading.Thread(target=worker_loop, daemon=True)
thread.start()
```

### When adding a new database table:
1. Check REFORM_PLAN.md §6 for existing schema
2. Add SQLAlchemy model in appropriate `models.py` (mdm, sds, sdc, or mgmt)
3. Add migration in `database.py` additive migration pattern
4. Never drop/recreate existing tables (additive only)

---

## ⚠️ Critical Rules

- **NEVER break existing IO flow** — Volume write/read must continue to work
- **NEVER modify `powerflex.db` schema without migration** — Use additive migrations only
- **ALWAYS check REFORM_PLAN.md before architectural changes** — It's the single source of truth
- **NEVER add new pip dependencies without approval** — Stdlib-first approach
- **ALWAYS use absolute file paths in tools** — `C:/Users/uid1944/Powerflex_demo/...`
- **NEVER use async/await** — This project uses threading, not asyncio
- **ALWAYS verify port availability before starting services** — Check for conflicts

---

## 📞 Port Reference

```
8001  — MDM API (FastAPI)
9100+n — SDS Control (HTTP)
9200+n — SDS Management (HTTP)
9700+n — SDS Data (TCP socket)
8003  — SDC Control (HTTP)
8004  — SDC Management (HTTP)
8005  — SDC NBD Device (TCP socket)
5000  — MGMT GUI (Flask)
```

---

## 🔧 Troubleshooting

**Port 8001 already in use:**
```powershell
$conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }
```

**DB locked errors:**  
Use `scoped_session` with `check_same_thread=False` for SQLite threading.

**Import errors after restructure:**  
Each component package is independent. No cross-imports between `mdm/`, `sds/`, `sdc/`, `mgmt/`.

**IO path not working:**  
Check that SDS socket server is running on the expected data_port (9700+n).

---

## 📚 Key Files to Read

1. **`docs/REFORM_PLAN.md`** — Architecture bible (read first!)
2. **`app/models.py`** — Current DB schema
3. **`app/api/volume.py`** — IO plan generation (complex, needs refactor per Phase 8)
4. **`app/distributed/sds_socket_server.py`** — Data plane reference implementation
5. **`app/config.py`** — Environment variable patterns

---

**When in doubt, read REFORM_PLAN.md. When still in doubt, ask the user.**
- Work through each checklist item systematically.
- Keep communication concise and focused.
- Follow development best practices.
- Never leave the homing terminal after using other terminals; always return to the homing terminal context.
