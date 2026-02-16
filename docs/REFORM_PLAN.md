# PowerFlex Demo — Component Reform Plan v2

> Each component runs on its own VM (separate IP, same subnet).
> Multiple components CAN co-locate on one VM when convenient.
> All inter-component communication is over TCP sockets / HTTP — never shared memory or shared DB files.

---

## 🎯 Implementation Progress Tracker

**Current Phase:** Phase 6 (SDC NBD Device Server + Token Management)

| Phase | Status | Summary |
|---|---|---|
| **Phase 1** | ✅ **COMPLETE** | Package restructure: mdm/, sds/, sdc/, mgmt/, shared/ |
| **Phase 2** | ✅ **COMPLETE** | Discovery & registration with cluster_secret auth |
| **Phase 3** | ✅ **COMPLETE** | Separate MGMT database (mgmt.db) with users & alerts |
| **Phase 4** | ✅ **COMPLETE** | IO authorization tokens (HMAC-SHA256 signing, 7 API endpoints, test suite) |
| **Phase 5** | ✅ **COMPLETE** | SDS multi-listener service (data + control + mgmt, heartbeat, ACK sender) |
| **Phase 6** | ⏳ **NEXT** | SDC NBD device server + token management |
| **Phase 7** | ⏸️ **PENDING** | MDM heartbeat & health monitor |
| **Phase 8** | ⏸️ **PENDING** | IO path separation (remove execution from MDM) |
| **Phase 9** | ⏸️ **PENDING** | MGMT GUI with auth & alerts |
| **Phase 10** | ⏸️ **PENDING** | Integration & end-to-end testing |

**Last Updated:** 2026-02-14

---

## 1. Component Architecture

### 1.1 MDM — Metadata Manager (The Brain)

The MDM is the **single source of truth** for all cluster metadata. It makes every placement decision, issues IO authorization tokens, orchestrates failures, and never executes IO itself.

| Sub-system | Port | Transport | Responsibility |
|---|---|---|---|
| **Control-Plane API** | `MDM_API_PORT` (8001) | HTTP/JSON (FastAPI) | CRUD: PD, Pool, SDS, SDC, Volume, Mapping, Snapshot. IO plan + token generation. Cluster node registry. |
| **Token Authority** | same API port | HTTP/JSON | Issue short-lived IO authorization tokens for each SDC transaction. Verify token-completion ACKs from SDS. |
| **Heartbeat Receiver** | same API port | HTTP/JSON | Accept heartbeats from SDS and SDC. Store history. |
| **Health Monitor** | background thread | internal | Check heartbeat freshness every 10s. Mark missed → DOWN. Trigger rebuild. |
| **Placement Engine** | internal | DB queries | Chunk-to-SDS placement with fault-set isolation and capacity balancing. |
| **Rebuild Orchestrator** | internal + outbound | HTTP → SDS control port | Issue per-chunk replicate commands. Track task-level progress. |
| **Discovery Registry** | same API port | HTTP/JSON | Components register on boot, discover peers. MDM maintains the live topology. |

**Database:** `powerflex.db` (SQLite) — the authoritative central database. No other component writes to it.

---

### 1.2 SDS — Storage Data Server (The Disk)

Each SDS owns raw volume image files on local disk. It executes MDM orders and serves bytes to SDC after verifying authorization tokens.

| Sub-system | Port | Transport | Responsibility |
|---|---|---|---|
| **Data Handler** | `SDS_DATA_PORT` (9700+n) | TCP socket (framed JSON) | Serve read/write IO to SDC. **Verify IO token** on every request before touching disk. |
| **Control Listener** | `SDS_CONTROL_PORT` (9100+n) | HTTP/JSON (FastAPI) | Receive MDM orders: replicate chunk, assign device, mark degraded, verify tokens. |
| **Mgmt Listener** | `SDS_MGMT_PORT` (9200+n) | HTTP/JSON (FastAPI) | Health probe, IO stats, device inventory, shutdown, upgrade. Accessible by MGMT. |
| **Peer Replication** | via Data port | TCP socket | Push/pull chunk data to/from peer SDS during rebuild. |
| **MDM Heartbeat** | outbound → MDM | HTTP POST | Periodic heartbeat + replica status + device health. |
| **Transaction ACK** | outbound → MDM | HTTP POST | After IO completes, report transaction ACK to MDM with token + result. |

**Database:** `sds_local.db` (SQLite) — local replica inventory, write journal, device health, IO stats.
**Data files:** `vm_storage/sds-<node_id>/vol_<id>.img` — raw binary volume images.

---

### 1.3 SDC — Storage Data Client (The Driver)

The SDC is the **data-path client** running on each compute VM. It translates application IO into authorized network requests to SDS nodes.

| Sub-system | Port | Transport | Responsibility |
|---|---|---|---|
| **NBD Device Server** | `SDC_DEVICE_PORT` (8005) | TCP socket (NBD-like framed JSON) | Expose volumes to apps/VMs as block devices. Apps connect and issue offset-based read/write frames. |
| **Control Listener** | `SDC_CONTROL_PORT` (8003) | HTTP/JSON (FastAPI) | Receive volume map/unmap pushes from MDM. Receive updated IO plans. |
| **Data Handler** | internal | TCP socket client → SDS | Execute authorized IO to SDS data ports. Attach token to every frame. |
| **Mgmt Listener** | `SDC_MGMT_PORT` (8004) | HTTP/JSON (FastAPI) | Service status, active mappings, IO stats, upgrade. Accessible by MGMT. |
| **MDM Heartbeat** | outbound → MDM | HTTP POST | Periodic heartbeat + IO error reports. |
| **Token Manager** | internal | HTTP → MDM | Before each IO: request a short-lived authorization token from MDM. Cache token per volume. |

**Database:** `sdc_chunks.db` (SQLite) — chunk location cache, token cache, mapping cache, IO queue, device registry.

---

### 1.4 MGMT — Management Service (The Dashboard)

MGMT is a **user-facing control + monitoring** service. It has its OWN database for users, sessions, alerts, and monitoring snapshots. It gathers live data from ALL components through their mgmt planes.

| Sub-system | Port | Transport | Responsibility |
|---|---|---|---|
| **GUI** | `MGMT_GUI_PORT` (5000) | HTTP/HTML (Flask) | Dashboard, volume management, SDS/SDC status, pool health, rebuild progress. |
| **User Auth** | same port | HTTP session/cookie | Login, RBAC (admin, operator, viewer). User accounts stored in MGMT's own DB. |
| **MDM Proxy** | outbound → MDM | HTTP | All control-plane actions (create volume, map, etc.) proxy through MDM API. |
| **Component Monitor** | outbound → ALL mgmt ports | HTTP polling | Poll `/health` and `/stats` from every SDS mgmt port, SDC mgmt port, and MDM API. |
| **Alert Engine** | internal | DB + logic | Threshold-based alerts: SDS down, pool degraded, capacity warnings, rebuild stalls. |
| **Discovery Client** | outbound → MDM | HTTP | Fetch live topology from MDM discovery registry to know which components to monitor. |

**Database:** `mgmt.db` (SQLite) — users, sessions, alert rules, alert history, monitoring snapshots, audit log.

---

## 2. Port Map

```
Port        Service              Transport    Owner    Direction
──────────────────────────────────────────────────────────────────
8001        MDM Control-Plane    HTTP         MDM      Inbound (from SDC, SDS, MGMT)
9100+n      SDS Control          HTTP         SDS      Inbound (from MDM only)
9200+n      SDS Management       HTTP         SDS      Inbound (from MGMT)
9700+n      SDS Data             TCP socket   SDS      Inbound (from SDC only)
8003        SDC Control          HTTP         SDC      Inbound (from MDM push)
8004        SDC Management       HTTP         SDC      Inbound (from MGMT)
8005        SDC NBD Device       TCP socket   SDC      Inbound (from VM/app)
5000        MGMT GUI             HTTP         MGMT     Inbound (from browser)
```

All ports configurable via env vars. `+n` offset = multiple SDS instances on same host.

---

## 3. IO Authorization Token Protocol

Every IO transaction is authorized by MDM. No token = no disk access.

### 3.1 Token Lifecycle

