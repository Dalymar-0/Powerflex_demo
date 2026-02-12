

# PowerFlex Simulator - Complete 10-Phase Implementation

## Project Overview

A comprehensive Python-based simulator of Dell PowerFlex architecture, implementing storage distribution, failure detection, automatic rebuild, and monitoring across 10 distinct phases.

## Project Motivation (North Star)

This project is intended to evolve from a local simulator into a realistic multi-VM PowerFlex demo:
- Each VM can take one or more roles: SDC, SDS, and metadata manager.
- VMs connect over sockets to exchange metadata and IO requests.
- Each SDS VM exposes local block files (for example, `5 x 1GB` files) as virtual storage blocks.
- Remote SDC clients consume and map those blocks as virtual drives through the PowerFlex-like control plane.

The current codebase is in the API/service simulation stage; distributed socket-based VM orchestration is the next major milestone.

**Status**: 7/11 Phases Complete (PHASES 0-6 ✅ Ready)

### Key Features
- 📊 **Data Models**: 11 SQLAlchemy ORM models with 8 enums, metrics, and timestamps
- 💾 **Storage Engine**: Chunk allocation, replication, capacity management, placement rules
- 📦 **Volume Operations**: Complete CRUD lifecycle with state transitions
- 🔄 **IO Simulation**: Realistic read/write patterns with latency simulation
- ⚡ **Failure & Rebuild**: Node failure detection, auto rebuild, rate limiting
- 📡 **REST API**: FastAPI endpoints for all operations (in development)
- 🔧 **CLI Tool**: Coming soon (scli commands)
- 📈 **Monitoring**: Prometheus/Grafana integration (in development)

## Quick Start

### Prerequisites
- Python 3.13+
- SQLite
- FastAPI, SQLAlchemy, Uvicorn

### Setup

```bash
# 1. Install dependencies
pip install fastapi sqlalchemy uvicorn click pydantic

# 2. Initialize database
python -c "from app.database import init_db; init_db(); print('✅ Database initialized')"

# 3. Start API server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001

# 4. (In another terminal) Start Flask GUI
python flask_gui.py  # Runs on http://localhost:5000
```

### Demo Scenarios

```bash
# Run Scenario A (Basic Deployment)
python app/scenario_a.py
```

## Service Modules (PHASES 2-5)

### PHASE 2: StorageEngine (app/services/storage_engine.py)
Handles core storage allocation and PowerFlex rules:
- **Chunk allocation** with replica placement
- **Capacity management** (thick/thin provisioning)
- **Validation functions** (pool, volume, consistency checks)
- **Health management** (pool/chunk state tracking)
- **Event logging** (audit trail)

```python
from app.services.storage_engine import StorageEngine
engine = StorageEngine(db_session)
success, msg = engine.allocate_capacity(pool, volume)
chunk_count, msg = engine.allocate_chunks(pool, volume)
```

### PHASE 3: VolumeManager (app/services/volume_manager.py)
Complete volume lifecycle management:
- **Create volume** - Allocate chunks, set up replicas
- **Map volume** - Grant SDC access with access modes
- **Unmap volume** - Revoke access
- **Extend volume** - Increase capacity
- **Delete volume** - Cleanup and deallocation
- **Query operations** - Get volume details and mappings

```python
from app.services.volume_manager import VolumeManager
mgr = VolumeManager(db_session)
success, volume, msg = mgr.create_volume(pool_id, "vol1", 100.0, "thin")
success, msg = mgr.map_volume(volume.id, sdc_id, "readWrite")
```

### PHASE 4: IOSimulator (app/services/io_simulator.py)
Workload generation and metrics aggregation:
- **Simulate reads/writes** - Random chunk selection, replica selection
- **Latency simulation** - 5-50ms per operation based on SDS load
- **Metrics aggregation** - IOPS, bandwidth, latency tracking
- **Per-resource metrics** - Volume, Pool, SDS, SDC level

