"""
MGMT Service Launcher (Phase 9)

Starts the PowerFlex Management GUI service.

This service provides:
- Web-based dashboard for cluster monitoring
- Real-time health monitoring via background thread
- Alert management and visualization
- Volume/Pool/SDS/SDC management interface

Architecture:
-------------
- Flask web server (port 5000)
- Background component monitor (polls MDM every 10s)
- SQLite database (mgmt.db) for alerts and caching

Usage:
------
python scripts/run_mgmt_service.py

Environment Variables:
----------------------
POWERFLEX_MDM_BASE_URL: MDM HTTP API base URL (default: http://127.0.0.1:8001)
POWERFLEX_GUI_PORT: Flask server port (default: 5000)
POWERFLEX_GUI_BIND_HOST: Flask bind address (default: 0.0.0.0)
POWERFLEX_GUI_DEBUG: Enable Flask debug mode (default: false)
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mgmt.database import init_db as init_mgmt_database
from mgmt.service import app


def main():
    """Main entrypoint for MGMT service."""
    
    print("=" * 60)
    print("PowerFlex Management GUI Service")
    print("=" * 60)
    
    # Configuration
    mdm_base_url = os.getenv("POWERFLEX_MDM_BASE_URL", "http://127.0.0.1:8001")
    bind_host = os.getenv("POWERFLEX_GUI_BIND_HOST", "0.0.0.0")
    port = int(os.getenv("POWERFLEX_GUI_PORT", "5000"))
    debug = os.getenv("POWERFLEX_GUI_DEBUG", "false").lower() in {"true", "1", "yes"}
    
    print(f"MDM API: {mdm_base_url}")
    print(f"Bind Address: {bind_host}:{port}")
    print(f"Debug Mode: {debug}")
    
    # Initialize database
    print("\nInitializing MGMT database...")
    try:
        init_mgmt_database()
        print("✓ MGMT database ready (mgmt.db)")
    except Exception as e:
        print(f"✗ Database initialization failed: {e}")
        return 1
    
    # Component monitor is initialized automatically in service.py
    print("✓ Component monitor started (background thread)")
    print("  - Polling interval: 10 seconds")
    print("  - Cache TTL: 30 seconds")
    
    print("\n" + "=" * 60)
    print(f"MGMT GUI available at: http://{bind_host}:{port}")
    print("=" * 60)
    print("\nEndpoints:")
    print(f"  • Health Dashboard: http://{bind_host}:{port}/health")
    print(f"  • Alerts: http://{bind_host}:{port}/alerts")
    print(f"  • Volumes: http://{bind_host}:{port}/volume")
    print(f"  • Pools: http://{bind_host}:{port}/pool")
    print(f"  • SDS Nodes: http://{bind_host}:{port}/sds")
    print(f"  • SDC Nodes: http://{bind_host}:{port}/sdc")
    print(f"  • Metrics: http://{bind_host}:{port}/metrics")
    
    print("\nMonitoring:")
    print("  • Health data cached from MDM (auto-refresh every 10s)")
    print("  • Alerts generated for component failures")
    print("  • Dashboard auto-refreshes every 10s")
    
    print("\nPress Ctrl+C to stop\n")
    
    try:
        # Start Flask app
        app.run(
            host=bind_host,
            port=port,
            debug=debug,
            use_reloader=False  # Avoid double monitor thread startup
        )
    except KeyboardInterrupt:
        print("\n\nShutting down MGMT service...")
        # Monitor cleanup registered via atexit in service.py
        print("✓ Component monitor stopped")
        print("✓ MGMT service stopped")
        return 0
    except Exception as e:
        print(f"\n\nError running MGMT service: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
