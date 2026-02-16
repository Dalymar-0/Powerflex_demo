# Cleanup Analysis — Obsolete Files & Database Locations
**Generated:** February 13, 2026  
**Status:** Post-restructure cleanup needed

---

## 🗑️ OBSOLETE Files & Folders

### 1. **app/** Directory (ENTIRE FOLDER OBSOLETE)
**Status:** ❌ **DELETE ENTIRE FOLDER**  
**Reason:** Old monolithic structure, completely replaced by mdm/, sds/, sdc/, mgmt/, shared/

**Evidence:**
- Project restructured in Phase 1 (see IMPLEMENTATION_STATUS.md)
- New structure: mdm/, sds/, sdc/, mgmt/, shared/ are the active components
- app/ contains old files: main.py, mdm_service.py, sdc_service.py, logic.py, etc.

**Impact of deletion:**
- ⚠️ **WARNING:** Some files still import from app/:
  ```
  mdm/logic.py:221                    → from app.models import SDCClient
  mdm/startup_profile.py:6            → from app.config import DATA_PLANE_BASE_PORT...
  mdm/services/rebuild_engine.py      → from app.models import Volume (4 occurrences)
  mdm/services/volume_manager.py      → from app.models import Replica, SDSNode, Chunk (3 occurrences)
  sdc/data_handler.py:9               → from app.distributed.sdc_socket_client import SDCSocketClient
  scripts/run_gui_service.py:4-5      → from app.config, app.startup_profile
  scripts/run_sds_socket_node.py:2    → from app.distributed.sds_socket_server
  scripts/socket_io_demo.py:5         → from app.distributed.sdc_socket_client
  ```

**Action Required BEFORE deletion:**
1. Fix imports in mdm/ files (replace `from app.models` → `from mdm.models`)
2. Fix imports in sdc/ files (replace `from app.distributed` → `from shared` or `sdc/`)
3. Fix scripts (replace `from app.` → `from mdm.` or `from mgmt.`)
4. Then DELETE entire app/ folder

---

### 2. **flask_gui.py** (Root Level)
**Status:** ❌ **DELETE**  
**Reason:** Replaced by mgmt/service.py

**Evidence:**
- Old Flask GUI implementation (pre-Phase 9)
- New MGMT service: mgmt/service.py (Flask app with full features)
- MGMT tests passing (4/4) using mgmt/service.py, not flask_gui.py

**Action:** DELETE flask_gui.py

---

### 3. **templates/** (Root Level)
**Status:** ❌ **DELETE ENTIRE FOLDER**  
**Reason:** Replaced by mgmt/templates/

**Evidence:**
- Root templates/ has 10 files:
  ```
  dashboard.html, index.html, metrics.html, pd_list.html, pool_list.html,
  rebuild.html, sdc_list.html, sds_list.html, status.html, volume_list.html
  ```
- mgmt/templates/ has 12 files (same 10 + alerts_list.html + health_dashboard.html)
- mgmt/templates/ is the active set used by mgmt/service.py

**Action:** DELETE templates/ folder

---

### 4. **Obsolete Scripts**

**a) run_gui_service.py**
**Status:** ⚠️ **FIX IMPORTS or DELETE**  
**Reason:** Uses old app/ imports
```python
# Current (BROKEN):
from app.config import GUI_PORT, MDM_BASE_URL
from app.startup_profile import StartupProfile, validate_gui_profile

# Should be:
from mgmt.config import GUI_PORT
from mgmt.database import init_db
# Or just use: python mgmt/service.py
```
**Action:** Either fix imports OR delete (mgmt/service.py can be run directly)

**b) run_sds_socket_node.py**
**Status:** ⚠️ **FIX IMPORTS or DELETE**  
**Reason:** Uses old app/ imports
```python
# Current (BROKEN):
from app.distributed.sds_socket_server import SDSSocketServer

# Should be:
from sds.data_handler import DataHandler
```
**Action:** Fix imports or delete (Phase 5 has sds/service.py as replacement)

**c) socket_io_demo.py**
**Status:** ❌ **DELETE**  
**Reason:** Demo/test script using old app/ structure
**Action:** DELETE (not part of production system)

---

### 5. **Old Test Scripts (Pre-Integration Tests)**

**Status:** ⚠️ **REVIEW THEN DELETE**

**Potentially obsolete tests:**
- test_mdm_restructured.py (Phase 1 test, now superseded by test_integration.py)
- test_new_architecture.py (Phase 1-2 test, now superseded)
- test_phase10_integration.py (Specific phase test, now superseded)
- test_phase2_discovery.py (Specific phase test, now superseded)
- test_phase3_mgmt_db.py (Specific phase test, now superseded)
- test_phase4_tokens.py (Specific phase test, now superseded)
- test_phase7_health.py (Specific phase test, now superseded)
- test_phase8_sdc_io.py (Specific phase test, now superseded)
- test_phase9_mgmt.py (Specific phase test, now superseded)