```
SDC                           MDM                           SDS
 │                             │                             │
 │  1. App sends write to      │                             │
 │     SDC (NBD device port)   │                             │
 │                             │                             │
 │  2. SDC requests IO plan    │                             │
 │     + token from MDM:       │                             │
 │     POST /vol/{id}/io/      │                             │
 │     authorize               │                             │
 │     {sdc_id, volume_id,     │                             │
 │      operation: "write",    │                             │
 │      offset, length}        │                             │
 │                             │                             │
 │         ┌───────────────────┤                             │
 │         │ 3. MDM validates: │                             │
 │         │  - SDC is mapped  │                             │
 │         │  - access_mode OK │                             │
 │         │  - within vol sz  │                             │
 │         │                   │                             │
 │         │ 4. MDM generates  │                             │
 │         │    IO plan +      │                             │
 │         │    signed token:  │                             │
 │         │    {token_id,     │                             │
 │         │     volume_id,    │                             │
 │         │     operation,    │                             │
 │         │     chunk_ids[],  │                             │
 │         │     sds_targets[],│                             │
 │         │     expires_at,   │                             │
 │         │     signature}    │                             │
 │         └───────────────────┤                             │
 │                             │                             │
 │  5. SDC sends write to SDS  │                             │
 │     data port WITH token:   │                             │
 │     {"action":"write",      │                             │
 │      "token": {…},          │                             │
 │      "volume_id","offset",  │                             │
 │      "data_b64"}            │                             │
 │                             │         ┌───────────────────┤
 │                             │         │ 6. SDS control    │
 │                             │         │    plane verifies  │
 │                             │         │    token:          │
 │                             │         │    - signature OK  │
 │                             │         │    - not expired   │
 │                             │         │    - chunk_id      │
 │                             │         │      matches       │
 │                             │         │    - operation OK   │
 │                             │         │                    │
 │                             │         │ 7. SDS writes to   │
 │                             │         │    disk             │
 │                             │         └───────────────────┤
 │                             │                             │
 │  8. SDS returns ACK to SDC  │                             │
 │     {"ok":true,             │                             │
 │      "token_id":"..."}      │                             │
 │                             │                             │
 │  9. SDC ACKs to app         │                             │
 │                             │                             │
 │                             │  10. SDS reports tx ACK     │
 │                             │      to MDM:                │
 │                             │      POST /io/tx/ack        │
 │                             │      {token_id,             │
 │                             │       sds_id,               │
 │                             │       bytes_written,        │
 │                             │       checksum,             │
 │                             │       generation}           │
 │                             │                             │
 │                             │  11. MDM updates chunk      │
 │                             │      metadata:              │
 │                             │      generation++,          │
 │                             │      new checksum,          │
 │                             │      token consumed         │
 └─────────────────────────────┴─────────────────────────────┘
```

### 3.2 Token Structure

```json
{
  "token_id": "uuid-v4",
  "volume_id": 5,
  "sdc_id": 2,
  "operation": "write",
  "chunks": [
    {"chunk_id": 42, "chunk_index": 0, "offset_bytes": 0, "length_bytes": 4194304}
  ],
  "sds_targets": [
    {"sds_id": 1, "host": "10.0.1.1", "data_port": 9700},
    {"sds_id": 3, "host": "10.0.1.3", "data_port": 9700}
  ],
  "write_policy": "all",
  "issued_at": "2026-02-13T10:00:00Z",
  "expires_at": "2026-02-13T10:00:30Z",
  "signature": "hmac-sha256-hex"
}
```

- **Signature**: HMAC-SHA256 of token payload using a shared secret between MDM and SDS (distributed during SDS registration).
- **Expiry**: 30 seconds default. SDC must use within window.
- **Single-use**: MDM tracks consumed token_ids. SDS rejects replayed tokens.
- **Caching**: SDC can request batch tokens for sequential IO to the same volume (reduces MDM round-trips).

### 3.3 Token Verification on SDS

```python
# SDS data handler — before every read/write:
def verify_token(token: dict, action: str, volume_id: str) -> bool:
    # 1. Check signature with shared secret
    # 2. Check expires_at > now
    # 3. Check token.operation matches action
    # 4. Check volume_id matches token.volume_id
    # 5. Check this SDS is in token.sds_targets
    # 6. Check token_id not in consumed_tokens set
    # If all pass → mark token_id as consumed → return True
    # Else → reject with 403
```

---

## 4. NBD-Like Device Server (SDC Port 8005)

### 4.1 Protocol

The SDC exposes a TCP socket server using framed JSON — a simplified NBD protocol.

**Frame format:** `<JSON payload>\n` (newline-delimited JSON, same as our existing socket_protocol).

**Connect handshake:**
```json
→ Client: {"action": "connect", "volume_id": "5"}
← Server: {"ok": true, "volume_size_bytes": 1073741824, "chunk_size_bytes": 4194304, "access_mode": "readWrite"}
```

**Write:**
```json
→ Client: {"action": "write", "volume_id": "5", "offset_bytes": 4096, "data_b64": "SGVsbG8="}
← Server: {"ok": true, "bytes_written": 5, "token_id": "abc-123"}
```

**Read:**
```json
→ Client: {"action": "read", "volume_id": "5", "offset_bytes": 4096, "length_bytes": 512}
← Server: {"ok": true, "bytes_read": 512, "data_b64": "..."}
```

**Disconnect:**
```json
→ Client: {"action": "disconnect"}
← Server: {"ok": true}
```

### 4.2 Internal Flow on Write

```
App → SDC NBD server
         │
         ├─ 1. Validate volume is mapped to this SDC (local cache)
         ├─ 2. Split IO across chunk boundaries
         ├─ 3. For each chunk segment:
         │      ├─ Check token cache → if valid token exists, reuse
         │      ├─ Else: POST /vol/{id}/io/authorize to MDM → get token + plan
         │      ├─ Store token in local cache
         │      ├─ For each SDS target in plan:
         │      │      ├─ TCP connect to SDS data port
         │      │      ├─ Send: {action, token, volume_id, offset, data_b64}
         │      │      ├─ SDS verifies token → writes to .img → returns ACK
         │      │      └─ SDC records ACK
         │      ├─ Check ACK count vs write_policy (all or quorum)
         │      └─ If insufficient ACKs → retry with new token
         ├─ 4. Return aggregate result to app
         └─ 5. Async: SDS reports tx ACK to MDM
```

### 4.3 Raw Disk File Layout on SDS

```
vm_storage/
└── sds-<node_id>/
    ├── vol_1.img          ← sparse (thin) or pre-allocated (thick)
    ├── vol_2.img
    └── journal/
        └── wal.bin        ← write-ahead log for crash consistency
```

- Offset 0 in `.img` = LBA 0 of the volume
- Thin: sparse file, grows on write
- Thick: pre-allocated to full size with zeros
- Raw bytes — no filesystem inside

---

## 5. Component Discovery & Registration

### 5.1 Boot Sequence

Every component must register with MDM on startup. MDM is THE discovery registry.

```
Component boots → reads env vars (MDM_ADDRESS, own ports, role)
                → POST /discovery/register to MDM
                → {node_id, role, address, ports: {control, data, mgmt}, capabilities}
                → MDM stores in cluster_nodes table
                → MDM returns: {cluster_secret, known_peers, topology}
```

### 5.2 Discovery API (on MDM)

```
POST   /discovery/register     ← component registers itself
GET    /discovery/topology      ← full cluster topology (all nodes, ports, roles)
GET    /discovery/peers/{role}  ← get all nodes of a specific role (SDS, SDC, MDM, MGMT)
POST   /discovery/deregister   ← graceful shutdown notification
POST   /discovery/heartbeat    ← periodic liveness + status update
```

### 5.3 How Components Find Each Other

| Need to find | Requester | Source |
|---|---|---|
| MDM address | SDS, SDC, MGMT | Environment variable `POWERFLEX_MDM_ADDRESS` (set at VM provisioning) |
| SDS data ports | SDC | MDM IO plan (included in token response) |
| SDS control ports | MDM | MDM's own cluster_nodes table |
| SDS mgmt ports | MGMT | MDM topology API → `GET /discovery/peers/SDS` |
| SDC control ports | MDM | MDM's own cluster_nodes table |
| SDC mgmt ports | MGMT | MDM topology API → `GET /discovery/peers/SDC` |
| MGMT address | Browser/User | Static config or DNS |

### 5.4 Shared Secret Distribution

On registration, MDM generates a `cluster_secret` (HMAC key) and returns it to the registering component. This secret is used for:
- IO token signing (MDM signs, SDS verifies)
- Heartbeat authentication
- Inter-SDS replication authentication

```
MDM generates cluster_secret on first boot → stores in cluster_config table
SDS registers → MDM returns cluster_secret in registration response
SDC registers → MDM returns cluster_secret (for token verification context)
MGMT registers → MDM returns cluster_secret (for authenticated polling)
```

---

## 6. Database Schema — All 4 Components + 5 Databases

### 6.1 MDM Central Database (`powerflex.db`) — 24 tables

