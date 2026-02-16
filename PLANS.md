# PowerFlex Simulator - Implementation Plans (Phases 0-10)

**Status**: Re-defined on 2026-02-12 for distributed multi-VM demo execution
**Created**: 2/9/2026
**Updated**: Ongoing

---

## 2026-02-12 Re-defined Plan (Supersedes old sequencing)

This section supersedes the original phase ordering and re-centers the project on the real goal:

**Goal**: a multi-VM PowerFlex-style demo where each node can run one or more capabilities (`SDS`, `SDC`, `MDM`), nodes communicate over sockets, SDS capabilities expose local block files, and SDC capabilities consume remote blocks via a metadata/control plane.

### Node Capability Model (Primary Design Rule)

Every VM/node is represented as a single cluster node with a capability set:
- `SDS` capability: owns and serves local storage blocks.
- `SDC` capability: issues IO requests for mapped volumes.
- `MDM` capability: participates in metadata/control responsibilities.

Allowed combinations for this demo include (but are not limited to):
- `SDS + MDM + SDC` (hyperconverged node)
- `SDS + MDM` (storage/control node)
- `SDC` only (compute client node)

Cluster logic must depend on **capabilities**, not machine type.

### Architecture Baseline We Will Emulate

PowerFlex concepts to emulate in this project:
- **SDC (client datapath initiator)**: sends IO to the correct SDS endpoint(s).
- **SDS (data server)**: owns local storage chunks/blocks and serves reads/writes.
- **MDM-like control plane**: owns metadata mapping of volume->chunks->replica locations and policy.
- **Network plane split**: control-plane traffic (`MDM`/cluster metadata + membership) uses control ports, while SDS IO uses dedicated data-plane ports.
- **Protection domain / pool policy**: defines placement and protection behavior.
- **Rebuild/failure flow**: when SDS fails, mark degraded and re-protect replicas.

### Feasibility Assessment (What is possible now)

#### ✅ Feasible in this repo immediately
1. Run separate Python node processes with capability flags.
2. Use TCP sockets (JSON-RPC style) between roles.
3. Use local files as SDS-backed block devices (e.g., 5 x 1GB sparse files per SDS VM).
4. Simulate volume mapping and read/write through metadata lookups and replica routing.
5. Demonstrate SDS failure, degraded reads, and rebuild to a new SDS.

#### ⚠️ Feasible with constraints
1. "Virtual drives" on guest OS:
   - True OS-mounted block devices are out of scope for pure Python.
   - We can provide file-level virtual volumes + CLI mount abstraction (path-based), not kernel block driver.
2. Strong consistency and distributed transactions:
   - We can implement practical demo-level consistency (single leader metadata manager + acknowledgements), not production-grade consensus initially.
3. MDM high-availability quorum:
   - Full multi-MDM consensus with tie-breaker arbitration is not yet implemented; current repo uses a single active control-plane authority model.

#### ❌ Not feasible in current scope (unless we add system-level components)
1. Native kernel block-driver integration equivalent to enterprise SDC.
2. Full production parity with Dell PowerFlex internals and performance characteristics.

### New Priority Phases (Execution Order)

#### Phase A - Stabilize local simulator (current codebase)
- Finish API correctness and service/model alignment.
- Complete missing detail endpoints.
- Make GUI strictly response-aware (no false success).
- Add basic integration tests for CRUD + failure/rebuild.

#### Phase B - Introduce node process + capability services (single machine first)
- `cluster_node.py`: common node runtime (identity, heartbeat, capability advertisement).
- `capability_mdm.py`: metadata/control service attached when node has `MDM`.
- `capability_sds.py`: block-file storage service attached when node has `SDS`.
- `capability_sdc.py`: IO client service attached when node has `SDC`.
- Define versioned socket protocol for registration, metadata lookup, and IO operations.

#### Phase C - Block-file backed SDS storage
- Create SDS data root with sparse block files.
- Implement chunk/block addressing and replica placement.
- Add checksums and simple journaling for crash-safe demo behavior.

#### Phase D - Multi-VM deployment demo
- Run one node process per VM with capability configuration (single-role or multi-role).
- Configure peer discovery/registration and capability-aware membership.
- Enforce control-plane and data-plane port separation in bootstrap/runbook (SDS data socket endpoints resolved only from data-plane ports).
- Execute scripted scenario: create PD/pool/volume -> map -> IO -> fail SDS-capable node -> rebuild.

