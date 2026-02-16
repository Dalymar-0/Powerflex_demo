"""
MDM Service Launcher - Phase 10.5 Architecture Activation

Starts the MDM (Metadata Manager) service from the new mdm/ package.

This service provides:
- Protection Domain, Storage Pool, Volume management
- SDS/SDC registration and discovery
- IO authorization token generation (Phase 4)
- Health monitoring and heartbeat receiver (Phase 7)
- Cluster metrics and topology
- Token authority for secure IO operations

Usage:
    python scripts/run_mdm_service.py --host 0.0.0.0 --port 8001

Environment Variables:
    POWERFLEX_MDM_API_PORT: MDM API port (default: 8001)
    POWERFLEX_MDM_BIND_HOST: Bind address (default: 0.0.0.0)
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PowerFlex MDM control-plane service")
    parser.add_argument("--host", default=os.getenv("POWERFLEX_MDM_BIND_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("POWERFLEX_MDM_API_PORT", "8001")))
    args = parser.parse_args()
    
    print("=" * 60)
    print("PowerFlex MDM Service (Phase 1-9 Architecture)")
    print("=" * 60)
    print(f"API Address: {args.host}:{args.port}")
    print(f"Database: powerflex.db")
    print(f"Package: mdm/")
    print("=" * 60)
    
    # Set environment variables for service startup
    os.environ["POWERFLEX_MDM_API_PORT"] = str(args.port)
    os.environ["POWERFLEX_MDM_BIND_HOST"] = args.host

    # Run MDM service from new package
    uvicorn.run("mdm.service:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
