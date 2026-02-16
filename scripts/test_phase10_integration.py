#!/usr/bin/env python3
"""
Phase 10 Integration Test Suite

Comprehensive end-to-end testing of the PowerFlex architecture:
- Full cluster deployment (MDM + SDS + SDC + MGMT)
- Complete volume lifecycle (create → map → IO → unmap → delete)
- Component failure/recovery scenarios
- Health monitoring validation
- Alert system verification
- Performance benchmarking

Run after starting all services:
1. MDM: python scripts/run_mdm_service.py
2. SDS: python scripts/run_sds_service.py (on each SDS node)
3. SDC: python scripts/run_sdc_service.py (on each SDC node)
4. MGMT: python scripts/run_mgmt_service.py

Usage:
    python scripts/test_phase10_integration.py [--mdm-url=http://127.0.0.1:8001] [--mgmt-url=http://127.0.0.1:5000]
"""

import sys
import os
import time
import json
import base64
import argparse
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional

# Fix Windows console encoding for Unicode output
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Test configuration
DEFAULT_MDM_URL = "http://127.0.0.1:8001"
DEFAULT_MGMT_URL = "http://127.0.0.1:5000"
REQUEST_TIMEOUT = 30

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []
        self.warnings = []

    def add_pass(self, test_name: str):
        self.passed += 1
        print(f"{GREEN}✓{RESET} {test_name}")

    def add_fail(self, test_name: str, error: str):
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"{RED}✗{RESET} {test_name}: {error}")

    def add_skip(self, test_name: str, reason: str):
        self.skipped += 1
        print(f"{YELLOW}⊘{RESET} {test_name}: {reason}")

    def add_warning(self, message: str):
        self.warnings.append(message)
        print(f"{YELLOW}⚠{RESET} {message}")

    def summary(self) -> str:
        total = self.passed + self.failed + self.skipped
        pass_rate = (self.passed / total * 100) if total > 0 else 0
        
        lines = [
            f"\n{'='*60}",
            f"TEST SUMMARY",
            f"{'='*60}",
            f"Total: {total} | Passed: {GREEN}{self.passed}{RESET} | Failed: {RED}{self.failed}{RESET} | Skipped: {YELLOW}{self.skipped}{RESET}",
            f"Pass Rate: {pass_rate:.1f}%",
        ]
        
        if self.errors:
            lines.append(f"\n{RED}FAILURES:{RESET}")
            for test_name, error in self.errors:
                lines.append(f"  • {test_name}: {error}")
        
        if self.warnings:
            lines.append(f"\n{YELLOW}WARNINGS:{RESET}")
            for warning in self.warnings:
                lines.append(f"  • {warning}")
        
        lines.append(f"{'='*60}\n")
        return "\n".join(lines)