#### Phase E - Observability and operator UX
- Add timeline/event stream for socket-level operations.
- Expose metrics endpoints for role-level health.
- Extend GUI with distributed status panels (node state, replica state, rebuild queue).

### Deliverables for "Real Demo" milestone

1. Capability-configured VM nodes (single-role and multi-role combinations).
2. SDS node with local 1GB block files (configurable count).
3. End-to-end read/write command from SDC to SDS via metadata lookup.
4. Failure/rebuild scenario script with observable output.
5. Demo runbook with exact startup order and verification commands.

### Definition of Done (for demo objective)

The project is "demo-ready" when:
1. A node with `SDC` capability on VM-A can write/read a mapped volume backed by nodes with `SDS` capability on VM-B/VM-C.
2. At least one node with `MDM` capability correctly tracks placement/mapping metadata.
3. Stopping an `SDS`-capable node degrades but does not lose data for protected volumes.
4. Rebuild restores replica count on remaining/added `SDS`-capable nodes and pool health returns to OK.
5. Demo script runs reproducibly across mixed capability combinations without manual DB surgery.

#### Current Assessment (2026-02-12)

**Current Phase Position:** Late **Phase B** / Early **Phase C**

- [x] DoD #2: `MDM` capability is present and used for metadata/control-plane checks.
- [~] DoD #1: End-to-end SDC↔SDS read/write exists on single-machine topology; full VM-A/VM-B/VM-C validation still pending.
- [~] DoD #3: Failure/degraded paths exist, but repeatable no-data-loss proof across distributed runs still pending.
- [ ] DoD #4: Full replica-restoration proof (including pool health return to OK) is not yet locked as a repeatable demo run.
- [~] DoD #5: Bootstrap/demo scripts exist, but reproducibility across mixed capability combinations needs final scripted validation.

Legend: `[x]` complete, `[~]` partial/in-progress, `[ ]` pending.

#### Exit Criteria: Phase C → Phase D

- [ ] Scripted validation run (`scripts/validate_demo_ready.py`) completes without manual DB edits.
- [ ] DoD #1 evidence captured: successful mapped volume write/read roundtrip in report output.
- [ ] DoD #3 evidence captured: read still succeeds after failing one `SDS` node.
- [ ] DoD #4 evidence captured: rebuild start/status output recorded and reviewed.
- [ ] Runbook inputs finalized for VM mapping (which node/VM hosts each capability role).

---

## Executive Summary

This document outlines the complete 10-phase implementation of a PowerFlex Simulator that faithfully reproduces Dell PowerFlex architecture, data distribution rules, failure modes, and recovery mechanisms.

**Key Objectives:**
- Simulate storage distribution algorithms (TWO_COPIES, ERASURE_CODING)
- Implement node failure detection and automatic rebuild
- Track IO metrics (IOPS, bandwidth, latency) per volume/SDC/SDS
- Provide REST API, CLI tool, and web GUI
- Enable comprehensive monitoring via Prometheus/Grafana
- Demonstrate realistic failure scenarios and recovery

---

## PHASE 0: Rules Definition ✅ COMPLETE

Documented fundamental PowerFlex behaviors:
- **Replication**: 2 copies on different SDS nodes; reads from fastest replica
- **Protection**: No two replicas on same SDS, no two on same FaultSet if possible
- **Capacity**: Thick volumes reserve space; thin volumes use-on-write
- **Failure**: Any SDS failure triggers degraded state; rebuild automatically starts
- **Access Control**: Volume mapped to SDC = read/write access; distinct access modes
- **Metrics**: IOPS, bandwidth, latency tracked per resource

---

## PHASE 1: Data Model Design ✅ COMPLETE

**Models Implemented:**
- `ProtectionDomain` - Top-level container
- `StoragePool` - Capacity + health tracking
- `SDSNode` - Physical storage node
- `SDCClient` - Host accessing volumes
- `Volume` - Logical storage unit
- `VolumeMapping` - Volume → SDC access
- `Chunk` - 4MB logical unit
- `Replica` - Copy of chunk on SDS
- `Snapshot` - Point-in-time volume copy
- `FaultSet` - Failure domain isolation
- `RebuildJob` - Track rebuild operations
- `EventLog` - Audit trail (13 event types)

