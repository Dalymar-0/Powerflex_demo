#!/usr/bin/env python3
"""
Pre-Deployment Validation Script for Phase 14

Validates VM requirements, network connectivity, and prerequisites
before starting multi-VM deployment.

Usage:
    python deployment/pre_deployment_check.py deployment/cluster_config.yaml
"""

import sys
import yaml
import socket
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Tuple


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_section(title: str):
    """Print section header"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{title:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


def print_check(name: str, passed: bool, message: str = ""):
    """Print check result"""
    if passed:
        print(f"  {Colors.GREEN}✓{Colors.END} {name}")
        if message:
            print(f"    {Colors.GREEN}{message}{Colors.END}")
    else:
        print(f"  {Colors.RED}✗{Colors.END} {name}")
        if message:
            print(f"    {Colors.RED}{message}{Colors.END}")


def check_ping(ip: str, timeout: int = 2) -> Tuple[bool, str]:
    """Check if host is reachable via ping"""
    try:
        # Windows vs Unix ping syntax
        if sys.platform == 'win32':
            result = subprocess.run(
                ['ping', '-n', '1', '-w', str(timeout * 1000), ip],
                capture_output=True,
                timeout=timeout + 1
            )
        else:
            result = subprocess.run(
                ['ping', '-c', '1', '-W', str(timeout), ip],
                capture_output=True,
                timeout=timeout + 1
            )
        
        if result.returncode == 0:
            return True, "Host reachable"
        else:
            return False, "Host unreachable"
    except subprocess.TimeoutExpired:
        return False, "Ping timeout"
    except Exception as e:
        return False, f"Ping failed: {e}"


def check_port(ip: str, port: int, timeout: int = 2) -> Tuple[bool, str]:
    """Check if port is open on host"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        
        if result == 0:
            return True, f"Port {port} open"
        else:
            return False, f"Port {port} closed"
    except socket.timeout:
        return False, f"Port {port} timeout"
    except Exception as e:
        return False, f"Port check failed: {e}"


def check_ssh(ip: str, user: str, port: int = 22) -> Tuple[bool, str]:
    """Check if SSH is accessible"""
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes', 
             '-p', str(port), f'{user}@{ip}', 'echo test'],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return True, "SSH accessible"
        else:
            return False, "SSH not accessible (try ssh-copy-id)"
    except subprocess.TimeoutExpired:
        return False, "SSH timeout"
    except FileNotFoundError:
        return False, "SSH client not found"
    except Exception as e:
        return False, f"SSH check failed: {e}"