**Keep:**
- test_health_components.py (Still used for health monitoring validation)
- test_integration.py (if exists - this is the main 25-test suite)

**Action:** Review each test, check if covered by scripts/test_integration.py, then DELETE obsolete ones

---

### 6. **Utility Scripts (KEEP but need review)**

**Keep:**
- bootstrap_minimal_topology.py (Still useful for demo setup)
- validate_demo_ready.py (Still useful for validation)
- run_mdm_service.py (Launcher for MDM)
- run_mgmt_service.py (Launcher for MGMT)
- run_sdc_service.py (Launcher for SDC)
- run_sds_service.py (Launcher for SDS)
- sdc_datastore_writer.py (Utility, may be needed)

---

## 💾 DATABASE Location Issues

### **PROBLEM:** Databases at root level, should be in component folders

### Current State:
```
Powerflex_demo/
├── powerflex.db        ← At root (bad)
├── mgmt.db             ← At root (bad)
├── mdm/
│   ├── database.py     → DATABASE_URL = "sqlite:///./powerflex.db"
│   └── ...
├── mgmt/
│   ├── database.py     → DATABASE_URL = "sqlite:///./mgmt.db"
│   └── ...
```

### Issue:
- **Database files mixed with code at root level** (messy)
- **Component databases not isolated** (violates separation principle)
- **Hard to deploy to separate VMs** (DB paths not component-relative)

---

## ✅ RECOMMENDED Database Location Strategy

### **Option A: Component-Local Databases (RECOMMENDED for multi-VM)**

**Structure:**
```
Powerflex_demo/
├── mdm/
│   ├── data/
│   │   └── powerflex.db      ← MDM database in mdm/data/
│   ├── database.py           → DATABASE_URL = "sqlite:///mdm/data/powerflex.db"
│   └── ...
├── mgmt/
│   ├── data/
│   │   └── mgmt.db           ← MGMT database in mgmt/data/
│   ├── database.py           → DATABASE_URL = "sqlite:///mgmt/data/mgmt.db"
│   └── ...
├── sds/
│   ├── data/
│   │   └── sds_local.db      ← SDS database in sds/data/
│   └── ...
├── sdc/
│   ├── data/
│   │   ├── sdc_chunks.db     ← SDC databases in sdc/data/
│   │   └── sdc_local.db
│   └── ...
```

**Benefits:**
- ✅ Clear ownership (each component owns its data/ folder)
- ✅ Easy to deploy (copy mdm/ folder to VM, includes DB)
- ✅ Follows component isolation principle
- ✅ Gitignore: `*/data/` to exclude all databases

**Implementation:**
```python
# mdm/database.py (BEFORE)
DATABASE_URL = "sqlite:///./powerflex.db"

# mdm/database.py (AFTER)
import os
from pathlib import Path

# Ensure data directory exists
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/powerflex.db"
```

---

### **Option B: Centralized Data Folder (CURRENT, acceptable for single-host)**

**Structure:**
```
Powerflex_demo/
├── data/
│   ├── powerflex.db          ← All databases in data/
│   ├── mgmt.db
│   ├── sds_local.db
│   ├── sdc_chunks.db
│   └── sdc_local.db
├── mdm/
│   ├── database.py           → DATABASE_URL = "sqlite:///./data/powerflex.db"
│   └── ...
├── mgmt/
│   ├── database.py           → DATABASE_URL = "sqlite:///./data/mgmt.db"
│   └── ...
```

**Benefits:**
- ✅ All databases in one place (easy to backup)
- ✅ Single .gitignore entry: `data/`
- ⚠️ Still acceptable for single-host deployment

**Con:**
- ❌ Harder to deploy to separate VMs (need to plumb DB paths)

**Implementation:**
```python
# mdm/database.py (BEFORE)
DATABASE_URL = "sqlite:///./powerflex.db"

# mdm/database.py (AFTER)
import os
from pathlib import Path

# Ensure data directory exists (at project root)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/powerflex.db"
```

---

## 🎯 RECOMMENDED Cleanup Actions

### **Phase 1: Fix Import Dependencies (MUST DO FIRST)**

**1. Fix mdm/ imports:**
```python
# mdm/logic.py:221
- from app.models import SDCClient
+ from mdm.models import SDCClient

# mdm/startup_profile.py:6
- from app.config import DATA_PLANE_BASE_PORT, MDM_API_PORT, SDC_SERVICE_PORT, GUI_PORT
+ from mdm.config import DATA_PLANE_BASE_PORT, MDM_API_PORT, SDC_SERVICE_PORT, GUI_PORT

# mdm/services/rebuild_engine.py (4 occurrences)
- from app.models import Volume
+ from mdm.models import Volume

# mdm/services/volume_manager.py (3 occurrences)
- from app.models import Replica, SDSNode, Chunk
+ from mdm.models import Replica, SDSNode, Chunk
```