**Enhancements:**
- DateTime tracking on all entities
- Metrics fields: IOPS, bandwidth, latency
- Rebuild state machine + progress tracking
- EventType enums instead of strings
- AccessMode enums vs string

---

## PHASE 2: Storage Engine Enhancement

**Goal**: Core storage logic that enforces PowerFlex rules

**Tasks:**
1. **Chunk-Replica Distribution Algorithm**
   - Allocate chunks to volume in order (offset 0, 4MB, 8MB, ...)
   - Distribute replicas across different SDS nodes
   - Enforce: no two replicas on same SDS
   - Prefer: different FaultSets (racks) if possible
   - File: `app/logic.py` → `class StorageEngine`

2. **Capacity Management**
   - Thin volumes: allocate only used_capacity (consumed on write)
   - Thick volumes: reserve FULL size immediately
   - Prevent allocation if pool would exceed total_capacity
   - Track reserved_capacity_gb vs used_capacity_gb
   - File: `app/logic.py` → `allocate_capacity()`

3. **Consistency Validation**
   - No volume without pool
   - No chunk without replicas (min 2 for TWO_COPIES)
   - No replica on failed SDS (state = DOWN)
   - No volume mapped while being deleted
   - File: `app/logic.py` → `validate_*()`

**Implementation Details:**
```python
# Example: allocate_chunks(volume, protection_policy)
# Input: Volume object, pool's protection_policy
# Logic:
#   1. Calculate chunk count = ceil(volume.size_gb * 256)  # 256 chunks/GB (4MB each)
#   2. For each chunk idx:
#      - Find N available SDS nodes (N=2 for TWO_COPIES, N=3 for EC)
#      - Prefer different FaultSets
#      - Create Chunk + N Replica records
#   3. Update pool.used_capacity_gb += volume.size_gb
#   Return: Total chunks created
```

---

## PHASE 3: Volume Operations Complete

**Goal**: Full CRUD lifecycle for volumes with state transitions

**Tasks:**
1. **Volume Creation** (`/vol/create`)
   - Parse: name, size_gb, provisioning (thin/thick), pool_id
   - Validate: pool exists, sufficient capacity
   - Allocate chunks via StorageEngine
   - State: AVAILABLE immediately
   - Event: VOLUME_CREATE logged

2. **Volume Mapping** (`/vol/map`)
   - Parse: volume_id, sdc_id, access_mode
   - Validate: volume state != DEGRADED, SDC exists
   - Create VolumeMapping record
   - Increment volume.mapping_count
   - State: → IN_USE if first mapping
   - Event: VOLUME_MAP logged

3. **Volume Unmapping** (`/vol/unmap`)
   - Remove VolumeMapping record
   - Decrement volume.mapping_count
   - State: → AVAILABLE if no mappings left
   - Event: VOLUME_UNMAP logged

4. **Volume Extension** (`/vol/extend`)
   - Parse: volume_id, additional_gb
   - Validate: pool has capacity, volume exists
   - Allocate additional chunks
   - Update volume.size_gb
   - Event: VOLUME_EXTEND logged

5. **Volume Deletion** (`/vol/delete`)
   - Validate: mapping_count == 0 (no SDCs mapped)
   - Delete all chunks, replicas
   - Update pool.used_capacity_gb
   - State: DELETING → removed from DB
   - Event: VOLUME_DELETE logged

**Implementation File:** `app/logic.py` → `class VolumeManager`

---

## PHASE 4: IO Simulation Integration

**Goal**: Simulate realistic workloads and track metrics

**Tasks:**
1. **IOSimulator Class** (`app/services/io_simulator.py`)
   - For each SDC with mapped volumes:
     - Generate writes: random chunks, update used_capacity_gb
     - Generate reads: select fastest replica (lowest latency)
     - Simulate latency: random 5-50ms per IO
   - Update metrics: current_iops, current_bandwidth_mbps

2. **Replica Selection**
   ```python
   def get_best_replica(chunk_id) -> Replica:
       # Read from replica with lowest average_latency_ms
       # If all unavailable, return None (degraded read)
   ```

3. **Metrics Aggregation** (per 5-second tick)
   - Volume: sum read/write IOPS from mapped SDCs
   - Pool: sum all volume IOPS
   - SDS: sum all replica accesses
   - SDC: sum all volume accesses
   - Update averages: latency_ms = moving average of last 10 samples

