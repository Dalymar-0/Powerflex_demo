# PowerFlex Simulator - Current State Baseline (Archived)

> Archived reference from simulator phase. For active split-service architecture (`MDM`/`SDS`/`SDC`), use `docs/ARCHITECTURE_RESHAPE.md` and `PLANS.md`.

**Last Updated:** 2026-02-12
**Purpose:** authoritative as-is snapshot before starting new development

---

## 1) Current Repository Structure (Actual)

### Top-level
- `app/`
- `templates/`
- `flask_gui.py`
- `README.md`
- `PLANS.md`
- `PHASES.md` (this file)
- `powerflex.db`
- `.vscode/tasks.json`

### Application modules in `app/`
- Core: `main.py`, `models.py`, `database.py`, `logic.py`, `scenario_a.py`
- API routers: `api/pd.py`, `api/pool.py`, `api/sds.py`, `api/sdc.py`, `api/volume.py`, `api/rebuild.py`, `api/metrics.py`
- Services: `services/storage_engine.py`, `services/volume_manager.py`, `services/rebuild_engine.py`, `services/io_simulator.py`, `services/io_worker.py`

### Present / Missing by design
- Present: FastAPI + SQLAlchemy + Flask GUI simulator stack
- Missing: `tests/` suite, CLI module (`app/cli.py`), distributed socket-role modules (`metadata_manager.py`, `sds_node.py`, `sdc_client.py`)

---

## 2) Runtime API Surface (Observed from OpenAPI)

**Total routes:** 24

- Root: `GET /`
- PD: `POST /pd/create`, `GET /pd/list`, `DELETE /pd/{pd_id}`
- Pool: `POST /pool/create`, `GET /pool/list`, `GET /pool/{pool_id}/health`
- SDS: `POST /sds/add`, `GET /sds/list`, `POST /sds/{sds_id}/fail`, `POST /sds/{sds_id}/recover`
- SDC: `POST /sdc/add`, `GET /sdc/list`
- Volume: `POST /vol/create`, `POST /vol/map`, `POST /vol/unmap`, `POST /vol/extend`, `GET /vol/list`, `DELETE /vol/{volume_id}`
- Rebuild: `POST /rebuild/start/{pool_id}`, `GET /rebuild/status/{pool_id}`
- Metrics: `GET /metrics/pool/{pool_id}`, `GET /metrics/sds/{sds_id}`, `GET /metrics/volume/{volume_id}`

---

## 3) Verified Working Capabilities (as of 2026-02-12)

Validated with live API smoke tests:
- PD create + duplicate conflict handling (`409`)
- SDS add/list
- Pool create/list/health
- SDC add/list
- Volume create/map/unmap/extend/delete
- Metrics volume/pool/sds endpoints
- Rebuild status endpoint reachable
- Flask GUI now checks API success/failure before showing success messages

Recent alignment fixes already applied:
- Field-name drift fixed (`protection_domain_id`, `total_capacity_gb`, `provisioning`)
- API error normalization improved (expected conflicts now not raw 500s)
- GUI payloads aligned to API contracts
- `scenario_a.py` updated for rerunnable unique names

---

## 4) What Is Not Implemented Yet (Gap List)

### Phase-6 API completeness gaps
- Missing detail endpoints:
  - `GET /pd/{id}`
  - `GET /pool/{id}`
  - `GET /sds/{id}`
  - `GET /sdc/{id}`
  - `GET /vol/{id}`
- Missing metrics endpoints:
  - `GET /metrics/sdc/{id}`
  - `GET /metrics/timeline`
- Missing rebuild action:
  - `POST /rebuild/cancel/{pool_id}` (optional in old plan, still absent)

### Product-direction gaps (distributed demo target)
- No socket protocol implementation between role processes
- No metadata-manager service process
- No SDS block-file server process
- No SDC remote IO client process
- No multi-VM orchestration/runbook

### Capability-model gaps (new primary design)
- No unified node identity/registration model with capability advertisement (`SDS`, `SDC`, `MDM`)
- No cluster membership table keyed by node + capability set
- No capability-aware scheduling (e.g., place replicas only on `SDS` capable nodes)

### Engineering gaps
- No test suite (`tests/` missing)
- No CLI (`scli`) implementation
- No Prometheus exporter and Grafana dashboard setup

---

## 5) Readiness Assessment

### Current maturity
- **Local simulator/API maturity:** Medium (usable demo for single-node logical flows)
- **Distributed VM demo maturity:** Low (architecture defined, runtime components not built)

### What we can confidently demo now
- CRUD lifecycle simulation via API/GUI
- Basic mapping/unmapping semantics
- Simulated node failure state transitions and rebuild-status checks

### What we cannot demo yet
- True VM-to-VM socket IO path with SDS-owned block files
- SDC remote data-path behavior over network

---

## 6) Required Pre-Development Gate (Completed)

This baseline fulfills the "redefine current structure and what exists now" gate.

Before implementing new major features, all work should reference this file for:
1. Existing modules and boundaries
2. Verified capabilities vs assumptions
3. Explicit missing components for distributed target

---

## 7) Next Build Order (after this baseline)

1. Complete missing Phase-6 endpoints (detail + metrics gaps)
2. Add minimal integration tests for current API behavior
3. Build distributed node + capability skeletons:
  - `app/distributed/cluster_node.py`
  - `app/distributed/capability_mdm.py`
  - `app/distributed/capability_sds.py`
  - `app/distributed/capability_sdc.py`
4. Implement first end-to-end socket write/read with file-backed SDS blocks
5. Add multi-VM runbook and scripted demo scenario

---

## 8) Capability Milestones (Per-Node)

### Milestone C1 - Capability registration
- Node starts with config like: `capabilities=["SDS","MDM"]` or `["SDC"]`
- Node registers into cluster metadata with heartbeat
- Cluster view endpoint returns all nodes + capabilities

### Milestone C2 - Capability-aware control plane
- Volume placement chooses only `SDS` capable nodes
- Metadata operations require `MDM` capable node availability
- Mapping requires target consumer node has `SDC` capability

### Milestone C3 - First distributed IO
- `SDC` capable node performs write/read over socket
- Data served from file-backed blocks on `SDS` capable nodes
- Metadata lookup resolved through `MDM` capability path

### Milestone C4 - Failure and rebuild by capability
- Failure of `SDS` capable node marks degraded state
- Rebuild targets another eligible `SDS` capable node
- Health returns to OK after replica restoration