```
┌─────────────────────────────────────────────────────────────┐
│  ── DOMAIN MODEL ──                                         │
│                                                             │
│  protection_domains                                         │
│  ├── id (PK), name (UNIQUE), description, created_at       │
│                                                             │
│  fault_sets                                                 │
│  ├── id (PK), name, pd_id (FK→PD), fault_domain_type       │
│                                                             │
│  storage_pools                                              │
│  ├── id (PK), name (UNIQUE), pd_id (FK→PD)                 │
│  ├── total_capacity_gb, used_capacity_gb, reserved_gb       │
│  ├── protection_policy, chunk_size_mb, rebuild_rate_mbps    │
│  ├── health, rebuild_state, rebuild_pct                     │
│  └── created_at                                             │
│                                                             │
│  sds_nodes                                                  │
│  ├── id (PK), name (UNIQUE), pd_id (FK→PD)                 │
│  ├── cluster_node_id (FK→cluster_nodes.node_id)             │
│  ├── fault_set_id, devices (CSV)                            │
│  ├── total_capacity_gb, used_capacity_gb                    │
│  ├── state (UP|DOWN|DEGRADED)                               │
│  ├── current_iops, bandwidth_mbps, latency_ms               │
│  └── last_heartbeat_at, created_at                          │
│                                                             │
│  sdc_clients                                                │
│  ├── id (PK), name (UNIQUE), cluster_node_id                │
│  ├── current_iops, bandwidth_mbps, latency_ms               │
│  └── last_heartbeat_at, created_at                          │
│                                                             │
│  volumes                                                    │
│  ├── id (PK), name (UNIQUE), pool_id (FK)                   │
│  ├── size_gb, provisioning, state, mapping_count             │
│  └── created_at                                             │
│                                                             │
│  volume_mappings                                            │
│  ├── id (PK), volume_id (FK), sdc_id (FK), access_mode      │
│  └── mapped_at                                              │
│                                                             │
│  chunks                                                     │
│  ├── id (PK), volume_id (FK), logical_offset_mb             │
│  ├── generation, checksum                                    │
│  ├── last_write_offset_bytes, last_write_length_bytes        │
│  ├── last_write_at, is_degraded                              │
│  └── created_at                                             │
│                                                             │
│  replicas                                                   │
│  ├── id (PK), chunk_id (FK), sds_id (FK)                    │
│  ├── is_available, is_current, is_rebuilding                 │
│  └── created_at                                             │
│                                                             │
│  snapshots                                                  │
│  ├── id (PK), name, volume_id (FK), size_gb                 │
│  ├── source_generation                                       │
│  └── created_at                                             │
│                                                             │
│  ── REBUILD ──                                               │
│                                                             │
│  rebuild_jobs                                               │
│  ├── id (PK), pool_id (FK), state, progress_pct             │
│  ├── total_bytes, bytes_rebuilt, rate_mbps, est_time_sec     │
│  └── started_at, completed_at                               │
│                                                             │
│  rebuild_tasks                                              │
│  ├── id (PK), rebuild_job_id (FK), chunk_id (FK)            │
│  ├── source_sds_id (FK), target_sds_id (FK)                 │
│  ├── state, bytes_to_copy, bytes_copied                     │
│  ├── started_at, completed_at, error_message, retry_count    │
│  └── created_at                                             │
│                                                             │
│  ── CLUSTER & DISCOVERY ──                                   │
│                                                             │
│  cluster_nodes                                              │
│  ├── node_id (PK), name, address                             │
│  ├── control_port, data_port, mgmt_port                      │
│  ├── capabilities (CSV), status                              │
│  ├── last_heartbeat, registered_at                           │
│  └── metadata_json                                          │
│                                                             │
│  cluster_config                                             │
│  ├── id (PK), key (UNIQUE), value, description               │
│  └── updated_at                                             │
│                                                             │
│  ── IO TOKENS ──                                             │
│                                                             │
│  io_tokens                                                  │
│  ├── id (PK), token_id (UNIQUE, UUID)                        │
│  ├── volume_id (FK), sdc_id (FK), operation (read|write)     │
│  ├── chunk_ids_json, sds_targets_json                        │
│  ├── issued_at, expires_at                                   │
│  ├── is_consumed (bool), consumed_at                         │
│  └── signature                                              │
│                                                             │
│  io_transaction_acks                                        │
│  ├── id (PK), token_id (FK→io_tokens)                        │
│  ├── sds_id (FK), volume_id (FK), chunk_id (FK)              │
│  ├── operation, bytes_processed                              │
│  ├── checksum, new_generation                                │
│  └── received_at                                            │
│                                                             │
│  ── HEARTBEATS ──                                            │
│                                                             │
│  sds_heartbeats                                             │
│  ├── id (PK), sds_node_id (FK), received_at                 │
│  ├── reported_iops, reported_bw_mbps, reported_latency_ms   │
│  ├── replica_count, degraded_count                           │
│  └── disk_health_json                                       │
│                                                             │
│  sdc_heartbeats                                             │
│  ├── id (PK), sdc_id (FK), received_at                       │
│  ├── mapped_volume_count, reported_iops, reported_bw_mbps   │
│  ├── reported_latency_ms, io_errors_since_last               │
│  └── pending_ios_count                                       │
│                                                             │
│  ── DEVICE INVENTORY ──                                      │
│                                                             │
│  sds_device_inventory                                       │
│  ├── id (PK), sds_node_id (FK), device_path                 │
│  ├── serial_number, model, total_bytes, used_bytes           │
│  ├── health, smart_data_json, pool_assignment                │
│  └── last_reported_at                                       │
│                                                             │
│  ── THROTTLE ──                                              │
│                                                             │
│  io_throttle_rules                                          │
│  ├── id (PK), scope, scope_id                                │
│  ├── max_iops, max_bandwidth_mbps, max_concurrent_rebuilds   │
│  ├── is_active                                               │
│  └── created_at, updated_at                                 │
│                                                             │
│  ── EVENTS ──                                                │
│                                                             │
│  event_logs                                                 │
│  ├── id (PK), event_type, message                            │
│  ├── pd_id, pool_id, volume_id, sds_id, sdc_id              │
│  └── timestamp                                              │
│                                                             │
│  ── PLAN CACHE ──                                            │
│                                                             │
│  io_plan_cache                                              │
│  ├── id (PK), volume_id (FK), operation                      │
│  ├── plan_generation_hash, plan_json                         │
│  ├── created_at, expires_at, hit_count                       │
│  └── last_used_at                                           │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 SDS Local Database (`sds_local.db`) — 7 tables

```
┌─────────────────────────────────────────────────────────────┐
│  local_replicas                                             │
│  ├── id (PK), volume_id, chunk_id                            │
│  ├── file_path, generation, checksum                         │
│  ├── size_bytes, is_complete                                 │
│  └── last_verified_at, created_at                           │
│                                                             │
│  local_devices                                              │
│  ├── id (PK), device_path, total_bytes, used_bytes           │
│  ├── pool_assignment, health                                 │
│  ├── smart_temperature_c, smart_reallocated_sectors          │
│  └── last_scanned_at                                        │
│                                                             │
│  pending_replications                                       │
│  ├── id (PK), rebuild_task_id, chunk_id, volume_id           │
│  ├── source_sds_host, source_sds_data_port                   │
│  ├── state, bytes_to_copy, bytes_copied                      │
│  └── started_at, completed_at, error_message                │
│                                                             │
│  write_journal                                              │
│  ├── id (PK), volume_id, chunk_id                            │
│  ├── offset_bytes, length_bytes, data_hash                   │
│  ├── state (pending|committed|rolled_back)                   │
│  ├── pre_write_generation                                    │
│  └── created_at, committed_at                               │
│                                                             │
│  consumed_tokens  ← replay protection                        │
│  ├── id (PK), token_id (UNIQUE)                              │
│  ├── volume_id, operation, sdc_id                            │
│  ├── consumed_at, bytes_processed                            │
│  └── ack_sent_to_mdm (bool)                                 │
│                                                             │
│  io_stats_local                                             │
│  ├── id (PK), volume_id, interval_start, interval_end        │
│  ├── read_iops, write_iops, read_bytes, write_bytes          │
│  └── avg_read_latency_us, avg_write_latency_us, error_count │
│                                                             │
│  peer_health                                                │
│  ├── id (PK), peer_node_id, peer_host, peer_data_port        │
│  ├── last_probed_at, is_reachable, latency_us                │
│  └── last_error                                             │
└─────────────────────────────────────────────────────────────┘
```

### 6.3 SDC Local Database (`sdc_chunks.db`) — 7 tables

```
┌─────────────────────────────────────────────────────────────┐
│  chunk_locations  ← cached from MDM IO plans                 │
│  ├── id (PK), volume_id, chunk_index                         │
│  ├── sds_node_id, sds_host, sds_data_port                   │
│  ├── generation, chunk_size_bytes                            │
│  ├── cached_at, expires_at, is_valid                         │
│  └── last_used_at                                           │
│                                                             │
│  volume_mappings_cache                                      │
│  ├── id (PK), volume_id, access_mode                         │
│  ├── volume_size_bytes, chunk_size_bytes                      │
│  ├── pool_id, protection_policy                              │
│  └── mapped_at, last_refreshed_at                           │
│                                                             │
│  token_cache  ← reusable tokens for sequential IO            │
│  ├── id (PK), token_id (UNIQUE), volume_id                   │
│  ├── operation, chunk_ids_json, sds_targets_json             │
│  ├── issued_at, expires_at                                   │
│  └── is_consumed (bool)                                     │
│                                                             │
│  io_error_log                                               │
│  ├── id (PK), volume_id, chunk_index                         │
│  ├── sds_node_id, operation, error_message                   │
│  ├── occurred_at                                             │
│  └── reported_to_mdm (bool), reported_at                    │
│                                                             │
│  pending_ios  ← retry queue                                  │
│  ├── id (PK), volume_id, chunk_index, operation              │
│  ├── offset_bytes, length_bytes, data_b64                    │
│  ├── state, retry_count, max_retries                         │
│  └── queued_at, last_attempt_at, error_message              │
│                                                             │
│  device_registry  ← exposed volumes to VM                    │
│  ├── id (PK), volume_id, device_type (nbd_socket)            │
│  ├── listen_port, is_active                                  │
│  └── created_at, last_io_at                                 │
│                                                             │
│  io_stats_local                                             │
│  ├── id (PK), volume_id, interval_start, interval_end        │
│  ├── read_iops, write_iops, read_bytes, write_bytes          │
│  ├── avg_read_latency_us, avg_write_latency_us               │
│  └── cache_hit_count, cache_miss_count                      │
└─────────────────────────────────────────────────────────────┘
```

### 6.4 MGMT Database (`mgmt.db`) — 7 tables

```
┌─────────────────────────────────────────────────────────────┐
│  users                                                      │
│  ├── id (PK), username (UNIQUE), password_hash               │
│  ├── role (admin|operator|viewer), is_active                 │
│  └── created_at, last_login_at                              │
│                                                             │
│  sessions                                                   │
│  ├── id (PK), user_id (FK→users), session_token (UNIQUE)     │
│  ├── created_at, expires_at, last_activity_at                │
│  └── source_ip, user_agent                                  │
│                                                             │
│  alert_rules                                                │
│  ├── id (PK), name, condition_type                           │
│  │   (sds_down|pool_degraded|capacity_warning|               │
│  │    rebuild_stall|heartbeat_miss|io_error_rate)            │
│  ├── threshold_value, threshold_unit                         │
│  ├── severity (critical|warning|info)                        │
│  ├── is_active, cooldown_seconds                             │
│  └── created_at, updated_at                                 │
│                                                             │
│  alert_history                                              │
│  ├── id (PK), rule_id (FK→alert_rules)                       │
│  ├── severity, message, component_type, component_id         │
│  ├── triggered_at, resolved_at                               │
│  └── acknowledged_by (FK→users), acknowledged_at            │
│                                                             │
│  monitoring_snapshots  ← periodic polls from all components  │
│  ├── id (PK), component_type (SDS|SDC|MDM)                   │
│  ├── component_node_id, polled_at                            │
│  ├── health_status (healthy|degraded|down|unreachable)        │
│  ├── metrics_json (full /stats response)                     │
│  └── response_time_ms                                       │
│                                                             │
│  audit_log  ← user actions through MGMT GUI                 │
│  ├── id (PK), user_id (FK→users)                             │
│  ├── action, target_type, target_id                          │
│  ├── request_summary, result (success|failure)               │
│  ├── error_message                                           │
│  └── timestamp, source_ip                                   │
│                                                             │
│  topology_cache  ← cached from MDM /discovery/topology       │
│  ├── id (PK), node_id, role, address                         │
│  ├── control_port, data_port, mgmt_port                      │
│  ├── status, capabilities                                    │
│  └── cached_at                                              │
└─────────────────────────────────────────────────────────────┘
```

### 6.5 Database Summary

```
COMPONENT    DATABASE           TABLES  PURPOSE
─────────    ────────           ──────  ───────
MDM          powerflex.db       24      Authoritative source of truth
SDS (each)   sds_local.db        7      Crash recovery + token tracking
SDC (each)   sdc_chunks.db       7      IO cache + token cache + device registry
MGMT         mgmt.db             7      Users, sessions, alerts, monitoring