4. **Background Worker Thread**
   - Start on app init: `BackgroundIOWorker()`
   - Every 100ms: generate random IO operations
   - Every 5s: aggregate metrics
   - Every 60s: log metrics to EventLog
   - File: `app/services/io_worker.py`

**Expected Flows:**
- Write to volume: 1) choose chunk, 2) increment volume.used_capacity_gb, 3) update all replica SDS metrics
- Read from volume: 1) choose chunk, 2) select best replica, 3) add to SDS.current_iops
- Bandwidth calc: IOPS × avg_io_size (assume 64KB IO) = MB/s

---

## PHASE 5: Failure & Rebuild Orchestration

**Goal**: Simulate node failures and automatic rebuild recovery

**Tasks:**
1. **Node Failure Simulation** (`/sds/{id}/fail`)
   - Set SDSNode.state = DOWN
   - Find all replicas on this SDS
   - Set Replica.is_available = False
   - For each affected chunk: set Chunk.is_degraded = True
   - Find affected pools: set Pool.health = DEGRADED
   - Event: SDS_STATE_CHANGE logged
   - Trigger auto-rebuild start

2. **Rebuild Orchestration** (`/rebuild/start/{pool_id}`)
   - Find all degraded chunks in pool
   - Create RebuildJob record
   - For each degraded replica:
     - Pick healthy SDS with capacity
     - Create new Replica record with is_rebuilding=True
     - Queue copy operation: source → target
   - Set Pool.rebuild_state = IN_PROGRESS

3. **Rebuild Rate Limiting**
   ```python
   # Token bucket: rebuild_rate_limit_mbps (e.g., 100 MB/s)
   # Rebuild worker:
   #   - Consume tokens for each MB copied
   #   - Stall if no tokens available (wait for refill)
   #   - Track: bytes_rebuilt / total_bytes_to_rebuild = progress%
   ```

4. **Rebuild Progress Tracking**
   - Poll rebuild job every 1 second
   - Calculate: progress_percent = bytes_rebuilt / total_bytes × 100
   - Estimate: time_remaining = (total - rebuilt) / current_rate_mbps
   - Update: RebuildJob.progress_percent, estimated_time_remaining_seconds
   - Event: Every 10% progress logged

5. **Rebuild Completion**
   - All replicas rebuilt and confirmed
   - Set Chunk.is_degraded = False for all chunks
   - Set Replica.is_rebuilding = False
   - Set Pool.rebuild_state = COMPLETED
   - Set Pool.health = OK (if all pools OK)
   - Event: REBUILD_COMPLETE logged

6. **Node Recovery** (`/sds/{id}/recover`)
   - Set SDSNode.state = UP
   - Check if any chunks lost (degraded with no available replicas)
   - If all replicas present: chunks auto-heal (is_degraded = False)
   - Update pool health
   - Event: SDS_STATE_CHANGE logged

**Implementation File:** `app/services/rebuild_engine.py`

---

## PHASE 6: REST API Endpoints

**Goal**: Expose all simulator operations via FastAPI

**Endpoints by Resource:**

### Protection Domain
- `POST /pd/create` → Create PD
- `GET /pd/list` → List all PDs
- `GET /pd/{id}` → Get PD detail + pool/node summary
- `DELETE /pd/{id}` → Delete PD (cascade)

### Storage Pool
- `POST /pool/create` → Create pool
- `GET /pool/list` → List pools
- `GET /pool/{id}` → Get pool detail + health status
- `GET /pool/{id}/health` → Detailed health metrics
- `GET /pool/{id}/metrics` → IOPS, bandwidth, latency

### SDS Node
- `POST /sds/add` → Add SDS to PD
- `GET /sds/list` → List SDS nodes
- `GET /sds/{id}` → Node detail + capacity + state
- `POST /sds/{id}/fail` → Simulate failure
- `POST /sds/{id}/recover` → Recover node
- `GET /sds/{id}/metrics` → Node IOPS, bandwidth, latency

### SDC Client
- `POST /sdc/add` → Add SDC
- `GET /sdc/list` → List SDCs
- `GET /sdc/{id}` → SDC detail + mapped volumes
- `GET /sdc/{id}/metrics` → SDC IOPS, bandwidth, latency

