# PowerFlex Deployment (Canonical)

This folder is intentionally minimal and contains only the files required for current RHEL 7.9 deployment to the 5-node lab cluster.

## Supported Topology

- 172.30.128.50 → MDM + MGMT
- 172.30.128.51 → SDS1
- 172.30.128.52 → SDS2
- 172.30.128.53 → SDC1
- 172.30.128.54 → SDC2

## Files Kept

- automated_deploy.ps1 (single canonical deployment entrypoint)
- powerflex-mdm.service
- powerflex-mgmt.service
- powerflex-sds1.service
- powerflex-sds2.service
- powerflex-sdc1.service
- powerflex-sdc2.service
- REDHAT79_DEPLOYMENT_GUIDE.md (manual fallback + troubleshooting)

## Quick Usage

From Windows PowerShell in repository root:

```powershell
cd .\deployment
.\automated_deploy.ps1 -Password root
```

Useful flags:

- -TestOnly → only SSH/connectivity preflight
- -SkipNetwork → do not touch hostname/hosts/resolver
- -SkipRepoSync → do not clone/reset repo on VMs
- -SkipDeps → skip pip installs
- -Force → continue if one or more nodes are unreachable

## Design Notes

- Uses plink + pscp in batch mode (non-interactive)
- Deploys service units from this folder into /etc/systemd/system
- Uses fixed interpreter path: /opt/rh/rh-python38/root/usr/bin/python3
- Initializes MDM and MGMT data directories before service start