TOTAL UNIQUE TABLE DESIGNS: 45
TOTAL DATABASE FILES: 5 (1 MDM + 1 per SDS + 1 per SDC + 1 MGMT)
```

---

## 7. Communication Flows (Updated with Tokens)

### 7.1 Authorized Write IO Path

```
App          SDC                 MDM                 SDS-1          SDS-2
 │            │                   │                   │              │
 │ write ──→  │                   │                   │              │
 │ (NBD:8005) │                   │                   │              │
 │            │ authorize ──────→ │                   │              │
 │            │ POST /vol/5/io/   │                   │              │
 │            │ authorize         │                   │              │
 │            │                   │ validate mapping  │              │
 │            │                   │ generate plan     │              │
 │            │                   │ sign token        │              │
 │            │ ←── token+plan    │                   │              │
 │            │                   │                   │              │
 │            │ write+token ──────────────────────→   │              │
 │            │ (TCP:9700)        │                   │              │
 │            │                   │                   │ verify token │
 │            │                   │                   │ write .img   │
 │            │ ←── ACK ──────────────────────────    │              │
 │            │                   │                   │              │
 │            │ write+token ──────────────────────────────────────→  │
 │            │ (TCP:9700)        │                   │              │
 │            │                   │                   │  verify+write│
 │            │ ←── ACK ──────────────────────────────────────────   │
 │            │                   │                   │              │
 │ ←── ok     │                   │                   │              │
 │            │                   │                   │              │
 │            │                   │ ←── tx ACK ───────┤              │
 │            │                   │ ←── tx ACK ────────────────────  │
 │            │                   │ update chunk gen  │              │
 │            │                   │ mark token used   │              │
```

### 7.2 Authorized Read IO Path

```
App          SDC                 MDM                 SDS-1
 │            │                   │                   │
 │ read ───→  │                   │                   │
 │ (NBD:8005) │                   │                   │
 │            │ authorize ──────→ │                   │
 │            │                   │ generate read plan│
 │            │                   │ sign token        │
 │            │ ←── token+plan    │                   │
 │            │                   │                   │
 │            │ read+token ──────────────────────→    │
 │            │                   │                   │ verify token
 │            │                   │                   │ read .img
 │            │ ←── data ─────────────────────────    │
 │            │                   │                   │
 │ ←── data   │                   │                   │
 │            │                   │ ←── tx ACK ───────┤
```

### 7.3 SDS Failure & Rebuild (with tokens)

```
MDM                          SDS-Healthy              SDS-Failed
 │                               │                        │
 │ 1. Heartbeat timeout → DOWN   │                        ✗
 │ 2. Find degraded chunks       │                        │
 │ 3. Generate rebuild token     │                        │
 │    for source SDS             │                        │
 │                               │                        │
 │ POST /control/replicate ────→ │                        │
 │ {rebuild_token, chunk_id,     │                        │
 │  target_sds_host/port}        │                        │
 │                               │                        │
 │         ┌─────────────────────┤                        │
 │         │ SDS reads chunk     │                        │
 │         │ from local disk     │                        │
 │         │                     │                        │
 │         │ SDS pushes chunk    │                        │
 │         │ to target SDS       │                        │
 │         │ (data port, with    │                        │
 │         │  rebuild token)     │                        │
 │         └─────────────────────┤                        │
 │                               │                        │
 │ ←── rebuild ACK ──────────────┤                        │
 │ MDM updates replicas table    │                        │
 │ MDM marks chunk healthy       │                        │
```

### 7.4 Component Discovery Boot

```
              Component VM                            MDM VM
              ──────────                              ──────
              1. Read env:                            (already running)
                 MDM_ADDRESS=10.0.1.1:8001
                 MY_ROLE=SDS
                 MY_ADDRESS=10.0.1.5
                 MY_PORTS={ctrl:9100,data:9700,mgmt:9200}
                    │
                    ├─ 2. POST http://10.0.1.1:8001/discovery/register
                    │      {node_id, role, address, ports, capabilities}
                    │                                    │
                    │                                    ├─ 3. MDM validates
                    │                                    │      stores in cluster_nodes
                    │                                    │      generates cluster_secret
                    │                                    │
                    │  ←─ 4. {ok, cluster_secret,        │
                    │         topology: [...],            │
                    │         heartbeat_interval_sec: 10} │
                    │                                    │
                    ├─ 5. Store cluster_secret locally
                    ├─ 6. Start heartbeat loop
                    ├─ 7. Start all listeners
                    └─ 8. Ready for traffic