def validate_config(config_path: str) -> Dict:
    """Load and validate configuration file"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        print(f"{Colors.RED}Config file not found: {config_path}{Colors.END}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"{Colors.RED}Invalid YAML: {e}{Colors.END}")
        sys.exit(1)


def check_local_prerequisites():
    """Check local machine prerequisites"""
    print_section("Local Machine Prerequisites")
    
    checks = []
    
    # Check Python version
    import sys
    python_version = sys.version_info
    python_ok = python_version >= (3, 10)
    checks.append(('Python 3.10+', python_ok, f"Version: {python_version.major}.{python_version.minor}.{python_version.micro}"))
    
    # Check required Python packages
    try:
        import yaml
        checks.append(('PyYAML installed', True, ""))
    except ImportError:
        checks.append(('PyYAML installed', False, "pip install pyyaml"))
    
    # Check SSH client
    ssh_ok = subprocess.run(['ssh', '-V'], capture_output=True).returncode == 0
    checks.append(('SSH client available', ssh_ok, ""))
    
    # Check git
    git_ok = subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    checks.append(('Git installed', git_ok, ""))
    
    # Print results
    for name, passed, message in checks:
        print_check(name, passed, message)
    
    return all(check[1] for check in checks)


def check_network(config: Dict):
    """Check network connectivity to all VMs"""
    print_section("Network Connectivity")
    
    all_passed = True
    
    # Check MDM
    print(f"{Colors.BOLD}MDM ({config['mdm']['ip']}){Colors.END}")
    ping_ok, ping_msg = check_ping(config['mdm']['ip'])
    print_check(f"Ping {config['mdm']['ip']}", ping_ok, ping_msg)
    all_passed = all_passed and ping_ok
    
    # Check SDS nodes
    for i, sds in enumerate(config['sds_nodes'], 1):
        print(f"\n{Colors.BOLD}SDS{i} ({sds['ip']}){Colors.END}")
        ping_ok, ping_msg = check_ping(sds['ip'])
        print_check(f"Ping {sds['ip']}", ping_ok, ping_msg)
        all_passed = all_passed and ping_ok
    
    # Check SDC nodes
    for i, sdc in enumerate(config['sdc_nodes'], 1):
        print(f"\n{Colors.BOLD}SDC{i} ({sdc['ip']}){Colors.END}")
        ping_ok, ping_msg = check_ping(sdc['ip'])
        print_check(f"Ping {sdc['ip']}", ping_ok, ping_msg)
        all_passed = all_passed and ping_ok
    
    return all_passed


def check_ssh_access(config: Dict):
    """Check SSH access to all VMs"""
    print_section("SSH Access")
    
    all_passed = True
    
    # Check MDM
    print(f"{Colors.BOLD}MDM ({config['mdm']['ip']}){Colors.END}")
    ssh_ok, ssh_msg = check_ssh(config['mdm']['ip'], config['mdm']['ssh_user'])
    print_check(f"SSH to {config['mdm']['ssh_user']}@{config['mdm']['ip']}", ssh_ok, ssh_msg)
    all_passed = all_passed and ssh_ok
    
    # Check SDS nodes
    for i, sds in enumerate(config['sds_nodes'], 1):
        print(f"\n{Colors.BOLD}SDS{i} ({sds['ip']}){Colors.END}")
        ssh_ok, ssh_msg = check_ssh(sds['ip'], sds['ssh_user'])
        print_check(f"SSH to {sds['ssh_user']}@{sds['ip']}", ssh_ok, ssh_msg)
        all_passed = all_passed and ssh_ok
    
    # Check SDC nodes
    for i, sdc in enumerate(config['sdc_nodes'], 1):
        print(f"\n{Colors.BOLD}SDC{i} ({sdc['ip']}){Colors.END}")
        ssh_ok, ssh_msg = check_ssh(sdc['ip'], sdc['ssh_user'])
        print_check(f"SSH to {sdc['ssh_user']}@{sdc['ip']}", ssh_ok, ssh_msg)
        all_passed = all_passed and ssh_ok
    
    return all_passed


def check_configuration(config: Dict):
    """Validate configuration values"""
    print_section("Configuration Validation")
    
    checks = []
    
    # Check cluster secret
    secret_ok = config['cluster']['cluster_secret'] != 'CHANGE_ME_GENERATE_NEW_SECRET'
    checks.append(('Cluster secret set', secret_ok, "Run: python -c \"import secrets; print(secrets.token_hex(32))\""))
    
    # Check unique IPs
    all_ips = [config['mdm']['ip']]
    all_ips.extend([sds['ip'] for sds in config['sds_nodes']])
    all_ips.extend([sdc['ip'] for sdc in config['sdc_nodes']])
    unique_ips = len(all_ips) == len(set(all_ips))
    checks.append(('All IPs unique', unique_ips, f"Found {len(set(all_ips))} unique IPs out of {len(all_ips)}"))
    
    # Check SDS count
    sds_count_ok = len(config['sds_nodes']) >= 2
    checks.append(('At least 2 SDS nodes', sds_count_ok, f"Found {len(config['sds_nodes'])} SDS nodes"))
    
    # Check port conflicts
    mdm_ports = {config['mdm']['port']}
    sds_ports = {sds['data_port'] for sds in config['sds_nodes']}
    sds_ports.update({sds['control_port'] for sds in config['sds_nodes']})
    sds_ports.update({sds['mgmt_port'] for sds in config['sds_nodes']})
    sdc_ports = {sdc['nbd_port'] for sdc in config['sdc_nodes']}
    sdc_ports.update({sdc['control_port'] for sdc in config['sdc_nodes']})
    sdc_ports.update({sdc['mgmt_port'] for sdc in config['sdc_nodes']})
    
    no_conflicts = len(mdm_ports & sds_ports & sdc_ports) == 0
    checks.append(('No port conflicts', no_conflicts, ""))
    
    # Print results
    for name, passed, message in checks:
        print_check(name, passed, message)
    
    return all(check[1] for check in checks)


def print_summary(results: Dict[str, bool]):
    """Print final summary"""
    print_section("Pre-Deployment Summary")
    
    all_passed = all(results.values())
    
    for category, passed in results.items():
        print_check(category, passed)
    
    print()
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ All checks passed! Ready for deployment.{Colors.END}")
        print(f"\n{Colors.BOLD}Next steps:{Colors.END}")
        print(f"  1. Review deployment/PHASE14_DEPLOYMENT_GUIDE.md")
        print(f"  2. Start with MDM deployment (VM {results.get('mdm_ip', '?')})")
        print(f"  3. Deploy SDS nodes")
        print(f"  4. Deploy SDC nodes")
        print(f"  5. Run integration tests")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}✗ Some checks failed. Fix issues before deployment.{Colors.END}")
        print(f"\n{Colors.BOLD}Failed checks:{Colors.END}")
        for category, passed in results.items():
            if not passed:
                print(f"  - {category}")
        return 1


def main():
    parser = argparse.ArgumentParser(description='Pre-deployment validation for Phase 14')
    parser.add_argument('config', help='Path to cluster_config.yaml')
    parser.add_argument('--skip-ssh', action='store_true', help='Skip SSH connectivity checks')
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}PowerFlex Phase 14 Pre-Deployment Check{Colors.END}")
    print(f"Config: {args.config}\n")
    
    # Load configuration
    config = validate_config(args.config)
    
    # Run checks
    results = {}
    
    results['Local Prerequisites'] = check_local_prerequisites()
    results['Network Connectivity'] = check_network(config)
    
    if not args.skip_ssh:
        results['SSH Access'] = check_ssh_access(config)
    
    results['Configuration'] = check_configuration(config)
    
    # Store MDM IP for summary
    results['mdm_ip'] = config['mdm']['ip']
    
    # Print summary and exit
    return print_summary(results)


if __name__ == '__main__':
    sys.exit(main())
