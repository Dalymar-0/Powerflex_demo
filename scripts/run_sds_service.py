"""
SDS Service Launcher Script (Phase 5)

Simplified launcher for SDS service with sensible defaults.
Handles registration with MDM discovery to get cluster_secret.

Usage:
    python scripts/run_sds_service.py --sds-id 1 --sds-ip 10.0.1.10 --storage-root ./vm_storage/sds1

Environment variables:
    MDM_URL: MDM base URL (default: http://127.0.0.1:8001)
"""

import argparse
import os
import sys
import requests
import logging
import signal
import time

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sds.service import SDSService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def register_with_mdm(mdm_url: str, sds_ip: str, data_port: int, control_port: int, mgmt_port: int) -> dict:
    """
    Register SDS with MDM discovery to get cluster_secret.
    
    Returns:
        dict with 'cluster_secret' and 'component_id'
    """
    component_id = f"sds-{sds_ip}"
    
    payload = {
        "component_type": "sds",
        "component_id": component_id,
        "network_address": sds_ip,
        "ports": {
            "data": data_port,
            "control": control_port,
            "mgmt": mgmt_port
        },
        "metadata": {
            "version": "1.0.0",
            "capabilities": ["read", "write", "rebuild"]
        }
    }
    
    logger.info(f"Registering SDS with MDM: {mdm_url}/discovery/register")
    
    try:
        response = requests.post(
            f"{mdm_url}/discovery/register",
            json=payload,
            timeout=10
        )
        
        if response.status_code in (200, 201):
            result = response.json()
            logger.info(f"✓ Registration successful: component_id={result['component_id']}")
            return result
        else:
            logger.error(f"Registration failed: status={response.status_code}, body={response.text}")
            sys.exit(1)
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Registration request failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Launch PowerFlex SDS Service")
    
    parser.add_argument(
        "--sds-id",
        type=int,
        required=True,
        help="SDS ID from MDM (must match /sds/add response)"
    )
    parser.add_argument(
        "--sds-ip",
        type=str,
        required=True,
        help="SDS IP address (e.g., 10.0.1.10 or 127.0.0.1)"
    )
    parser.add_argument(
        "--storage-root",
        type=str,
        required=True,
        help="Storage directory (e.g., ./vm_storage/sds1)"
    )
    parser.add_argument(
        "--mdm-url",
        type=str,
        default=os.getenv("MDM_URL", "http://127.0.0.1:8001"),
        help="MDM URL (default: http://127.0.0.1:8001 or $MDM_URL)"
    )
    parser.add_argument(
        "--data-port",
        type=int,
        default=9700,
        help="Data port (default: 9700)"
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=9100,
        help="Control port (default: 9100)"
    )
    parser.add_argument(
        "--mgmt-port",
        type=int,
        default=9200,
        help="Management port (default: 9200)"
    )
    parser.add_argument(
        "--data-host",
        type=str,
        default="0.0.0.0",
        help="Data bind host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--control-host",
        type=str,
        default="0.0.0.0",
        help="Control bind host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--mgmt-host",
        type=str,
        default="0.0.0.0",
        help="Management bind host (default: 0.0.0.0)"
    )
    
    args = parser.parse_args()
    
    # 1. Register with MDM to get cluster_secret
    logger.info("Step 1: Registering with MDM...")
    registration = register_with_mdm(
        mdm_url=args.mdm_url,
        sds_ip=args.sds_ip,
        data_port=args.data_port,
        control_port=args.control_port,
        mgmt_port=args.mgmt_port
    )
    
    cluster_secret = registration["cluster_secret"]
    component_id = registration["component_id"]
    
    # 2. Create and start SDS service
    logger.info("Step 2: Starting SDS service...")
    service = SDSService(
        sds_id=args.sds_id,
        component_id=component_id,
        storage_root=args.storage_root,
        mdm_url=args.mdm_url,
        cluster_secret=cluster_secret,
        data_host=args.data_host,
        data_port=args.data_port,
        control_host=args.control_host,
        control_port=args.control_port,
        mgmt_host=args.mgmt_host,
        mgmt_port=args.mgmt_port
    )
    
    def signal_handler(signum, frame):
        logger.info(f"\nReceived signal {signum}, shutting down...")
        service.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    service.start()
    
    # Keep alive
    try:
        while service.running.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt, shutting down...")
        service.stop()


if __name__ == "__main__":
    main()
