# PowerFlex RHEL 7.9 Deployment Guide (Canonical)

This is the concise manual fallback for the automated flow in deployment/automated_deploy.ps1.

## 1) Environment

- 5 VMs on 172.30.128.0/24
- SSH access as root/root
- Repo path on VMs: /opt/Powerflex_demo
- Python path on VMs: /opt/rh/rh-python38/root/usr/bin/python3

## 2) Copy Unit Files

From Windows host:

```powershell
$base='C:\Users\uid1944\Powerflex_demo\deployment'
pscp -batch -pw root "$base\powerflex-mdm.service"  root@172.30.128.50:/etc/systemd/system/powerflex-mdm.service
pscp -batch -pw root "$base\powerflex-mgmt.service" root@172.30.128.50:/etc/systemd/system/powerflex-mgmt.service
pscp -batch -pw root "$base\powerflex-sds1.service" root@172.30.128.51:/etc/systemd/system/powerflex-sds.service
pscp -batch -pw root "$base\powerflex-sds2.service" root@172.30.128.52:/etc/systemd/system/powerflex-sds.service
pscp -batch -pw root "$base\powerflex-sdc1.service" root@172.30.128.53:/etc/systemd/system/powerflex-sdc.service
pscp -batch -pw root "$base\powerflex-sdc2.service" root@172.30.128.54:/etc/systemd/system/powerflex-sdc.service
```

## 3) Initialize DB + Start Services

On MDM node (172.30.128.50):

```bash
mkdir -p /opt/Powerflex_demo/mdm/data /opt/Powerflex_demo/mgmt/data
cd /opt/Powerflex_demo
/opt/rh/rh-python38/root/usr/bin/python3 -c "from mdm.database import init_db; init_db()"
systemctl daemon-reload
systemctl enable powerflex-mdm powerflex-mgmt
systemctl restart powerflex-mdm
sleep 3
systemctl restart powerflex-mgmt
```

On SDS nodes:

```bash
systemctl daemon-reload
systemctl enable powerflex-sds
systemctl restart powerflex-sds
```

On SDC nodes:

```bash
systemctl daemon-reload
systemctl enable powerflex-sdc
systemctl restart powerflex-sdc
```

## 4) Validate

```bash
systemctl is-active powerflex-mdm
systemctl is-active powerflex-mgmt
systemctl is-active powerflex-sds
systemctl is-active powerflex-sdc
```

From Windows:

```powershell
Invoke-RestMethod -Uri "http://172.30.128.50:8001/health/" -TimeoutSec 10
Invoke-WebRequest -UseBasicParsing -Uri "http://172.30.128.50:5000/" -TimeoutSec 10
```

## 5) Troubleshooting

- Check service logs:
  - journalctl -u powerflex-mdm -n 100 --no-pager
  - journalctl -u powerflex-sds -n 100 --no-pager
  - journalctl -u powerflex-sdc -n 100 --no-pager
  - journalctl -u powerflex-mgmt -n 100 --no-pager
- Verify ports:
  - MDM 8001, MGMT 5000
  - SDS 9700/9100/9200
  - SDC 8005/8003/8004
- Re-run full deployment:
  - deployment\automated_deploy.ps1 -Password root
