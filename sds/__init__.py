"""
SDS (Storage Data Server) — The Disk

Each SDS owns raw volume image files on local disk.
Responsibilities:
- Serve read/write IO to SDC (after token verification)
- Execute MDM replication orders
- Report heartbeats + transaction ACKs to MDM
"""
