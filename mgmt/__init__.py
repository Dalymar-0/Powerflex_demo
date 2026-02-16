"""
MGMT (Management Service) — The Dashboard

User-facing control + monitoring service.
Responsibilities:
- Flask GUI (login, dashboard, volume management)
- Poll all component mgmt ports for health/stats
- Alert engine (threshold-based)
- Proxy control-plane actions to MDM
"""
