"""
SDC Service Launcher Script - Phase 6

Launch standalone SDC service with auto-registration to MDM.

This script:
1. Registers SDC with MDM discovery API
2. Starts SDC multi-listener service (NBD + Control + Mgmt)
3. Sends periodic heartbeats to MDM
4. Handles graceful shutdown

Usage:
    python scripts/run_sdc_service.py --sdc-id 1 --address 127.0.0.1

Environment Variables:
    POWERFLEX_MDM_ADDRESS: MDM host (default: 127.0.0.1)
    POWERFLEX_MDM_PORT: MDM port (default: 8001)
    POWERFLEX_SDC_ID: SDC ID (default: 1)
    POWERFLEX_SDC_ADDRESS: SDC listen address (default: 127.0.0.1)
    POWERFLEX_CLUSTER_SECRET: Cluster secret for authentication
"""

import sys
import os
import logging
import argparse
import hashlib
import requests
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sdc.service import SDCService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def register_with_mdm(
    component_id: str,
    address: str,
    control_port: int,
    data_port: int,
    mgmt_port: int,
    mdm_address: str,
    mdm_port: int,
    cluster_secret: str = None
) -> dict:
    """
    Register SDC with MDM discovery API.
    
    Returns MDM response with cluster_secret on first registration.
    """
    register_url = f"http://{mdm_address}:{mdm_port}/discovery/register"
    
    # Compute auth token (for re-registration)
    auth_token = None
    if cluster_secret:
        auth_token = hashlib.sha256(f"{cluster_secret}{component_id}".encode()).hexdigest()
    
    payload = {
        "component_id": component_id,
        "component_type": "SDC",
        "address": address,
        "control_port": control_port,
        "data_port": data_port,
        "mgmt_port": mgmt_port,
        "metadata": {
            "nbd_port": data_port,
            "version": "0.6.0"
        }
    }
    
    if auth_token:
        payload["auth_token"] = auth_token
    
    try:
        response = requests.post(register_url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Registration failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Launch SDC service")
    parser.add_argument("--sdc-id", type=int, default=int(os.getenv("POWERFLEX_SDC_ID", "1")), help="SDC ID")
    parser.add_argument("--address", default=os.getenv("POWERFLEX_SDC_ADDRESS", "127.0.0.1"), help="Listen address")
    parser.add_argument("--nbd-port", type=int, default=8005, help="NBD server port")
    parser.add_argument("--control-port", type=int, default=8003, help="Control API port")
    parser.add_argument("--mgmt-port", type=int, default=8004, help="Management API port")
    parser.add_argument("--mdm-address", default=os.getenv("POWERFLEX_MDM_ADDRESS", "127.0.0.1"), help="MDM address")
    parser.add_argument("--mdm-port", type=int, default=int(os.getenv("POWERFLEX_MDM_PORT", "8001")), help="MDM port")
    parser.add_argument("--cluster-secret", default=os.getenv("POWERFLEX_CLUSTER_SECRET"), help="Cluster secret")
    parser.add_argument("--no-register", action="store_true", help="Skip MDM registration")
    
    args = parser.parse_args()
    
    # Generate component ID
    component_id = f"sdc-{args.address}-{args.nbd_port}"
    
    logger.info(f"Starting SDC service: {component_id}")
    logger.info(f"  SDC ID: {args.sdc_id}")
    logger.info(f"  Listen address: {args.address}")
    logger.info(f"  NBD port: {args.nbd_port}")
    logger.info(f"  Control port: {args.control_port}")
    logger.info(f"  Mgmt port: {args.mgmt_port}")
    logger.info(f"  MDM: {args.mdm_address}:{args.mdm_port}")
    
    # Register with MDM (unless --no-register)
    cluster_secret = args.cluster_secret
    
    if not args.no_register:
        try:
            logger.info("Registering with MDM...")
            
            reg_response = register_with_mdm(
                component_id=component_id,
                address=args.address,
                control_port=args.control_port,
                data_port=args.nbd_port,
                mgmt_port=args.mgmt_port,
                mdm_address=args.mdm_address,
                mdm_port=args.mdm_port,
                cluster_secret=cluster_secret
            )
            
            logger.info(f"Registration status: {reg_response.get('status')}")
            
            # Store cluster secret if first-time registration
            if reg_response.get("cluster_secret"):
                cluster_secret = reg_response["cluster_secret"]
                logger.info("Received cluster secret from MDM (store securely)")
        
        except Exception as e:
            logger.error(f"Registration failed: {e}")
            logger.warning("Continuing without registration (may affect IO operations)")
    
    # Create and start SDC service
    service = SDCService(
        sdc_id=args.sdc_id,
        sdc_component_id=component_id,
        listen_address=args.address,
        nbd_port=args.nbd_port,
        control_port=args.control_port,
        mgmt_port=args.mgmt_port,
        mdm_address=args.mdm_address,
        mdm_port=args.mdm_port,
        cluster_secret=cluster_secret
    )
    
    try:
        service.start()
        logger.info("SDC service running. Press Ctrl+C to stop.")
        service.wait()
    
    except KeyboardInterrupt:
        logger.info("Shutting down SDC service...")
        service.stop()
    
    logger.info("SDC service stopped")


if __name__ == "__main__":
    main()
