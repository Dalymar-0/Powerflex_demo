# PowerFlex Deployment (Canonical)

This folder is intentionally minimal and contains only the files required for current RHEL 7.9 deployment to the 5-node lab cluster.

## Supported Topology

- 172.30.128.50 → MDM + MGMT
- 172.30.128.51 → SDS1
- 172.30.128.52 → SDS2
- 172.30.128.53 → SDC1
- 172.30.128.54 → SDC2

## Files Kept

- automated_deploy.ps1 (full bootstrap deploy)
- automated_resync.ps1 (fast commit sync + redeploy)
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

For day-to-day updates after code changes:

```powershell
cd .\deployment
.\automated_resync.ps1 -Password root
```

`automated_deploy.ps1` behavior (full bootstrap):

- Reads local `HEAD` commit from your current branch
- Verifies `HEAD` is pushed to upstream (unless `-AllowUnpushed`)
- Archives that exact commit locally and syncs it to every node
- Redeploys services so all nodes run the same commit
- Applies network baseline and dependency installation by default

`automated_resync.ps1` behavior (quick loop):

- Runs commit sync + unit deploy + DB init + restart + validation
- Skips network baseline and dependency reinstall by default
- Supports `-WithNetwork` and `-WithDeps` when needed

Useful flags:

- -TestOnly → only SSH/connectivity preflight
- -SkipNetwork → do not touch hostname/hosts/resolver
- -SkipCodeSync (alias: -SkipRepoSync) → do not sync local code archive
- -SkipDeps → skip pip installs
- -AllowUnpushed → allow deploying local commits not yet pushed
- -Force → continue if one or more nodes are unreachable

## Design Notes

- Uses plink + pscp in batch mode (non-interactive)
- Syncs source from local git commit archive to `/opt/Powerflex_demo` on each node
- Preserves `/opt/Powerflex_demo/mdm/data` and `/opt/Powerflex_demo/mgmt/data` during sync
- Deploys service units from this folder into /etc/systemd/system
- Uses fixed interpreter path: /opt/rh/rh-python38/root/usr/bin/python3
- Initializes MDM and MGMT data directories before service start