```python
from app.services.io_simulator import IOSimulator
sim = IOSimulator(db_session)
success, latency = sim.simulate_volume_read(volume_id)
metrics = sim.aggregate_volume_metrics(volume_id)
```

### PHASE 4: BackgroundIOWorker (app/services/io_worker.py)
Continuous background workload generation:
- **Workload ticks** - 100ms intervals
- **Metrics aggregation** - 5s windows
- **Event logging** - 60s periodic logging
- **Thread-safe** - Runs in background without blocking

```python
from app.services.io_worker import init_io_worker, stop_io_worker
worker = init_io_worker(db_session_factory)
# Worker runs in background automatically
```

### PHASE 5: RebuildEngine (app/services/rebuild_engine.py)
Failure detection and rebuild orchestration:
- **Node failure** - Mark chunks degraded, set pool DEGRADED
- **Auto-rebuild** - Trigger rebuild, find targets, create replicas
- **Rate limiting** - Respect pool's rebuild_rate_limit_mbps
- **Progress tracking** - Track bytes rebuilt, ETA, stall detection
- **Recovery** - Mark node UP, heal chunks if replicas available

```python
from app.services.rebuild_engine import RebuildEngine
rebuild = RebuildEngine(db_session)
success, msg = rebuild.fail_sds_node(sds_id)  # Auto-triggers rebuild
success, msg = rebuild.start_rebuild(pool_id)
success, msg = rebuild.update_rebuild_progress(pool_id)
```

## API Endpoints (PHASE 6 - In Development)

Organized by resource type:

### Protection Domain
- `POST /pd/create` - Create protection domain
- `GET /pd/list` - List all PDs
- `GET /pd/{id}` - Get PD details
- `DELETE /pd/{id}` - Delete PD

### Storage Pool
- `POST /pool/create` - Create pool
- `GET /pool/list` - List pools
- `GET /pool/{id}` - Get pool details
- `GET /pool/{id}/health` - Pool health status
- `GET /pool/{id}/metrics` - Pool metrics

### SDS Node
- `POST /sds/add` - Add SDS to PD
- `GET /sds/list` - List SDS nodes
- `GET /sds/{id}` - Get SDS details
- `POST /sds/{id}/fail` - Simulate SDS failure
- `POST /sds/{id}/recover` - Recover SDS
- `GET /sds/{id}/metrics` - SDS metrics

### SDC Client
- `POST /sdc/add` - Add SDC
- `GET /sdc/list` - List SDCs
- `GET /sdc/{id}` - Get SDC details
- `GET /sdc/{id}/metrics` - SDC metrics

### Volume
- `POST /vol/create` - Create volume
- `GET /vol/list` - List volumes
- `GET /vol/{id}` - Get volume details
- `POST /vol/map` - Map to SDC
- `POST /vol/unmap` - Unmap from SDC
- `POST /vol/extend` - Extend size
- `DELETE /vol/{id}` - Delete volume
- `GET /vol/{id}/metrics` - Volume metrics

### Rebuild
- `POST /rebuild/start/{pool_id}` - Start rebuild
- `GET /rebuild/status/{pool_id}` - Get rebuild progress
- `POST /rebuild/cancel/{pool_id}` - Cancel rebuild

## PowerFlex Rules Enforced

✅ **Replication**
- 2 replicas per chunk (TWO_COPIES) on different SDS nodes
- No chunk data loss if ≥1 replica available

✅ **Capacity**
- Thick volumes reserve full size upfront
- Thin volumes allocate on-write
- No over-allocation beyond pool total

✅ **Placement**
- No two replicas on same SDS node
- Prefers different FaultSets (racks)
- Balances load across nodes

✅ **Failure**
- SDS failure automatically triggers rebuild
- Degraded chunks marked when replica lost
- Pool health transitions: OK → DEGRADED → OK

✅ **Access Control**
- Volume mapped to SDC = access granted
- Unmapped volume = access denied
- Support for read-only and read-write modes