### Volume
- `POST /vol/create` → Create volume
- `GET /vol/list` → List volumes
- `GET /vol/{id}` → Volume detail
- `POST /vol/map` → Map to SDC
- `POST /vol/unmap` → Unmap from SDC
- `POST /vol/extend` → Extend size
- `DELETE /vol/{id}` → Delete (if unmapped)
- `GET /vol/{id}/metrics` → Volume IOPS, bandwidth, latency

### Rebuild
- `POST /rebuild/start/{pool_id}` → Start rebuild
- `GET /rebuild/status/{pool_id}` → Rebuild progress
- `POST /rebuild/cancel/{pool_id}` → Cancel rebuild (optional)

### Metrics
- `GET /metrics/pool/{pool_id}` → Pool aggregated metrics
- `GET /metrics/sds/{sds_id}` → SDS metrics
- `GET /metrics/volume/{volume_id}` → Volume metrics
- `GET /metrics/sdc/{sdc_id}` → SDC metrics
- `GET /metrics/timeline` → Historical metrics (last 60 samples)

**Implementation Files:**
- `app/api/pd.py`, `app/api/pool.py`, `app/api/sds.py`, `app/api/sdc.py`
- `app/api/volume.py`, `app/api/rebuild.py`, `app/api/metrics.py`
- Update all to use new models + StorageEngine logic

---

## PHASE 7: CLI Tool (scli)

**Goal**: PowerFlex admin simulation via command-line interface

**Tool**: Click framework for ergonomic CLI

**Commands:**

```
# Protection Domain
pflex pd create <name> [-d description]
pflex pd list
pflex pd show <id>
pflex pd delete <id>

# Storage Pool
pflex pool create <pd_id> <name> <capacity_gb> [--policy two_copies|ec]
pflex pool list [--pd <id>]
pflex pool show <id>
pflex pool health <id>
pflex pool metrics <id> [--interval 5]

# SDS Node
pflex sds add <pd_id> <name> <capacity_gb> [--ip <ip>] [--devices <list>]
pflex sds list [--pd <id>]
pflex sds show <id>
pflex sds fail <id> [--duration 30]
pflex sds recover <id>
pflex sds metrics <id>

# SDC Client
pflex sdc add <name> [--ip <ip>]
pflex sdc list
pflex sdc show <id>
pflex sdc metrics <id>

# Volume
pflex vol create <pool_id> <name> <size_gb> [--thin|--thick]
pflex vol list [--pool <id>]
pflex vol show <id>
pflex vol map <id> <sdc_id> [--ro]
pflex vol unmap <id> <sdc_id>
pflex vol extend <id> <additional_gb>
pflex vol delete <id>
pflex vol metrics <id>

# Rebuild
pflex rebuild status <pool_id>
pflex rebuild start <pool_id>
pflex rebuild cancel <pool_id>

# Scenarios
pflex scenario run <scenario>  # a, b, c, d
pflex scenario log            # Show last scenario output

# System
pflex system status           # Overall system health
pflex system reset            # Clear database
pflex system export <file>    # Export config to JSON
```

**Output Format:**
- Human-readable tables (ASCII art)
- JSON output option: `--json`
- Color-coded status: GREEN (OK), YELLOW (DEGRADED), RED (FAILED)

**Implementation:**
- `app/cli.py` - Main CLI entry point (Click app)
- `app/cli_commands/` - Subcommand modules
- Entry point: `python -m app.cli` or `scli` (if installed as package)

---

## PHASE 8: Prometheus + Grafana

**Goal**: Production-grade monitoring and dashboards

**Tasks:**

1. **Prometheus Metrics Exporter** (`app/prometheus.py`)
   - FastAPI route: `GET /prometheus/metrics`
   - Metrics exported:
     ```
     # Pool metrics
     powerflex_pool_total_capacity_gb{pool_id, pool_name}
     powerflex_pool_used_capacity_gb{pool_id, pool_name}
     powerflex_pool_free_capacity_gb{pool_id, pool_name}
     powerflex_pool_health{pool_id, state=ok|degraded|failed}
     powerflex_pool_rebuild_progress_percent{pool_id}
     powerflex_pool_iops{pool_id}
     powerflex_pool_bandwidth_mbps{pool_id}
     
     # Volume metrics
     powerflex_volume_size_gb{volume_id, volume_name, pool_id}
     powerflex_volume_state{volume_id, state=available|in_use|degraded}
     powerflex_volume_iops{volume_id}
     powerflex_volume_bandwidth_mbps{volume_id}
     powerflex_volume_latency_ms{volume_id}
     
     # SDS metrics
     powerflex_sds_capacity_gb{sds_id, sds_name}
     powerflex_sds_used_capacity_gb{sds_id}
     powerflex_sds_state{sds_id, state=up|down|degraded}
     powerflex_sds_iops{sds_id}
     powerflex_sds_bandwidth_mbps{sds_id}
     powerflex_sds_latency_ms{sds_id}
     ```