**2. Fix sdc/ imports:**
```python
# sdc/data_handler.py:9
- from app.distributed.sdc_socket_client import SDCSocketClient
+ from shared.sdc_socket_client import SDCSocketClient
# OR
+ from sdc.data_client import DataClient
```

**3. Fix scripts/ imports:**
```python
# scripts/run_gui_service.py:4-5
- from app.config import GUI_PORT, MDM_BASE_URL
- from app.startup_profile import StartupProfile, validate_gui_profile
+ # Just run: python mgmt/service.py
+ # Or delete this script

# scripts/run_sds_socket_node.py:2
- from app.distributed.sds_socket_server import SDSSocketServer
+ from sds.data_handler import DataHandler

# scripts/socket_io_demo.py:5
- DELETE THIS FILE (demo only)
```

---

### **Phase 2: Move Database Files (CHOOSE Option A or B)**

**Option A (Component-Local):**
```powershell
# Create data directories
New-Item -ItemType Directory -Path "mdm\data" -Force
New-Item -ItemType Directory -Path "mgmt\data" -Force

# Move databases
Move-Item -Path "powerflex.db" -Destination "mdm\data\powerflex.db"
Move-Item -Path "mgmt.db" -Destination "mgmt\data\mgmt.db"

# Update database.py files (see code above)
```

**Option B (Centralized):**
```powershell
# Create data directory
New-Item -ItemType Directory -Path "data" -Force

# Move databases
Move-Item -Path "powerflex.db" -Destination "data\powerflex.db"
Move-Item -Path "mgmt.db" -Destination "data\mgmt.db"

# Update database.py files (see code above)
```

---

### **Phase 3: Delete Obsolete Files**

```powershell
# Delete obsolete folders
Remove-Item -Recurse -Force "app"           # OLD monolithic structure
Remove-Item -Recurse -Force "templates"     # OLD templates (use mgmt/templates/)

# Delete obsolete root files
Remove-Item -Force "flask_gui.py"           # OLD GUI (use mgmt/service.py)

# Delete obsolete scripts
Remove-Item -Force "scripts\socket_io_demo.py"

# Delete obsolete test scripts (after verifying coverage in test_integration.py)
Remove-Item -Force "scripts\test_mdm_restructured.py"
Remove-Item -Force "scripts\test_new_architecture.py"
Remove-Item -Force "scripts\test_phase10_integration.py"
Remove-Item -Force "scripts\test_phase2_discovery.py"
Remove-Item -Force "scripts\test_phase3_mgmt_db.py"
Remove-Item -Force "scripts\test_phase4_tokens.py"
Remove-Item -Force "scripts\test_phase7_health.py"
Remove-Item -Force "scripts\test_phase8_sdc_io.py"
Remove-Item -Force "scripts\test_phase9_mgmt.py"
```

---

### **Phase 4: Update .gitignore**

```gitignore
# Database files (Option A: component-local)
mdm/data/
mgmt/data/
sds/data/
sdc/data/

# OR (Option B: centralized)
data/

# Obsolete (already removed)
# app/
# templates/
# flask_gui.py

# Keep existing
.venv/
__pycache__/
*.pyc
.cluster_secret.*
vm_storage/
```

---

## 📊 Impact Summary

### Files to Delete:
- **1 folder:** app/ (entire old structure)
- **1 folder:** templates/ (old GUI templates)
- **1 root file:** flask_gui.py
- **10 test scripts:** Phase-specific tests (superseded by integration tests)
- **1 demo script:** socket_io_demo.py

### Files to Fix:
- **9 Python files:** Fix imports from app/ → mdm/ or shared/
- **2 database.py files:** Update DATABASE_URL paths

### Files to Move:
- **2 databases:** powerflex.db, mgmt.db (to component folders or data/)

### Expected Result:
- ✅ Clean project structure (no obsolete code)
- ✅ Clear component ownership (each component owns its data/)
- ✅ Ready for multi-VM deployment (no cross-dependencies)
- ✅ Follows all 10 design principles from REFORM_PLAN.md

---

## ⚠️ WARNINGS

1. **DO NOT delete app/ until fixing imports** - Will break mdm/ and sdc/
2. **Backup databases before moving** - Copy powerflex.db and mgmt.db to safe location
3. **Test after each phase** - Run `scripts/test_integration.py` after fixes
4. **Update documentation** - Fix any references to app/ in docs/

---

## 🎯 Recommended Sequence

**Today (30-60 minutes):**
1. Backup databases (copy powerflex.db → powerflex.db.backup)
2. Fix imports (Phase 1) - 9 files to edit
3. Test: `python scripts/test_integration.py` (should still be 24/25 passing)
4. Move databases (Phase 2) - Choose Option A or B
5. Test again

**Next session (15-30 minutes):**
6. Delete obsolete files (Phase 3) - Use PowerShell commands above
7. Update .gitignore (Phase 4)
8. Final test: `python scripts/test_integration.py`
9. Update README.md to remove references to old structure

**Result:** Clean, component-based architecture ready for Phase 14 (multi-VM deployment)