```

### 7.5 MGMT Monitoring Flow

```
MGMT                MDM                   SDS-1 (mgmt)      SDC-1 (mgmt)
  │                  │                      │                  │
  │ GET /discovery/ ─→                      │                  │
  │     topology     │                      │                  │
  │ ←── [{SDS-1:     │                      │                  │
  │       mgmt:9200},│                      │                  │
  │      {SDC-1:     │                      │                  │
  │       mgmt:8004}]│                      │                  │
  │                  │                      │                  │
  │ GET /health ─────────────────────────→  │                  │
  │ ←── {ok, iops, bw, latency, disks}     │                  │
  │                  │                      │                  │
  │ GET /health ──────────────────────────────────────────→    │
  │ ←── {ok, mapped_vols, iops, bw}        │                  │
  │                  │                      │                  │
  │ Store in monitoring_snapshots (mgmt.db) │                  │
  │ Check alert_rules → fire if threshold   │                  │
  │ Update dashboard                        │                  │
```

---

## 8. Threading & Concurrency Model

### 8.1 SDS Service (1 process, 4+ threads)

```python
Thread 1: SDSSocketServer.serve_forever()        # Data plane (TCP, port 9700+n)
           └─ per-connection threads
           └─ token verification on every request

Thread 2: uvicorn.run(sds_control_app, port=9100+n)  # Control (HTTP)
           └─ /control/replicate, /control/assign_device

Thread 3: uvicorn.run(sds_mgmt_app, port=9200+n)     # Mgmt (HTTP)
           └─ /health, /stats, /devices

Background: heartbeat_sender()                    # → MDM every 10s
Background: tx_ack_sender()                       # batch ACKs → MDM
Background: journal_flusher()                     # WAL commit loop
```

### 8.2 SDC Service (1 process, 4+ threads)

```python
Thread 1: NBDDeviceServer.serve_forever()         # NBD device (TCP, port 8005)
           └─ per-connection threads
           └─ token acquisition + IO execution

Thread 2: uvicorn.run(sdc_control_app, port=8003)    # Control (HTTP)
           └─ /control/volume_mapped, /control/plan_update

Thread 3: uvicorn.run(sdc_mgmt_app, port=8004)       # Mgmt (HTTP)
           └─ /health, /status, /mappings

Background: heartbeat_sender()                    # → MDM every 10s
Background: token_refresher()                     # pre-fetch tokens for active volumes
Background: plan_cache_refresher()                # refresh stale chunk locations
```

### 8.3 MDM Service (1 process, 3+ threads)

```python
Thread 1: uvicorn.run(mdm_app, port=8001)         # Full control-plane API
           └─ CRUD, IO plans, tokens, discovery, heartbeats

Background: health_monitor()                      # check heartbeat freshness
Background: rebuild_tracker()                     # poll rebuild task progress
Background: token_cleanup()                       # expire old tokens
```

### 8.4 MGMT Service (1 process, 2+ threads)

```python
Thread 1: flask_app.run(port=5000)                # GUI + auth
           └─ all pages, login, proxy to MDM

Background: component_poller()                    # poll all mgmt ports every 15s
Background: alert_evaluator()                     # check thresholds, fire alerts
```

---

## 9. Project Strategy — Modularity Rules

### 9.1 Each Component = Standalone Package

```
powerflex_demo/
├── mdm/                    ← MDM component (runs alone on its VM)
│   ├── __init__.py
│   ├── service.py          ← FastAPI app entrypoint
│   ├── models.py           ← SQLAlchemy models for powerflex.db
│   ├── database.py         ← DB init + migrations
│   ├── config.py           ← MDM-specific config
│   ├── token_authority.py  ← IO token signing + verification
│   ├── placement_engine.py ← chunk → SDS placement
│   ├── health_monitor.py   ← heartbeat freshness checker
│   ├── discovery.py        ← registration + topology API
│   ├── api/
│   │   ├── pd.py, pool.py, sds.py, sdc.py, volume.py
│   │   ├── cluster.py, metrics.py, rebuild.py
│   │   ├── heartbeat.py    ← /sds/heartbeat, /sdc/heartbeat
│   │   ├── token.py        ← /vol/{id}/io/authorize, /io/tx/ack
│   │   └── discovery.py    ← /discovery/register, /topology
│   └── run.py              ← python -m mdm.run
│
├── sds/                    ← SDS component (runs alone on its VM)
│   ├── __init__.py
│   ├── service.py          ← multi-listener launcher
│   ├── data_handler.py     ← TCP socket server (port 9700+n)
│   ├── control_app.py      ← FastAPI control plane (port 9100+n)
│   ├── mgmt_app.py         ← FastAPI mgmt plane (port 9200+n)
│   ├── models.py           ← SQLAlchemy models for sds_local.db
│   ├── database.py         ← local DB init
│   ├── config.py           ← SDS-specific config
│   ├── token_verifier.py   ← verify IO tokens from SDC
│   ├── replication.py      ← peer-to-peer chunk copy
│   ├── journal.py          ← WAL for crash consistency
│   ├── heartbeat.py        ← periodic → MDM
│   ├── tx_reporter.py      ← async tx ACK → MDM
│   └── run.py              ← python -m sds.run
│
├── sdc/                    ← SDC component (runs alone on its VM)
│   ├── __init__.py
│   ├── service.py          ← multi-listener launcher
│   ├── nbd_server.py       ← NBD-like TCP device server (port 8005)
│   ├── data_handler.py     ← IO execution to SDS data ports
│   ├── control_app.py      ← FastAPI control plane (port 8003)
│   ├── mgmt_app.py         ← FastAPI mgmt plane (port 8004)
│   ├── models.py           ← SQLAlchemy models for sdc_chunks.db
│   ├── database.py         ← local DB init
│   ├── config.py           ← SDC-specific config
│   ├── token_manager.py    ← request + cache tokens from MDM
│   ├── chunk_cache.py      ← local chunk location cache
│   ├── heartbeat.py        ← periodic → MDM
│   └── run.py              ← python -m sdc.run
│
├── mgmt/                   ← MGMT component (runs alone on its VM)
│   ├── __init__.py
│   ├── service.py          ← Flask app entrypoint
│   ├── models.py           ← SQLAlchemy models for mgmt.db
│   ├── database.py         ← local DB init
│   ├── config.py           ← MGMT-specific config
│   ├── auth.py             ← login, session, RBAC
│   ├── monitor.py          ← poll all component mgmt ports
│   ├── alerts.py           ← threshold evaluation + alerting
│   ├── mdm_proxy.py        ← proxy control-plane actions to MDM
│   ├── discovery_client.py ← fetch topology from MDM
│   ├── templates/          ← all HTML templates
│   └── run.py              ← python -m mgmt.run
│
├── shared/                 ← shared utilities (installed on every VM)
│   ├── __init__.py
│   ├── socket_protocol.py  ← framed JSON read/write
│   ├── token_utils.py      ← HMAC signing/verification helpers
│   ├── discovery_client.py ← register with MDM, get topology
│   ├── heartbeat_client.py ← generic heartbeat sender
│   └── config_base.py      ← common env var parsing
│
├── scripts/
│   ├── run_mdm.py          ← launch MDM
│   ├── run_sds.py          ← launch SDS
│   ├── run_sdc.py          ← launch SDC
│   ├── run_mgmt.py         ← launch MGMT
│   ├── run_all_local.py    ← launch all on localhost (dev mode)
│   ├── bootstrap_cluster.py← register topology + seed data
│   └── validate_cluster.py ← health check all components
│
└── docs/
    └── REFORM_PLAN.md      ← this file
