"""
Discovery Client (Phase 2)

Shared utility for components to register with MDM discovery registry.
Used by SDS, SDC, and MGMT on startup to join the cluster and discover peers.
"""

import requests
import hashlib
import json
import logging
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)


class DiscoveryClient:
    """
    Client for MDM discovery & registration service.
    
    Usage:
        client = DiscoveryClient(
            component_id="sds-10.0.1.10",
            component_type="SDS",
            mdm_url="http://10.0.1.1:8001"
        )
        
        # First-time registration
        client.register(
            address="10.0.1.10",
            control_port=9100,
            data_port=9700,
            mgmt_port=9200,
            metadata={"devices": ["sda", "sdb"], "capacity_gb": 512}
        )
        
        # Subsequent registrations (after restart)
        client.register(address="10.0.1.10", ...)  # Uses stored cluster_secret
        
        # Discover peers
        sds_nodes = client.get_peers("SDS")
        topology = client.get_topology()
    """
    
    def __init__(
        self,
        component_id: str,
        component_type: str,
        mdm_url: str,
        secret_file: Optional[str] = None
    ):
        """
        Initialize discovery client.
        
        Args:
            component_id: Unique component identifier (e.g., 'sds-10.0.1.10')
            component_type: Component type ('MDM', 'SDS', 'SDC', 'MGMT')
            mdm_url: MDM base URL (e.g., 'http://10.0.1.1:8001')
            secret_file: Path to store cluster_secret (default: ./.cluster_secret)
        """
        self.component_id = component_id
        self.component_type = component_type.upper()
        self.mdm_url = mdm_url.rstrip("/")
        self.secret_file = Path(secret_file or ".cluster_secret")
        self.cluster_secret: Optional[str] = None
        self.cluster_name: Optional[str] = None
        
        # Load existing cluster_secret if available
        self._load_secret()
    
    def _load_secret(self):
        """Load cluster_secret from local storage"""
        if self.secret_file.exists():
            try:
                data = json.loads(self.secret_file.read_text())
                self.cluster_secret = data.get("cluster_secret")
                self.cluster_name = data.get("cluster_name")
                logger.info(f"Loaded cluster_secret from {self.secret_file}")
            except Exception as e:
                logger.warning(f"Failed to load cluster_secret: {e}")
    
    def _save_secret(self, cluster_secret: str, cluster_name: str):
        """Save cluster_secret to local storage"""
        try:
            self.secret_file.write_text(json.dumps({
                "cluster_secret": cluster_secret,
                "cluster_name": cluster_name,
                "component_id": self.component_id
            }, indent=2))
            self.secret_file.chmod(0o600)  # Restrict to owner only
            self.cluster_secret = cluster_secret
            self.cluster_name = cluster_name
            logger.info(f"Saved cluster_secret to {self.secret_file}")
        except Exception as e:
            logger.error(f"Failed to save cluster_secret: {e}")
            raise
    
    def _compute_auth_token(self) -> Optional[str]:
        """Compute authentication token from stored cluster_secret"""
        if not self.cluster_secret:
            return None
        return hashlib.sha256(
            f"{self.cluster_secret}{self.component_id}".encode()
        ).hexdigest()
    
    def register(
        self,
        address: str,
        control_port: Optional[int] = None,
        data_port: Optional[int] = None,
        mgmt_port: Optional[int] = None,
        metadata: Optional[Dict] = None,
        timeout: int = 10
    ) -> Dict:
        """
        Register component with MDM discovery registry.
        
        On first registration, MDM returns cluster_secret which is stored locally.
        On subsequent registrations, uses stored cluster_secret for authentication.
        
        Args:
            address: Component IP address
            control_port: Control plane port
            data_port: Data plane port (SDS, SDC only)
            mgmt_port: Management plane port
            metadata: Component-specific metadata (devices, capacity, etc.)
            timeout: Request timeout in seconds
        
        Returns:
            Registration response dict with status, cluster_name, etc.
        
        Raises:
            requests.RequestException: On network errors
            ValueError: On auth failure
        """
        payload = {
            "component_id": self.component_id,
            "component_type": self.component_type,
            "address": address,
            "control_port": control_port,
            "data_port": data_port,
            "mgmt_port": mgmt_port,
            "metadata": metadata,
            "auth_token": self._compute_auth_token()
        }
        
        url = f"{self.mdm_url}/discovery/register"
        
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            
            # Store cluster_secret on first registration
            if result.get("status") == "registered" and result.get("cluster_secret"):
                self._save_secret(result["cluster_secret"], result["cluster_name"])
            
            # Update cluster_name if returned
            if result.get("cluster_name"):
                self.cluster_name = result["cluster_name"]
            
            logger.info(f"Registration {result['status']}: {result['message']}")
            return result
            
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                logger.error("Authentication failed. Cluster secret may be invalid.")
                raise ValueError("Registration failed: Invalid authentication")
            logger.error(f"Registration failed: HTTP {e.response.status_code}")
            raise
        except requests.RequestException as e:
            logger.error(f"Registration failed: {e}")
            raise
    
    def get_topology(self, timeout: int = 10) -> Dict:
        """
        Fetch complete cluster topology from MDM.
        
        Returns:
            Dict with cluster_name and list of all components
        """
        url = f"{self.mdm_url}/discovery/topology"
        
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch topology: {e}")
            raise
    
    def get_peers(self, component_type: str, timeout: int = 10) -> List[Dict]:
        """
        Get list of all components of a specific type.
        
        Args:
            component_type: 'MDM', 'SDS', 'SDC', or 'MGMT'
        
        Returns:
            List of component info dicts
        """
        url = f"{self.mdm_url}/discovery/peers/{component_type.upper()}"
        
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch peers: {e}")
            raise
    
    def heartbeat(self, timeout: int = 5) -> Dict:
        """
        Send heartbeat to MDM to indicate liveness.
        Should be called periodically by long-running components.
        
        Returns:
            Heartbeat acknowledgment
        """
        url = f"{self.mdm_url}/discovery/heartbeat/{self.component_id}"
        
        try:
            response = requests.post(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.warning(f"Heartbeat failed: {e}")
            raise
    
    def unregister(self, timeout: int = 5) -> Dict:
        """
        Unregister component from MDM (graceful shutdown).
        Should be called before component exits.
        
        Returns:
            Unregistration confirmation
        """
        url = f"{self.mdm_url}/discovery/unregister/{self.component_id}"
        
        try:
            response = requests.delete(url, timeout=timeout)
            response.raise_for_status()
            logger.info(f"Unregistered from cluster: {self.component_id}")
            return response.json()
        except requests.RequestException as e:
            logger.warning(f"Unregistration failed: {e}")
            raise


def register_on_startup(
    component_id: str,
    component_type: str,
    mdm_url: str,
    address: str,
    control_port: Optional[int] = None,
    data_port: Optional[int] = None,
    mgmt_port: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> DiscoveryClient:
    """
    Convenience function for one-shot registration on component startup.
    
    Usage:
        client = register_on_startup(
            component_id="sds-10.0.1.10",
            component_type="SDS",
            mdm_url="http://10.0.1.1:8001",
            address="10.0.1.10",
            control_port=9100,
            data_port=9700,
            mgmt_port=9200,
            metadata={"capacity_gb": 512}
        )
    
    Returns:
        Initialized DiscoveryClient (can be used for subsequent operations)
    """
    client = DiscoveryClient(component_id, component_type, mdm_url)
    client.register(
        address=address,
        control_port=control_port,
        data_port=data_port,
        mgmt_port=mgmt_port,
        metadata=metadata
    )
    return client