2. **Docker Compose Setup**
   ```yaml
   # docker-compose.yml
   services:
     powerflex-app:
       image: python:3.13
       ports: ["8000:8000"]
       volumes:
         - .:/app
       command: uvicorn app.main:app --host 0.0.0.0 --port 8000
     
     prometheus:
       image: prom/prometheus:latest
       ports: ["9090:9090"]
       volumes:
         - ./prometheus.yml:/etc/prometheus/prometheus.yml
       command: --config.file=/etc/prometheus/prometheus.yml
     
     grafana:
       image: grafana/grafana:latest
       ports: ["3000:3000"]
       environment:
         - GF_SECURITY_ADMIN_PASSWORD=admin
   ```

3. **Prometheus Configuration** (`prometheus.yml`)
   ```yaml
   scrape_configs:
     - job_name: 'powerflex'
       static_configs:
         - targets: ['localhost:8000']
       metrics_path: '/prometheus/metrics'
       scrape_interval: 5s
   ```

4. **Grafana Dashboard**
   - **Panel 1**: Pool Capacity (stacked bar: used/free)
   - **Panel 2**: Pool Health (status gauge + rebuild progress)
   - **Panel 3**: Top Volumes by IOPS (bar chart)
   - **Panel 4**: Volume Latency (line chart over time)
   - **Panel 5**: SDS Node States (table)
   - **Panel 6**: Rebuild Progress (gauge + status)
   - **Panel 7**: System IOPS (line chart, all volumes)
   - **Panel 8**: System Bandwidth (line chart, all volumes)
   - Export as JSON: `grafana_dashboard.json`

**Implementation File:** `app/prometheus.py`

---

## PHASE 9: Complete Demo Scenarios (B, C, D)

**Goal**: Realistic use-case demos showcasing simulator capabilities

### Scenario A: Basic Deployment ✅ (Already created)
- Create 1 PD, 1 Pool (2GB), 3 SDS nodes (1GB each)
- Create 1 volume (500MB, thin)
- Map to 1 SDC
- Verify: chunks distributed, 2 replicas per chunk, metrics available

### Scenario B: Failover & Rebuild
**Steps:**
1. Setup: PD + Pool (4GB) + 4 SDS nodes (2GB each)
2. Create: 2 volumes (1.5GB each, thick) + map to 2 SDCs
3. Start IO workload: 1000 IOPS on volume 1, 500 IOPS on volume 2
4. Fail SDS node 2 at T=10s
5. Observe: Pool → DEGRADED, volume state → DEGRADED
6. Monitor reads: should succeed (other replicas available)
7. Rebuild starts automatically
8. Monitor rebuild progress: 0% → 100%
9. On complete: Pool → OK, volumes → AVAILABLE
10. Result check: All chunks have 2 available replicas again

**Assertions:**
- No data loss (chunks > 0 available replicas at all times)
- Read success rate 100% during rebuild
- Rebuild rate ≈ pool's rebuild_rate_limit_mbps

### Scenario C: Multi-Host Mapping
**Steps:**
1. Setup: PD + Pool + 3 SDS nodes
2. Create volume (500MB, thin)
3. Add 3 SDCs
4. Map volume to SDC1 (RW), SDC2 (RW), SDC3 (RO)
5. Generate IO from all 3:
   - SDC1: write 50%, read 50%
   - SDC2: write 50%, read 50%
   - SDC3: read 100% (read-only)
6. Monitor: Volume shows concurrent IOPS increase
7. Reads distributed across replicas (load balancing)
8. Writes coordinated (both replicas updated)

**Assertions:**
- Volume state: IN_USE (multiple mappings)
- Replica consistency maintained
- Read prefer closest/fastest replica
- Write to both replicas (2 copies)

