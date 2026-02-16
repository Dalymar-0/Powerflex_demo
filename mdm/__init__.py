"""
MDM (Metadata Manager) — The Brain

The MDM is the single source of truth for all cluster metadata.
Responsibilities:
- Volume/Pool/PD/SDS/SDC CRUD operations
- IO plan generation + token signing
- Chunk placement decisions
- Rebuild orchestration
- Component discovery registry
- Heartbeat monitoring
"""