✅ **State Machines**
- SDSNode: UP ↔ DOWN ↔ DEGRADED
- StoragePool: OK ↔ DEGRADED → OK (after rebuild)
- Volume: AVAILABLE → IN_USE → AVAILABLE
- Rebuild: IDLE → IN_PROGRESS → COMPLETED

## Documentation

- **PLANS.md** - Complete 10-phase implementation guide with technical details
- **PHASES.md** - Current phase status, progress tracking, and session logs
- **models.py** - ORM models with comprehensive docstrings
- **Service modules** - Inline documentation with examples

## Project Structure

```
powerflex_demo/
├── app/
│   ├── main.py                  # FastAPI entry point
│   ├── models.py                # SQLAlchemy models (11 models, 8 enums)
│   ├── database.py              # Database initialization
│   ├── services/                # PHASES 2-5 services
│   │   ├── storage_engine.py    # PHASE 2: Allocation & placement
│   │   ├── volume_manager.py    # PHASE 3: Volume lifecycle
│   │   ├── io_simulator.py      # PHASE 4: Workload & metrics
│   │   ├── io_worker.py         # PHASE 4: Background worker
│   │   └── rebuild_engine.py    # PHASE 5: Failure & rebuild
│   ├── api/                     # REST endpoints (PHASE 6)
│   │   ├── pd.py
│   │   ├── pool.py
│   │   ├── sds.py
│   │   ├── sdc.py
│   │   ├── volume.py
│   │   ├── rebuild.py
│   │   └── metrics.py
│   └── scenarios/               # Demo scenarios (PHASE 9)
│       ├── scenario_a.py        # Basic deployment
│       ├── scenario_b.py        # Failover & rebuild (TODO)
│       ├── scenario_c.py        # Multi-host mapping (TODO)
│       └── scenario_d.py        # Capacity exhaustion (TODO)
├── tests/                       # Validation tests (PHASE 10 - TODO)
├── templates/                   # Flask GUI templates
├── flask_gui.py                 # Flask web interface
├── PLANS.md                     # 10-phase implementation guide
├── PHASES.md                    # Phase status tracker
├── powerflex.db                 # SQLite database
└── README.md                    # This file
```

## Development Roadmap

### ✅ COMPLETE (PHASES 0-5)
- [x] Phase 0: Rules definition
- [x] Phase 1: Data models
- [x] Phase 2: Storage engine
- [x] Phase 3: Volume operations
- [x] Phase 4: IO simulation
- [x] Phase 5: Failure & rebuild

### 🟡 IN PROGRESS (PHASE 6)
- [ ] Phase 6: REST API endpoints
  - [ ] Integration of service layers with API routers
  - [ ] Error handling and validation
  - [ ] Testing of all endpoints

### ⏳ UPCOMING (PHASES 7-10)
- [ ] Phase 7: CLI tool (scli)
- [ ] Phase 8: Prometheus/Grafana monitoring
- [ ] Phase 9: Complete demo scenarios B, C, D
- [ ] Phase 10: Validation test suite

## Testing

```bash
# Run tests (when ready)
pytest tests/ -v

# Check code syntax
python -m py_compile app/services/*.py app/api/*.py

# Run linting (optional)
pylint app/
```

## Performance Considerations

- **Chunk size**: 4MB (configurable in StorageEngine)
- **IO latency**: 5-50ms simulation
- **Metrics window**: 5-second aggregation
- **Rebuild rate**: Configurable per pool (default 100 MB/s)
- **Stall detection**: 60-second timeout

## Known Limitations

1. FaultSet (rack/chassis) support is implemented but optional
2. Erasure coding (EC) replica count is 3, not fully tuned
3. Prometheus/Grafana integration not yet complete
4. CLI tool not yet implemented
5. Validation test suite not yet complete

## Version History

- **v1.0** (2/9/2026): PHASES 0-5 complete, services ready for API integration

## License

MIT

## Contributing

Contributions welcome! Currently focusing on:
- PHASE 6: REST API integration
- PHASE 7: CLI tool development
- PHASE 9: Demo scenario completion
- PHASE 10: Comprehensive testing