### Scenario D: Capacity Exhaustion
**Steps:**
1. Setup: PD + Pool (2GB total) + 2 SDS nodes (1.5GB each for safety margin)
2. Create volume 1 (800MB, thick)
3. Create volume 2 (800MB, thick)
4. Attempt create volume 3 (800MB, thick)
5. Monitor: API returns error "Insufficient capacity in pool"

**Assertions:**
- Volume 3 not created
- Pool.used_capacity_gb = 1.6GB (volumes 1+2)
- Error message clear and actionable

**Implementation Files:**
- `app/scenario_a.py` → Already exists (update for new models)
- `app/scenario_b.py` → New
- `app/scenario_c.py` → New
- `app/scenario_d.py` → New
- `app/scenarios/__init__.py` → Orchestrator that runs all scenarios

---

## PHASE 10: Validation Suite

**Goal**: Verify all PowerFlex rules are correctly enforced

**Test Categories:**

### 1. Data Integrity Tests
- ✓ No volume without pool
- ✓ No chunk without replicas
- ✓ TWO_COPIES: exactly 2 replicas per chunk (if all SDS UP)
- ✓ TWO_COPIES: replica on different SDS (never same SDS twice)
- ✓ No replica on DOWN node
- ✓ Thick volume: used_capacity = size_gb
- ✓ Thin volume: used_capacity ≤ size_gb

### 2. Capacity Tests
- ✓ Sum(volume.used_capacity) ≤ pool.total_capacity
- ✓ Thick volume creation fails if capacity insufficient
- ✓ Thin volume always succeeds (until SDS fills)
- ✓ extend fails if would exceed pool capacity

### 3. State Transition Tests
- ✓ Volume: AVAILABLE → IN_USE → AVAILABLE transitions valid
- ✓ Pool: OK → DEGRADED → OK on node fail/recover
- ✓ SDS: UP ↔ DOWN ↔ DEGRADED transitions valid
- ✓ Chunk: is_degraded flag set correctly based on replica availability

### 4. Failure & Rebuild Tests
- ✓ SDS failure: all chunks affected become degraded
- ✓ Rebuild: creates new replicas on different SDS
- ✓ Rebuild: respects rate limiting
- ✓ Rebuild: completes successfully
- ✓ Node recovery: chunks auto-heal if replicas present
- ✓ Node recovery: data loss if chunk lost all replicas

### 5. Access Control Tests
- ✓ Unmapped volume: SDC cannot access
- ✓ Mapped volume: SDC can access
- ✓ Read-only mapping: writes rejected
- ✓ Read-write mapping: reads/writes succeed

### 6. Metrics Tests
- ✓ IOPS aggregate: volume.iops = sum(sdc_iops) for all mapped SDCs
- ✓ IOPS aggregate: pool.iops = sum(volume_iops) for all volumes
- ✓ Bandwidth: calculated as iops × io_size
- ✓ Latency: moving average correctly computed

### 7. Event Logging Tests
- ✓ All state changes logged (14 event types)
- ✓ Event timestamps correct
- ✓ Event references (pool_id, volume_id, sds_id, sdc_id) correct
- ✓ Event history queryable

**Implementation:**
- `tests/test_integrity.py`
- `tests/test_capacity.py`
- `tests/test_state_machine.py`
- `tests/test_failure_rebuild.py`
- `tests/test_access_control.py`
- `tests/test_metrics.py`
- `tests/test_events.py`

**Test Runner:**
```bash
pytest tests/ -v --html=report.html
```

---

## Implementation Timeline & Dependencies

### Week 1
- [ ] PHASE 2: Storage Engine
- [ ] PHASE 3: Volume Ops (update for new engines)
- [ ] PHASE 5: Rebuild Engine

### Week 2
- [ ] PHASE 4: IO Simulator + metrics
- [ ] PHASE 6: Rebuild REST API endpoints
- [ ] Scenario A: update for new models

### Week 3
- [ ] PHASE 7: CLI tool (scli)
- [ ] PHASE 9: Scenarios B, C, D
- [ ] Flask GUI: update for new models

### Week 4
- [ ] PHASE 8: Prometheus + Grafana
- [ ] PHASE 10: Validation tests
- [ ] Documentation + endpoints guide

---

## File Structure

