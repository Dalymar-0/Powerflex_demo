"""
SDC (Storage Data Client) — The Driver

The SDC is the data-path client running on each compute VM.
Responsibilities:
- Expose volumes via NBD-like TCP protocol (port 8005)
- Request IO tokens from MDM
- Execute authorized IO to SDS data ports
- Report heartbeats to MDM
"""