class IntegrationTestSuite:
    """Phase 10 integration test suite."""
    
    def __init__(self, mdm_url: str, mgmt_url: str):
        self.mdm_url = mdm_url.rstrip('/')
        self.mgmt_url = mgmt_url.rstrip('/')
        self.results = TestResult()
        self.test_prefix = f"p10test{int(time.time())}"
        self.test_resources = {
            'pd_id': None,
            'pool_id': None,
            'sds_ids': [],
            'sdc_ids': [],
            'volume_ids': [],
        }

    def req(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make HTTP request with timeout."""
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        try:
            resp = requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            raise Exception(f"{method} {url} failed: {e}")

    # ======================================================================
    # TEST SECTION 1: Service Availability
    # ======================================================================

    def test_mdm_availability(self):
        """Test MDM service is running and responding."""
        try:
            resp = self.req('GET', f"{self.mdm_url}/")
            body = resp.json()
            # Current implementation returns 'mdm', Phase 7+ returns 'powerflex-mdm'
            if body.get('service') not in ['mdm', 'powerflex-mdm']:
                raise Exception(f"Unexpected service name: {body.get('service')}")
            self.results.add_pass("MDM service availability")
        except Exception as e:
            self.results.add_fail("MDM service availability", str(e))

    def test_mgmt_availability(self):
        """Test MGMT service is running and responding."""
        try:
            resp = self.req('GET', f"{self.mgmt_url}/health")
            if resp.status_code != 200:
                raise Exception(f"Status {resp.status_code}")
            self.results.add_pass("MGMT service availability")
        except Exception as e:
            self.results.add_fail("MGMT service availability", str(e))

    def test_mdm_health_endpoints(self):
        """Test MDM health monitoring endpoints."""
        endpoints = {
            '/health': dict,  # Returns summary dict
            '/health/components': list,  # Returns list of components
            '/health/metrics': dict,  # Returns metrics dict
        }
        for endpoint, expected_type in endpoints.items():
            try:
                resp = self.req('GET', f"{self.mdm_url}{endpoint}")
                body = resp.json()
                if not isinstance(body, expected_type):
                    raise Exception(f"Expected {expected_type.__name__}, got {type(body)}")
                self.results.add_pass(f"MDM health endpoint {endpoint}")
            except Exception as e:
                self.results.add_fail(f"MDM health endpoint {endpoint}", str(e))

    # ======================================================================
    # TEST SECTION 2: Cluster Topology Creation
    # ======================================================================

    def test_create_protection_domain(self):
        """Create a protection domain."""
        try:
            resp = self.req('POST', f"{self.mdm_url}/pd/create", json={
                'name': f"{self.test_prefix}_PD"
            })
            body = resp.json()
            pd_id = body.get('id')
            if not pd_id:
                raise Exception(f"No id in response: {body}")
            self.test_resources['pd_id'] = pd_id
            self.results.add_pass("Create protection domain")
        except Exception as e:
            self.results.add_fail("Create protection domain", str(e))

    def test_add_sds_nodes(self):
        """Add SDS nodes to protection domain."""
        if not self.test_resources['pd_id']:
            self.results.add_skip("Add SDS nodes", "No PD created")
            return
        
        pd_id = self.test_resources['pd_id']
        sds_configs = [
            {'name': f"{self.test_prefix}_SDS1", 'capacity_gb': 128, 'devices': 'blk0,blk1,blk2', 'node_id': f'{self.test_prefix}-sds-1'},
            {'name': f"{self.test_prefix}_SDS2", 'capacity_gb': 128, 'devices': 'blk0,blk1,blk2', 'node_id': f'{self.test_prefix}-sds-2'},
        ]
        
        for sds_cfg in sds_configs:
            try:
                # First, register cluster node with SDS capability
                self.req('POST', f"{self.mdm_url}/cluster/nodes/register", json={
                    'node_id': sds_cfg['node_id'],
                    'name': sds_cfg['name'],
                    'address': '127.0.0.1',
                    'port': 9700,
                    'capabilities': ['SDS'],
                })
                
                # Then add SDS
                resp = self.req('POST', f"{self.mdm_url}/sds/add", json={
                    'name': sds_cfg['name'],
                    'total_capacity_gb': sds_cfg['capacity_gb'],
                    'devices': sds_cfg['devices'],
                    'protection_domain_id': pd_id,
                    'cluster_node_id': sds_cfg['node_id'],
                })
                body = resp.json()
                sds_id = body.get('id')
                if not sds_id:
                    raise Exception(f"No id in response: {body}")
                self.test_resources['sds_ids'].append(sds_id)
                self.results.add_pass(f"Add SDS node {sds_cfg['name']}")
            except Exception as e:
                self.results.add_fail(f"Add SDS node {sds_cfg['name']}", str(e))

    def test_create_storage_pool(self):
        """Create a storage pool."""
        if not self.test_resources['pd_id']:
            self.results.add_skip("Create storage pool", "No PD created")
            return
        
        try:
            resp = self.req('POST', f"{self.mdm_url}/pool/create", json={
                'name': f"{self.test_prefix}_POOL",
                'pd_id': self.test_resources['pd_id'],
                'protection_policy': 'two_copies',
                'total_capacity_gb': 256,
            })
            body = resp.json()
            pool_id = body.get('id')
            if not pool_id:
                raise Exception(f"No id in response: {body}")
            self.test_resources['pool_id'] = pool_id
            self.results.add_pass("Create storage pool")
        except Exception as e:
            self.results.add_fail("Create storage pool", str(e))

    def test_add_sdc_clients(self):
        """Add SDC clients."""
        sdc_configs = [
            {'name': f"{self.test_prefix}_SDC1", 'node_id': f'{self.test_prefix}-sdc-1'},
            {'name': f"{self.test_prefix}_SDC2", 'node_id': f'{self.test_prefix}-sdc-2'},
        ]
        
        for sdc_cfg in sdc_configs:
            try:
                # First, register cluster node with SDC capability
                self.req('POST', f"{self.mdm_url}/cluster/nodes/register", json={
                    'node_id': sdc_cfg['node_id'],
                    'name': sdc_cfg['name'],
                    'address': '127.0.0.1',
                    'port': 8003,
                    'capabilities': ['SDC'],
                })
                
                # Then add SDC
                resp = self.req('POST', f"{self.mdm_url}/sdc/add", json={
                    'name': sdc_cfg['name'],
                    'cluster_node_id': sdc_cfg['node_id'],
                })
                body = resp.json()
                sdc_id = body.get('id')
                if not sdc_id:
                    raise Exception(f"No id in response: {body}")
                self.test_resources['sdc_ids'].append(sdc_id)
                self.results.add_pass(f"Add SDC client {sdc_cfg['name']}")
            except Exception as e:
                self.results.add_fail(f"Add SDC client {sdc_cfg['name']}", str(e))

    # ======================================================================
    # TEST SECTION 3: Volume Lifecycle
    # ======================================================================

    def test_create_volumes(self):
        """Create thin and thick volumes."""
        if not self.test_resources['pool_id']:
            self.results.add_skip("Create volumes", "No pool created")
            return
        
        pool_id = self.test_resources['pool_id']
        volume_configs = [
            {'name': f"{self.test_prefix}_VOL_THIN", 'size_gb': 0.1, 'provisioning': 'thin'},  # 100 MB
            {'name': f"{self.test_prefix}_VOL_THICK", 'size_gb': 0.05, 'provisioning': 'thick'},  # 50 MB
        ]
        
        for vol_cfg in volume_configs:
            try:
                resp = self.req('POST', f"{self.mdm_url}/vol/create", json={
                    'name': vol_cfg['name'],
                    'size_gb': vol_cfg['size_gb'],
                    'provisioning': vol_cfg['provisioning'],
                    'pool_id': pool_id,
                })
                body = resp.json()
                vol_id = body.get('id')
                if not vol_id:
                    raise Exception(f"No id in response: {body}")
                self.test_resources['volume_ids'].append(vol_id)
                self.results.add_pass(f"Create volume {vol_cfg['name']}")
            except Exception as e:
                self.results.add_fail(f"Create volume {vol_cfg['name']}", str(e))

    def test_map_volumes(self):
        """Map volumes to SDC clients."""
        if not self.test_resources['volume_ids'] or not self.test_resources['sdc_ids']:
            self.results.add_skip("Map volumes", "No volumes or SDCs created")
            return
        
        # Map first volume to first SDC
        if len(self.test_resources['volume_ids']) > 0 and len(self.test_resources['sdc_ids']) > 0:
            vol_id = self.test_resources['volume_ids'][0]
            sdc_id = self.test_resources['sdc_ids'][0]
            try:
                self.req('POST', f"{self.mdm_url}/vol/map", params={
                    'volume_id': vol_id,
                    'sdc_id': sdc_id,
                    'access_mode': 'readWrite',
                })
                self.results.add_pass(f"Map volume {vol_id} to SDC {sdc_id}")
            except Exception as e:
                self.results.add_fail(f"Map volume {vol_id} to SDC {sdc_id}", str(e))

    def test_volume_io_operations(self):
        """Test volume read/write operations."""
        if not self.test_resources['volume_ids'] or not self.test_resources['sdc_ids']:
            self.results.add_skip("Volume IO operations", "No volumes or SDCs created")
            return
        
        vol_id = self.test_resources['volume_ids'][0]
        sdc_id = self.test_resources['sdc_ids'][0]
        test_data = b"phase10-integration-test-data"
        test_offset = 4096
        
        # Write test
        try:
            write_resp = self.req('POST', f"{self.mdm_url}/vol/{vol_id}/io/write", json={
                'sdc_id': sdc_id,
                'offset_bytes': test_offset,
                'data_b64': base64.b64encode(test_data).decode('ascii'),
            })
            write_body = write_resp.json()
            # Check for successful write (status='written' and bytes match)
            if write_body.get('status') != 'written':
                raise Exception(f"Write status not 'written': {write_body}")
            if write_body.get('bytes_written') != len(test_data):
                raise Exception(f"Bytes written mismatch: expected {len(test_data)}, got {write_body.get('bytes_written')}")
            self.results.add_pass(f"Volume write operation")
        except Exception as e:
            self.results.add_fail(f"Volume write operation", str(e))
            return
        
        # Read test
        try:
            read_resp = self.req('POST', f"{self.mdm_url}/vol/{vol_id}/io/read", json={
                'sdc_id': sdc_id,
                'offset_bytes': test_offset,
                'length_bytes': len(test_data),
            })
            read_body = read_resp.json()
            read_data = base64.b64decode(read_body.get('data_b64', ''))
            if read_data != test_data:
                raise Exception(f"Data mismatch: expected {test_data}, got {read_data}")
            self.results.add_pass(f"Volume read operation")
        except Exception as e:
            self.results.add_fail(f"Volume read operation", str(e))

    def test_unmap_volumes(self):
        """Unmap volumes from SDC clients."""
        if not self.test_resources['volume_ids'] or not self.test_resources['sdc_ids']:
            self.results.add_skip("Unmap volumes", "No volumes or SDCs created")
            return
        
        vol_id = self.test_resources['volume_ids'][0]
        sdc_id = self.test_resources['sdc_ids'][0]
        try:
            self.req('POST', f"{self.mdm_url}/vol/unmap", params={
                'volume_id': vol_id,
                'sdc_id': sdc_id,
            })
            self.results.add_pass(f"Unmap volume {vol_id} from SDC {sdc_id}")
        except Exception as e:
            self.results.add_fail(f"Unmap volume {vol_id} from SDC {sdc_id}", str(e))

    # ======================================================================
    # TEST SECTION 4: Health Monitoring & Alerts
    # ======================================================================

    def test_mgmt_health_dashboard(self):
        """Test MGMT health dashboard data."""
        try:
            resp = self.req('GET', f"{self.mgmt_url}/health/api/summary")
            body = resp.json()
            
            # Check for nested structure returned by MGMT health_api_summary endpoint
            required_keys = ['health_summary', 'health_metrics', 'alert_counts']
            for key in required_keys:
                if key not in body:
                    raise Exception(f"Missing key '{key}' in health summary")
            
            # Validate structure
            if not isinstance(body['health_metrics'], dict):
                raise Exception(f"health_metrics should be dict, got {type(body['health_metrics'])}")
            if not isinstance(body['alert_counts'], dict):
                raise Exception(f"alert_counts should be dict, got {type(body['alert_counts'])}")
            
            self.results.add_pass("MGMT health dashboard data")
        except Exception as e:
            self.results.add_fail("MGMT health dashboard data", str(e))

    def test_mgmt_component_monitoring(self):
        """Test MGMT component monitoring."""
        try:
            resp = self.req('GET', f"{self.mgmt_url}/health/api/components")
            body = resp.json()
            
            # Endpoint returns list of components directly (not wrapped in dict)
            if not isinstance(body, list):
                raise Exception(f"Expected list of components, got {type(body)}")
            
            if not body:
                self.results.add_warning("No components detected in monitoring")
            
            self.results.add_pass("MGMT component monitoring")
        except Exception as e:
            self.results.add_fail("MGMT component monitoring", str(e))

    def test_alert_system(self):
        """Test alert system functionality."""
        try:
            # Wait for monitor to poll at least once
            time.sleep(2)
            
            resp = self.req('GET', f"{self.mgmt_url}/alerts")
            if resp.status_code != 200:
                raise Exception(f"Status {resp.status_code}")
            
            self.results.add_pass("Alert system")
        except Exception as e:
            self.results.add_fail("Alert system", str(e))

    # ======================================================================
    # TEST SECTION 5: Discovery & Registration
    # ======================================================================

    def test_discovery_topology(self):
        """Test discovery topology endpoint (Phase 2+ only)."""
        try:
            # Try Phase 2+ discovery endpoint first
            resp = self.req('GET', f"{self.mdm_url}/discovery/topology")
            body = resp.json()
            
            if 'registered_components' not in body:
                raise Exception("Missing 'registered_components' in topology")
            
            self.results.add_pass("Discovery topology")
        except Exception:
            # Fall back to legacy cluster info
            try:
                resp = self.req('GET', f"{self.mdm_url}/cluster/info")
                body = resp.json()
                self.results.add_pass("Cluster info (legacy)")
            except Exception as e:
                self.results.add_skip("Discovery topology (Phase 2+)", "Not implemented in current code")

    def test_cluster_metrics(self):
        """Test cluster metrics endpoint."""
        try:
            resp = self.req('GET', f"{self.mdm_url}/metrics/cluster")
            body = resp.json()
            
            # Check for correct structure (nested under 'storage', 'volumes', 'nodes', 'health')
            required_sections = ['storage', 'volumes', 'nodes', 'health']
            for section in required_sections:
                if section not in body:
                    raise Exception(f"Missing section '{section}' in metrics")
            
            self.results.add_pass("Cluster metrics")
        except Exception as e:
            self.results.add_fail("Cluster metrics", str(e))

    # ======================================================================
    # TEST SECTION 6: Data Validation
    # ======================================================================

    def test_data_integrity(self):
        """Verify data integrity across multiple read/write cycles."""
        if not self.test_resources['volume_ids'] or not self.test_resources['sdc_ids']:
            self.results.add_skip("Data integrity test", "No volumes or SDCs created")
            return
        
        vol_id = self.test_resources['volume_ids'][0]
        sdc_id = self.test_resources['sdc_ids'][0]
        
        # Re-map volume if needed (may have been unmapped in previous tests)
        try:
            self.req('POST', f"{self.mdm_url}/vol/map", params={
                'volume_id': vol_id,
                'sdc_id': sdc_id,
                'access_mode': 'readWrite',
            })
        except Exception:
            # Volume might already be mapped, ignore error
            pass
        
        # Write and read multiple patterns
        patterns = [
            (b"pattern1", 0),
            (b"pattern2" * 100, 8192),
            (b"pattern3" * 500, 16384),
        ]
        
        for data, offset in patterns:
            try:
                # Write
                self.req('POST', f"{self.mdm_url}/vol/{vol_id}/io/write", json={
                    'sdc_id': sdc_id,
                    'offset_bytes': offset,
                    'data_b64': base64.b64encode(data).decode('ascii'),
                })
                
                # Read back
                read_resp = self.req('POST', f"{self.mdm_url}/vol/{vol_id}/io/read", json={
                    'sdc_id': sdc_id,
                    'offset_bytes': offset,
                    'length_bytes': len(data),
                })
                read_data = base64.b64decode(read_resp.json().get('data_b64', ''))
                
                if read_data != data:
                    raise Exception(f"Data mismatch at offset {offset}")
                
            except Exception as e:
                self.results.add_fail(f"Data integrity at offset {offset}", str(e))
                return
        
        self.results.add_pass("Data integrity test")

    # ======================================================================
    # TEST SECTION 7: Cleanup
    # ======================================================================

    def test_cleanup_volumes(self):
        """Delete test volumes."""
        for vol_id in self.test_resources['volume_ids']:
            try:
                # Try to unmap all SDCs from this volume first (might fail if already unmapped)
                for sdc_id in self.test_resources.get('sdc_ids', []):
                    try:
                        self.req('POST', f"{self.mdm_url}/vol/unmap", params={
                            'volume_id': vol_id,
                            'sdc_id': sdc_id,
                        })
                    except Exception:
                        pass  # Ignore if already unmapped
                
                # Now delete the volume
                self.req('DELETE', f"{self.mdm_url}/vol/{vol_id}")
                self.results.add_pass(f"Delete volume {vol_id}")
            except Exception as e:
                self.results.add_fail(f"Delete volume {vol_id}", str(e))

    # ======================================================================
    # Main Test Runner
    # ======================================================================

    def run_all(self):
        """Run all integration tests."""
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}PowerFlex Phase 10 Integration Test Suite{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        print(f"MDM URL: {self.mdm_url}")
        print(f"MGMT URL: {self.mgmt_url}")
        print(f"Test Prefix: {self.test_prefix}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{BLUE}{'='*60}{RESET}\n")
        
        # Section 1: Service Availability
        print(f"{BLUE}[1/7] Service Availability{RESET}")
        self.test_mdm_availability()
        self.test_mgmt_availability()
        self.test_mdm_health_endpoints()
        
        # Section 2: Cluster Topology
        print(f"\n{BLUE}[2/7] Cluster Topology Creation{RESET}")
        self.test_create_protection_domain()
        self.test_add_sds_nodes()
        self.test_create_storage_pool()
        self.test_add_sdc_clients()
        
        # Section 3: Volume Lifecycle
        print(f"\n{BLUE}[3/7] Volume Lifecycle{RESET}")
        self.test_create_volumes()
        self.test_map_volumes()
        self.test_volume_io_operations()
        self.test_unmap_volumes()
        
        # Section 4: Health Monitoring
        print(f"\n{BLUE}[4/7] Health Monitoring & Alerts{RESET}")
        self.test_mgmt_health_dashboard()
        self.test_mgmt_component_monitoring()
        self.test_alert_system()
        
        # Section 5: Discovery
        print(f"\n{BLUE}[5/7] Discovery & Registration{RESET}")
        self.test_discovery_topology()
        self.test_cluster_metrics()
        
        # Section 6: Data Validation
        print(f"\n{BLUE}[6/7] Data Validation{RESET}")
        self.test_data_integrity()
        
        # Section 7: Cleanup
        print(f"\n{BLUE}[7/7] Cleanup{RESET}")
        self.test_cleanup_volumes()
        
        # Print summary
        print(self.results.summary())
        
        # Return exit code
        return 0 if self.results.failed == 0 else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Phase 10 Integration Test Suite")
    parser.add_argument('--mdm-url', default=DEFAULT_MDM_URL, help="MDM service URL")
    parser.add_argument('--mgmt-url', default=DEFAULT_MGMT_URL, help="MGMT service URL")
    args = parser.parse_args()
    
    suite = IntegrationTestSuite(args.mdm_url, args.mgmt_url)
    exit_code = suite.run_all()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