```
powerflex_demo/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app
│   ├── models.py                # SQLAlchemy ORM (✅ complete)
│   ├── database.py              # DB initialization
│   ├── logic.py                 # Storage engine (PHASE 2)
│   ├── cli.py                   # CLI entry point (PHASE 7)
│   ├── prometheus.py            # Metrics exporter (PHASE 8)
│   │
│   ├── api/                     # REST endpoints (PHASE 6)
│   │   ├── pd.py
│   │   ├── pool.py
│   │   ├── sds.py
│   │   ├── sdc.py
│   │   ├── volume.py
│   │   ├── rebuild.py
│   │   └── metrics.py
│   │
│   ├── services/                # Business logic
│   │   ├── storage_engine.py    # PHASE 2
│   │   ├── volume_manager.py    # PHASE 3
│   │   ├── io_simulator.py      # PHASE 4
│   │   ├── io_worker.py         # PHASE 4 (background thread)
│   │   └── rebuild_engine.py    # PHASE 5
│   │
│   ├── cli_commands/            # CLI subcommands (PHASE 7)
│   │   ├── pd.py
│   │   ├── pool.py
│   │   ├── sds.py
│   │   ├── sdc.py
│   │   ├── volume.py
│   │   ├── rebuild.py
│   │   └── scenarios.py
│   │
│   ├── scenarios/               # Demo scenarios (PHASE 9)
│   │   ├── __init__.py
│   │   ├── scenario_a.py        # Basic deployment
│   │   ├── scenario_b.py        # Failover & rebuild
│   │   ├── scenario_c.py        # Multi-host mapping
│   │   └── scenario_d.py        # Capacity exhaustion
│   │
│   └── config.py                # Settings (DB URL, ports, etc)
│
├── tests/                       # PHASE 10 validation
│   ├── test_integrity.py
│   ├── test_capacity.py
│   ├── test_state_machine.py
│   ├── test_failure_rebuild.py
│   ├── test_access_control.py
│   ├── test_metrics.py
│   └── test_events.py
│
├── templates/                   # Flask GUI templates
│   ├── base.html
│   ├── dashboard.html
│   ├── pd_list.html
│   ├── pool_list.html
│   ├── sds_list.html
│   ├── sdc_list.html
│   ├── volume_list.html
│   ├── metrics.html
│   ├── rebuild.html
│   └── scenarios.html
│
├── flask_gui.py                 # Flask web app
├── docker-compose.yml           # PHASE 8: Prometheus + Grafana
├── prometheus.yml               # PHASE 8: Metrics config
├── grafana_dashboard.json       # PHASE 8: Dashboard export
├── PLANS.md                     # This file
├── PHASES.md                    # Phase status tracker
├── README.md                    # User guide
└── .venv/                       # Python virtual env
```

---

## Success Criteria

✅ **PHASE COMPLETION CHECKLIST:**

- [ ] Phase 2: `test_allocate_chunks()` passes all 10 test cases
- [ ] Phase 3: All volume CRUD endpoints respond correctly
- [ ] Phase 4: Metrics fields updated every 5s in EventLog
- [ ] Phase 5: Rebuild completes within expected time, respects rate limit
- [ ] Phase 6: All 30 REST endpoints functional and tested
- [ ] Phase 7: `scli pool list` returns formatted table with health colors
- [ ] Phase 8: Grafana dashboard shows live IOPS/bandwidth charts
- [ ] Phase 9: All 4 scenarios complete without errors
- [ ] Phase 10: `pytest tests/ -v` shows 50+ tests passing

---

## Notes & Assumptions

1. **Metrics Update Frequency**: 5-second window (balance between responsiveness and accuracy)
2. **Chunk Size**: Fixed 4MB (simplifies allocation math)
3. **IO Size**: Assume 64KB average (used for bandwidth calculations)
4. **Latency Simulation**: Random 5-50ms per operation (realistic for SAN)
5. **Rebuild Rate**: Configurable per pool, default 100 MB/s
6. **Replica Selection**: Always prefer best (lowest latency), fallback to any available
7. **FaultSet**: Optional optimization; basic implementation may skip initially
8. **Error Handling**: Always return meaningful 400/409 errors with explanations
9. **Database**: SQLite for simplicity; production would use PostgreSQL
10. **Async**: Use asyncio for background tasks (rebuild, metrics, IO simulation)

---

**Last Updated:** 2/9/2026
**Owner:** PowerFlex Simulator Project
**Status:** Phases 0-1 ✅, Phases 2-10 in planning