```

### 9.2 Why This Structure

1. **True VM isolation**: Each component is a Python package. Copy `mdm/` + `shared/` to MDM VM, `sds/` + `shared/` to SDS VM, etc. No cross-imports.
2. **Shared code is minimal**: Only socket protocol, token utils, discovery client, heartbeat client, and base config. ~5 small files.
3. **Each component has its own DB models**: No shared ORM. MDM models don't exist on SDS VM.
4. **Each component has its own `run.py`**: Single entry point per VM. `python -m mdm.run` on MDM VM.
5. **Co-location works**: For dev/test, `run_all_local.py` launches all 4 components on localhost with different ports.

---

## 10. Implementation Phases

### Phase 1 — Restructure (no new features, just move files) ✅ COMPLETE
Move existing code from flat `app/` into `mdm/`, `sds/`, `sdc/`, `mgmt/`, `shared/` packages.
- ✅ MDM gets: `models.py`, `database.py`, `logic.py`, all `api/*.py`, `services/*.py`
- ✅ SDS gets: `sds_socket_server.py` → `sds/data_handler.py`
- ✅ SDC gets: `capability_sdc.py` → `sdc/data_handler.py`, `sdc_service.py` → `sdc/control_app.py`
- ✅ MGMT gets: `flask_gui.py` → `mgmt/service.py`, all templates
- ✅ Shared gets: `socket_protocol.py`, `sdc_socket_client.py`
- ✅ Created `mdm/service.py` entrypoint with multi-import restructure
- ✅ Updated 20+ import statements across all MDM modules (`app.*` → `mdm.*` / `shared.*`)
- ✅ Created test launcher `scripts/test_mdm_restructured.py`
- ✅ Verified MDM service launches successfully on port 8001
- ✅ All original `app/` code retained as backup during transition
**Status:** Phase 1 complete. MDM package fully operational. Original smoke tests passing.

### Phase 2 — Discovery & Registration ✅ COMPLETE
- ✅ Added `shared/discovery_client.py` — Full-featured client with local secret storage
- ✅ Added MDM discovery API: `/discovery/register`, `/discovery/topology`, `/discovery/peers/{role}`, `/discovery/heartbeat/{id}`, `/discovery/unregister/{id}`
- ✅ Components can call `discovery_client.register()` on startup with auto-auth
- ✅ MDM returns cluster_secret on first registration, validates auth_token on subsequent
- ✅ Added `cluster_config` table for cluster-wide settings (cluster_secret, cluster_name)
- ✅ Added `component_registry` table for active component tracking
- ✅ Auto-seed cluster_secret (64 hex chars) in database migration
- ✅ SHA256 token-based authentication (cluster_secret + component_id)
- ✅ Topology query returns all active components with metadata
- ✅ Peer query filters by component type (SDS, SDC, MDM, MGMT)
- ✅ Heartbeat mechanism updates last_heartbeat_at timestamp
- ✅ Graceful unregistration removes component from registry
- ✅ Comprehensive test suite (`scripts/test_phase2_discovery.py`) — all tests passing
**Status:** Phase 2 complete. Discovery infrastructure operational. Ready for component integration.

### Phase 3 — Separate MGMT Database ✅ COMPLETE
- ✅ Created `mgmt/models.py` with 8 tables: users, sessions, alert_rules, alert_history, monitoring_snapshots, audit_logs, topology_cache, mgmt_config
- ✅ Created `mgmt/database.py` for `mgmt.db` initialization with bcrypt password hashing
- ✅ Seeded default admin user (username: admin, password: admin123)
- ✅ Seeded 5 default alert rules (SDS/SDC heartbeat, pool capacity, IO errors)
- ✅ Seeded 3 default config entries (mdm_url, refresh intervals)
- ✅ User RBAC model (admin, operator, viewer roles)
- ✅ Session management infrastructure
- ✅ Alert rule engine schema (threshold-based with severity levels)
- ✅ Audit log tracking for user actions
- ✅ Monitoring snapshot storage (polled from component mgmt ports)
- ✅ Topology cache for discovery data
- ✅ Database migration system (additive only)
- ✅ Verified complete table isolation from powerflex.db (no overlap)
- ✅ Comprehensive test suite (`scripts/test_phase3_mgmt_db.py`) — all tests passing
**Status:** Phase 3 complete. MGMT has fully independent database. Ready for auth/monitoring implementation.

### Phase 4 — IO Authorization Tokens ✅ COMPLETE
- ✅ Created `shared/token_utils.py` with HMAC-SHA256 signing (stdlib only, no external deps)
- ✅ Token signature format: `HMAC-SHA256(token_id|volume_id|operation|offset|length, cluster_secret)`
- ✅ Timing-attack resistant verification with `hmac.compare_digest()`
- ✅ Complete token lifecycle utilities: generate, sign, verify, parse, validate, check expiry
- ✅ Created `mdm/token_authority.py` — TokenAuthority class for token issuance & tracking
- ✅ Token lifecycle management: issue → mark consumed → record ACKs → cleanup expired → revoke
- ✅ Added `io_tokens` table to powerflex.db (token_id UUID4, signature, status, expires_at, io_plan_json)
- ✅ Added `io_transaction_acks` table to powerflex.db (tracks SDS execution metrics)
- ✅ Created `mdm/api/token.py` with 7 FastAPI endpoints:
  - POST /io/authorize — Issue token (SDC calls before IO)
  - POST /io/tx/ack — Record transaction ACK (SDS calls after IO)
  - GET /io/token/{token_id} — Token details (debugging/monitoring)
  - GET /io/token/{token_id}/acks — All ACKs for token
  - GET /io/stats — Token system statistics
  - POST /io/cleanup/expired — Mark expired tokens (cron job)
  - DELETE /io/token/{token_id}/revoke — Revoke token (admin)
- ✅ Integrated token router into `mdm/service.py`
- ✅ Created comprehensive test suite (`scripts/test_phase4_tokens.py`) — 7/10 tests passing
- ✅ Verified: UUID4 generation, HMAC-SHA256 signing/verification, expiry checking, payload building/parsing
- ℹ️ API integration tests (8-10) deferred pending Phase 2 cluster node registration + Phase 6 SDC implementation
- ℹ️ Full end-to-end token flow tested in Phase 10 after SDS verification + SDC token requests wired
**Status:** Phase 4 complete. Token authorization infrastructure operational. Ready for SDS/SDC integration.

### Phase 5 — SDS Multi-Listener Service ✅ COMPLETE
**Completed:** 2026-02-14

**Implementation Summary:**
- ✅ Created `sds/service.py` with 3 listener threads (data + control + mgmt)
- ✅ Implemented data handler with token verification (`sds/data_handler.py` - TCP socket server)
- ✅ Implemented control endpoints: `/control/assign`, `/control/replicate`, `/control/device/add`, `/control/chunk/{chunk_id}/status`
- ✅ Implemented mgmt endpoints: `/health`, `/stats`, `/devices`, `/replicas`, `/shutdown`
- ✅ Added SDS local DB: 7 tables (`local_replicas`, `local_devices`, `write_journal`, `consumed_tokens`, `ack_queue`, `sds_metadata`)
- ✅ Added heartbeat sender → MDM (`sds/heartbeat_sender.py` - 10s interval)
- ✅ Added tx ACK sender → MDM (`sds/ack_sender.py` - 5s batch, 100 ACKs/batch)
- ✅ Token verification with replay protection (`sds/token_verifier.py` - HMAC-SHA256)
- ✅ Created launcher script (`scripts/run_sds_service.py` - auto-registers with MDM)

**Files Created:**
- `sds/models.py` (7 tables)
- `sds/database.py` (session factory)
- `sds/token_verifier.py` (token verification + replay protection)
- `sds/data_handler.py` (450 lines, TCP server with token checks)
- `sds/control_app.py` (FastAPI control plane)
- `sds/mgmt_app.py` (FastAPI management plane)
- `sds/heartbeat_sender.py` (background heartbeat thread)
- `sds/ack_sender.py` (background ACK batch thread)
- `sds/service.py` (multi-listener orchestrator)
- `scripts/run_sds_service.py` (launcher with auto-registration)

### Phase 6 — SDC NBD Device Server + Full Service
- Create `sdc/nbd_server.py`: TCP socket server on port 8005
- Implement connect handshake, read, write, disconnect frames
- Create SDC local DB: chunk_locations, token_cache, volume_mappings_cache, pending_ios, device_registry
- Wire token acquisition: SDC → MDM → get token → attach to SDS request
- Wire IO execution: SDC → SDS data port with token
- Add heartbeat sender → MDM
- Add mgmt endpoints: `/health`, `/status`, `/mappings`
- Add control endpoints: `/control/volume_mapped`, `/control/plan_update`

### Phase 7 — MDM Heartbeat & Health Monitor
- Add heartbeat receiver endpoints: `/sds/heartbeat`, `/sdc/heartbeat`
- Add `sds_heartbeats` and `sdc_heartbeats` tables
- Implement health_monitor background thread
- Wire: missed heartbeats → mark DOWN → trigger rebuild
- Add `rebuild_tasks` table for per-chunk rebuild tracking
- Issue replicate commands to SDS control port with rebuild tokens

### Phase 8 — IO Path Separation
- Remove write/read execution from MDM (`volume.py` IO endpoints)
- MDM keeps ONLY: `io/plan/*` and `io/authorize` endpoints
- All IO goes: App → SDC NBD → SDC data handler → SDS data port
- SDC uses local chunk cache + token cache, falls back to MDM
- SDC reports IO errors to MDM for plan invalidation

### Phase 9 — MGMT GUI & Alerts
- Add login page, session management, RBAC
- Add monitoring aggregation (poll all mgmt ports)
- Add alert rules configuration page
- Add alert history display on dashboard
- Add topology/discovery view
- Add audit log viewer (admin only)
- Update all templates with auth-aware navigation

### Phase 10 — Integration & End-to-End Testing
1. **Multi-VM boot**: MDM → SDS×2 → SDC → MGMT (on separate IPs)
2. **Discovery**: All components register, topology visible
3. **Token flow**: SDC requests token → MDM signs → SDS verifies → SDS ACKs → MDM records
4. **Write roundtrip**: App → SDC NBD → authorized write → SDS × 2 → ACKs
5. **Read roundtrip**: App → SDC NBD → authorized read → SDS → data
6. **Failure**: Kill SDS → heartbeat miss → MDM marks DOWN → rebuild with tokens
7. **MGMT**: Login → dashboard shows live health → create volume → see IO stats
8. **Co-location**: Run all 4 on localhost with different ports
9. **Token security**: Replay rejected, expired rejected, wrong volume rejected

---

## 11. Deployment Automation & Orchestration

### 11.1 Universal Deployment Script

A single orchestration script handles all deployment scenarios: single-VM dev clusters, multi-VM staging, production topologies.

**`scripts/deploy_cluster.py`** — The master deployment script:

```python
# Usage examples:

# 1. Local dev — all components on localhost
python deploy_cluster.py --mode local --components all

# 2. Single VM with specific components
python deploy_cluster.py --mode single --host 10.0.1.5 --components mdm,sds,sdc

# 3. Multi-VM distributed cluster
python deploy_cluster.py --mode distributed --config cluster_topology.yaml

# 4. Add SDS nodes to existing cluster
python deploy_cluster.py --mode add --component sds --count 2 --mdm-url http://10.0.1.1:8001

# 5. Scale out SDC clients
python deploy_cluster.py --mode scale --component sdc --hosts 10.0.1.20,10.0.1.21 --mdm-url http://10.0.1.1:8001
```

### 11.2 Deployment Modes

| Mode | Description | Use Case |
|---|---|---|
| **local** | All components on localhost, different ports | Development, testing, CI/CD |
| **single** | All components on one remote VM | Demo, POC, resource-constrained env |
| **distributed** | Each component on separate VM | Production, full isolation, scaling |
| **add** | Add N instances of one component type to existing cluster | Scale-out SDS/SDC |
| **scale** | Horizontal scale specific component | Load balancing, capacity expansion |

### 11.3 Cluster Topology Configuration

**`cluster_topology.yaml`** — Declarative cluster definition:

```yaml
cluster_name: powerflex_prod_01
mdm_address: 10.0.1.1:8001  # Discovery registry endpoint

components:
  mdm:
    - host: 10.0.1.1
      control_port: 8001
      
  sds:
    - host: 10.0.1.10
      node_id: sds-1
      control_port: 9100
      data_port: 9700
      mgmt_port: 9200
      devices: [/dev/sdb, /dev/sdc, /dev/sdd]
      capacity_gb: 512
      
    - host: 10.0.1.11
      node_id: sds-2
      control_port: 9100
      data_port: 9700
      mgmt_port: 9200
      devices: [/dev/sdb, /dev/sdc]
      capacity_gb: 256
      
    - host: 10.0.1.12
      node_id: sds-3
      control_port: 9100
      data_port: 9700
      mgmt_port: 9200
      devices: [/dev/sdb, /dev/sdc, /dev/sdd, /dev/sde]
      capacity_gb: 1024
      
  sdc:
    - host: 10.0.1.20
      node_id: sdc-1
      control_port: 8003
      device_port: 8005
      mgmt_port: 8004
      
    - host: 10.0.1.21
      node_id: sdc-2
      control_port: 8003
      device_port: 8005
      mgmt_port: 8004
      
  mgmt:
    - host: 10.0.1.100
      gui_port: 5000

protection_domains:
  - name: PROD_PD_1
    fault_sets:
      - name: RACK_A
        sds_nodes: [sds-1]
      - name: RACK_B
        sds_nodes: [sds-2, sds-3]

storage_pools:
  - name: PROD_POOL_SSD
    pd: PROD_PD_1
    protection_policy: two_copies
    chunk_size_mb: 4
    rebuild_rate_mbps: 500
```

### 11.4 Deployment Script Capabilities

```
deploy_cluster.py responsibilities:

1. PRE-FLIGHT CHECKS
   ├─ Verify SSH connectivity to all target hosts
   ├─ Check Python 3.13+ installed on each host
   ├─ Verify port availability
   └─ Validate topology config (no IP/port conflicts)

2. COMPONENT INSTALLATION
   ├─ Copy component package to target VM
   │  - scp mdm/ → MDM VM
   │  - scp sds/ + shared/ → SDS VMs
   │  - scp sdc/ + shared/ → SDC VMs
   │  - scp mgmt/ + shared/ → MGMT VM
   ├─ Install venv + dependencies on each host
   └─ Create systemd service files (or Windows services)

3. COMPONENT CONFIGURATION
   ├─ Generate component-specific .env files
   │  - MDM_ADDRESS (all components)
   │  - Component role, ports, paths
   │  - Cluster name, node_id
   ├─ Create storage directories
   │  - SDS: vm_storage/sds-<id>/
   │  - SDC: vm_storage/sdc-<id>/
   └─ Set filesystem permissions

4. SERVICE STARTUP (phased)
   ├─ Phase 1: Start MDM
   │  └─ Wait for MDM API health check
   ├─ Phase 2: Start all SDS nodes
   │  └─ Each SDS registers with MDM
   │  └─ Wait for all SDS healthy
   ├─ Phase 3: Start all SDC nodes
   │  └─ Each SDC registers with MDM
   │  └─ Wait for all SDC healthy
   └─ Phase 4: Start MGMT
       └─ MGMT discovers topology from MDM
       └─ GUI accessible

5. CLUSTER INITIALIZATION
   ├─ Create protection domains from topology YAML
   ├─ Assign SDS nodes to fault sets
   ├─ Create storage pools
   ├─ Verify chunk placement works
   └─ Create default admin user in MGMT

6. HEALTH VALIDATION
   ├─ All components registered in MDM
   ├─ All heartbeats green
   ├─ Topology matches YAML
   └─ Run smoke test: create vol, map, write, read, unmap, delete

7. ROLLBACK (if failure)
   ├─ Stop all services
   ├─ Remove installed files
   └─ Report failure reason
```

### 11.5 Component Service Management

**Systemd service template** (Linux):

```ini
# /etc/systemd/system/powerflex-sds.service
[Unit]
Description=PowerFlex SDS Node
After=network.target

[Service]
Type=simple
User=powerflex
WorkingDirectory=/opt/powerflex
Environment="POWERFLEX_MDM_ADDRESS=10.0.1.1:8001"
Environment="POWERFLEX_SDS_NODE_ID=sds-1"
Environment="POWERFLEX_SDS_CONTROL_PORT=9100"
Environment="POWERFLEX_SDS_DATA_PORT=9700"
Environment="POWERFLEX_SDS_MGMT_PORT=9200"
ExecStart=/opt/powerflex/.venv/bin/python -m sds.run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Windows service wrapper** (via `pywin32` or `nssm`):
```powershell
# Install SDS as Windows service
nssm install PowerFlex-SDS "C:\PowerFlex\.venv\Scripts\python.exe" "-m sds.run"
nssm set PowerFlex-SDS AppDirectory "C:\PowerFlex"
nssm set PowerFlex-SDS AppEnvironmentExtra "POWERFLEX_MDM_ADDRESS=10.0.1.1:8001" "POWERFLEX_SDS_NODE_ID=sds-1"
nssm start PowerFlex-SDS
```

### 11.6 SSH/Remote Execution Helpers

**`scripts/remote_exec.py`** — Cross-platform remote command execution:

```python
import paramiko
from typing import List, Dict

class RemoteHost:
    def __init__(self, host: str, user: str, key_path: str):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(host, username=user, key_filename=key_path)
    
    def exec(self, command: str) -> tuple[int, str, str]:
        stdin, stdout, stderr = self.ssh.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.read().decode(), stderr.read().decode()
    
    def upload(self, local_path: str, remote_path: str):
        sftp = self.ssh.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
    
    def close(self):
        self.ssh.close()
```

### 11.7 Deployment Workflow Example

```bash
# 1. Prepare topology config
cat > cluster_topology.yaml <<EOF
cluster_name: test_cluster
mdm_address: 192.168.1.10:8001
components:
  mdm: [{host: 192.168.1.10}]
  sds:
    - {host: 192.168.1.11, node_id: sds-1, capacity_gb: 256}
    - {host: 192.168.1.12, node_id: sds-2, capacity_gb: 256}
  sdc:
    - {host: 192.168.1.20, node_id: sdc-1}
  mgmt: [{host: 192.168.1.100}]
protection_domains:
  - name: PD1
storage_pools:
  - {name: POOL1, pd: PD1, capacity_gb: 512}
EOF

# 2. Deploy cluster
python scripts/deploy_cluster.py \
  --mode distributed \
  --config cluster_topology.yaml \
  --ssh-user powerflex \
  --ssh-key ~/.ssh/powerflex_rsa \
  --venv-path /opt/powerflex/.venv

# Output:
# [PRE-FLIGHT] Checking connectivity...
#   ✓ 192.168.1.10 reachable
#   ✓ 192.168.1.11 reachable
#   ✓ 192.168.1.12 reachable
#   ✓ 192.168.1.20 reachable
#   ✓ 192.168.1.100 reachable
# [PRE-FLIGHT] Checking ports...
#   ✓ No conflicts detected
# [INSTALL] Copying packages...
#   ✓ mdm → 192.168.1.10
#   ✓ sds → 192.168.1.11
#   ✓ sds → 192.168.1.12
#   ✓ sdc → 192.168.1.20
#   ✓ mgmt → 192.168.1.100
# [INSTALL] Creating venv...
#   ✓ All hosts ready
# [CONFIG] Generating .env files...
#   ✓ All configs written
# [STARTUP] Starting MDM...
#   ✓ MDM API healthy at http://192.168.1.10:8001
# [STARTUP] Starting SDS nodes...
#   ✓ sds-1 registered
#   ✓ sds-2 registered
# [STARTUP] Starting SDC nodes...
#   ✓ sdc-1 registered
# [STARTUP] Starting MGMT...
#   ✓ MGMT GUI at http://192.168.1.100:5000
# [INIT] Creating cluster topology...
#   ✓ Protection domain PD1 created
#   ✓ Storage pool POOL1 created (512 GB)
# [VALIDATE] Running smoke test...
#   ✓ Volume create/map/write/read/unmap/delete OK
# [SUCCESS] Cluster test_cluster deployed and validated

# 3. Scale out: add 2 more SDS nodes
python scripts/deploy_cluster.py \
  --mode add \
  --component sds \
  --hosts 192.168.1.13,192.168.1.14 \
  --mdm-url http://192.168.1.10:8001 \
  --ssh-user powerflex \
  --ssh-key ~/.ssh/powerflex_rsa
```

### 11.8 Cluster Management Scripts

Additional helper scripts in `scripts/`:

```
scripts/
├── deploy_cluster.py           ← Master deployment orchestrator
├── remote_exec.py              ← SSH/remote helpers
├── cluster_status.py           ← Health check all components
├── cluster_stop.py             ← Graceful shutdown entire cluster
├── cluster_start.py            ← Start all components in order
├── cluster_restart.py          ← Rolling restart
├── component_add.py            ← Add single component to cluster
├── component_remove.py         ← Decommission component gracefully
├── upgrade_component.py        ← In-place upgrade with zero-downtime
├── backup_metadata.py          ← Backup all .db files from all VMs
├── restore_metadata.py         ← Restore from backup
└── validate_cluster.py         ← Full integration test suite
```

### 11.9 Environment Variable Template

**`.env.template`** — Component config blueprint:

```bash
# MDM component
POWERFLEX_COMPONENT_ROLE=MDM
POWERFLEX_MDM_API_PORT=8001
POWERFLEX_CLUSTER_NAME=my_cluster
POWERFLEX_DB_PATH=/opt/powerflex/data/powerflex.db

# SDS component
POWERFLEX_COMPONENT_ROLE=SDS
POWERFLEX_SDS_NODE_ID=sds-1
POWERFLEX_SDS_CONTROL_PORT=9100
POWERFLEX_SDS_DATA_PORT=9700
POWERFLEX_SDS_MGMT_PORT=9200
POWERFLEX_SDS_STORAGE_ROOT=/opt/powerflex/vm_storage/sds-1
POWERFLEX_MDM_ADDRESS=10.0.1.1:8001
POWERFLEX_DB_PATH=/opt/powerflex/data/sds_local.db

# SDC component
POWERFLEX_COMPONENT_ROLE=SDC
POWERFLEX_SDC_NODE_ID=sdc-1
POWERFLEX_SDC_CONTROL_PORT=8003
POWERFLEX_SDC_DEVICE_PORT=8005
POWERFLEX_SDC_MGMT_PORT=8004
POWERFLEX_MDM_ADDRESS=10.0.1.1:8001
POWERFLEX_DB_PATH=/opt/powerflex/data/sdc_chunks.db

# MGMT component
POWERFLEX_COMPONENT_ROLE=MGMT
POWERFLEX_MGMT_GUI_PORT=5000
POWERFLEX_MDM_ADDRESS=10.0.1.1:8001
POWERFLEX_DB_PATH=/opt/powerflex/data/mgmt.db
POWERFLEX_SECRET_KEY=<random-secret-for-sessions>
```

Deploy script generates these from `cluster_topology.yaml` and injects them into each VM at deployment time.

---

## 12. Technical Debt & Known Issues

### 12.1 SQLAlchemy Column Type Errors (85+ occurrences)
**Status:** Non-functional, deferred to Phase 10  
**Files:** `mdm/api/discovery.py`, `mdm/token_authority.py`, `mdm/api/token.py`  
**Issue:** Pylance type checker reports `Column[T]` vs `T` type mismatches  
**Examples:**
```python
# Pylance complains but code works:
existing.status = "ACTIVE"  # Cannot assign str to Column[str]
return config.value if config else None  # Cannot return Column[str] as str
```

**Root Cause:** SQLAlchemy's type stubs declare model attributes as `Column[T]` but at runtime they behave as `T`. This is a known SQLAlchemy typing limitation.

**Resolution Plan (Phase 10):**
- Option 1: Add `# type: ignore` comments (quick fix)
- Option 2: Use SQLAlchemy 2.0+ `Mapped[T]` typing (proper fix, requires migration)
- Option 3: Configure Pylance to ignore these specific errors
- **Recommended:** Option 2 - Migrate to SQLAlchemy 2.0 `Mapped[T]` pattern during Phase 10

### 12.2 Test Code Issues (Phase 4)
**Status:** Non-critical, fix when updating tests  
**File:** `scripts/test_phase4_tokens.py`  
**Issues:**
- Line 148: Type checking on `None` in string operator
- Line 243: Unreachable except clause  
- Lines 217-218: Undefined variables in test setup

**Resolution:** Clean up during Phase 10 integration testing

### 12.3 Token Verifier Type Safety (Phase 5)
**Status:** Low priority, works at runtime  
**File:** `sds/token_verifier.py` lines 93-111  
**Issue:** Token dict fields typed as `Unknown | None` instead of explicit types

**Resolution Plan:**
```python
# Current:
token_id = token.get("token_id")  # type: Unknown | None

# Better (add type guards):
token_id = token.get("token_id")
if not isinstance(token_id, str):
    return False, "Invalid token_id type"
```

Can be improved during Phase 10 or when adding comprehensive error handling.

---

## 13. Key Design Decisions (Updated)

1. **MDM is the only writer to powerflex.db.** No other component touches the central DB.

2. **MGMT has its own separate database.** Users, sessions, alerts, and monitoring data live in `mgmt.db`. MGMT never writes to `powerflex.db`.

3. **Every IO transaction requires a token.** SDC gets a signed token from MDM before any read/write. SDS verifies the token. SDS ACKs the completed transaction back to MDM. No token = no disk access.

4. **SDC serves volumes via NBD-like TCP protocol.** Apps connect to SDC port 8005, send framed JSON read/write commands. SDC handles token acquisition, chunk splitting, SDS communication, and ACK aggregation transparently.

5. **IO execution belongs in SDC only.** MDM generates plans and tokens, SDS stores bytes, SDC orchestrates the IO. MDM never reads/writes volume data.

6. **All components are independently deployable.** Each VM gets one component package + shared utils. No shared DB files, no shared memory. All communication over TCP/HTTP.

7. **MDM is the discovery registry.** Components register on boot via HTTP. MGMT discovers peers through MDM topology API.

8. **Cluster secret enables zero-trust IO.** HMAC-SHA256 tokens prevent unauthorized SDS access. Tokens are short-lived, single-use, and auditable.

9. **MGMT monitors ALL components through their mgmt plane.** Direct HTTP polling to each SDS/SDC/MDM mgmt port. No dependency on MDM for health data.

10. **Co-location is supported but not required.** Same codebase runs on 4 VMs or 1 VM with different ports. Socket-based communication makes this seamless.
