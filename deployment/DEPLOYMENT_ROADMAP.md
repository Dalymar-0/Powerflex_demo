# Phase 14 Deployment Roadmap - VMware + Rocky Linux

**Your Environment:** 5 Rocky Linux VMs on VMware Workstation, Windows Host

---

## 📅 Timeline Overview

**Total Time:** ~8-10 hours (2 weekends)
- **VM Setup:** 2.5 hours (one-time)
- **PowerFlex Deployment:** 4-6 hours
- **Testing & Validation:** 1-2 hours

---

## 🗓️ Weekend 1: VM Infrastructure Setup (2.5 hours)

### Saturday Morning (1.5 hours)

**Hour 1: Download & Setup**
- [ ] Download Rocky Linux 9 ISO (~2GB) - 15 minutes
- [ ] Install VMware Workstation (if needed) - 10 minutes
- [ ] Configure VMware NAT network (VMnet8: 192.168.100.0/24) - 5 minutes
- [ ] Create 5 VM shells with PowerShell script - 30 minutes

**Hour 2: OS Installation (Part 1)**
- [ ] Install Rocky Linux on VM1 (MDM) - 15 minutes
- [ ] Install Rocky Linux on VM2 (SDS1) - 15 minutes
- [ ] Coffee break - 10 minutes
- [ ] Install Rocky Linux on VM3 (SDS2) - 15 minutes

### Saturday Afternoon (1 hour)

**Hour 3: OS Installation (Part 2) + Config**
- [ ] Install Rocky Linux on VM4 (SDC1) - 15 minutes
- [ ] Install Rocky Linux on VM5 (SDC2) - 15 minutes
- [ ] Post-install config (dnf update, Python, firewall) - 30 minutes

**Checkpoint:** All 5 VMs running Rocky Linux with static IPs ✅

---

### Saturday Evening (Optional: 30 minutes)

**Hour 4: SSH & Validation**
- [ ] Setup SSH keys from Windows host - 10 minutes
- [ ] Test SSH to all VMs - 5 minutes
- [ ] Generate cluster secret - 1 minute
- [ ] Edit cluster_config.yaml - 5 minutes
- [ ] Run pre-deployment check - 2 minutes
- [ ] Take VMware snapshots ("Ready for PowerFlex") - 7 minutes

**Checkpoint:** Pre-deployment check passes ✅

---

## 🗓️ Weekend 2: PowerFlex Deployment (4-6 hours)

### Sunday Morning (2 hours)

**Hour 1: MDM Deployment**
- [ ] SSH to MDM VM (192.168.100.10)
- [ ] Clone PowerFlex repo to /opt/powerflex - 5 minutes
- [ ] Create Python virtual environment - 3 minutes
- [ ] Install dependencies (pip install -r requirements.txt) - 5 minutes
- [ ] Initialize MDM database - 2 minutes
- [ ] Create systemd service file - 5 minutes
- [ ] Start MDM service - 2 minutes
- [ ] Verify MDM API responding (curl http://127.0.0.1:8001/) - 3 minutes
- [ ] Create Protection Domain via API - 5 minutes
- [ ] Buffer time - 30 minutes

**Checkpoint:** MDM running, API accessible, PD created ✅

**Hour 2: SDS1 Deployment**
- [ ] SSH to SDS1 VM (192.168.100.11)
- [ ] Clone repo and setup venv - 8 minutes
- [ ] Create storage directory (/var/powerflex/sds1) - 2 minutes
- [ ] Register SDS with MDM discovery - 5 minutes
- [ ] Add SDS to Protection Domain - 5 minutes
- [ ] Create Pool (if not exists) - 5 minutes
- [ ] Create systemd service - 5 minutes
- [ ] Start SDS service - 2 minutes
- [ ] Verify data port open (nc -zv 192.168.100.11 9700) - 3 minutes
- [ ] Check heartbeat on MDM - 5 minutes
- [ ] Buffer time - 20 minutes

**Checkpoint:** SDS1 running, heartbeat active, pool created ✅

---

### Sunday Afternoon (2 hours)

**Hour 3: SDS2 Deployment**
- [ ] SSH to SDS2 VM (192.168.100.12)
- [ ] Clone repo and setup (same as SDS1) - 8 minutes
- [ ] Create storage directory - 2 minutes
- [ ] Register & add to PD - 10 minutes
- [ ] Create systemd service - 5 minutes
- [ ] Start service - 2 minutes
- [ ] Verify connectivity - 5 minutes
- [ ] Test cross-SDS replication readiness - 8 minutes
- [ ] Buffer time - 20 minutes

**Checkpoint:** SDS2 running, 2-node storage pool operational ✅

**Hour 4: SDC Deployment**
- [ ] SSH to SDC1 VM (192.168.100.13)
- [ ] Clone repo and setup - 8 minutes
- [ ] Register SDC with MDM - 5 minutes
- [ ] Add SDC entity to MDM - 5 minutes
- [ ] Create systemd service - 5 minutes
- [ ] Start SDC service - 2 minutes
- [ ] Verify NBD port (nc -zv 192.168.100.13 8005) - 3 minutes
- [ ] Check heartbeat - 5 minutes
- [ ] Optional: Deploy SDC2 (same steps, 25 minutes)
- [ ] Buffer time - 17 minutes

**Checkpoint:** SDC running, NBD device available ✅

---

### Sunday Evening (2 hours)

**Hour 5: MGMT & Integration**
- [ ] SSH to MDM VM (co-locate MGMT)
- [ ] Create MGMT systemd service - 5 minutes
- [ ] Start MGMT GUI - 2 minutes
- [ ] Access GUI from Windows (http://192.168.100.10:5000) - 3 minutes
- [ ] Login and verify dashboard - 5 minutes
- [ ] Check component health page - 5 minutes
- [ ] Buffer time - 40 minutes

**Checkpoint:** MGMT running, all components visible ✅

**Hour 6: Testing & Validation**
- [ ] Create test volume (10GB) - 3 minutes
- [ ] Map volume to SDC - 2 minutes
- [ ] Write test data via MDM API - 3 minutes
- [ ] Read data back - 2 minutes
- [ ] Verify data on SDS1 chunks - 5 minutes
- [ ] Verify replica on SDS2 chunks - 5 minutes
- [ ] Test failure scenario (stop SDS1) - 10 minutes
- [ ] Verify alert generated - 3 minutes
- [ ] Restart SDS1 and verify recovery - 5 minutes
- [ ] Take final snapshots ("Phase 14 Complete") - 7 minutes
- [ ] Document results - 15 minutes

**Checkpoint:** All tests passing, Phase 14 complete! 🎉

---

## 📋 Daily Checklists

### Day 1 (Saturday): VM Setup

**Morning:**
```
[ ] Downloaded Rocky Linux ISO
[ ] VMware network configured (192.168.100.0/24)
[ ] Created 5 VM shells
[ ] Installed Rocky on VM1, VM2, VM3
```

**Afternoon:**
```
[ ] Installed Rocky on VM4, VM5
[ ] Updated all VMs (dnf update)
[ ] Installed Python 3.11 on all VMs
[ ] Opened firewall ports on all VMs
[ ] Disabled SELinux on all VMs
```

**Evening (Optional):**
```
[ ] Setup SSH keys (passwordless access)
[ ] Generated cluster secret
[ ] Edited cluster_config.yaml
[ ] Pre-deployment check passed
[ ] All VMs can ping each other
[ ] All VMs can access internet
```

---

### Day 2 (Sunday): PowerFlex Deployment

**Morning:**
```
[ ] MDM deployed and running
[ ] MDM API responding (port 8001)
[ ] Protection Domain created
[ ] SDS1 deployed and running
[ ] SDS1 heartbeat active
[ ] Storage pool created
```

**Afternoon:**
```
[ ] SDS2 deployed and running
[ ] SDS2 heartbeat active
[ ] 2-copy replication ready
[ ] SDC1 deployed and running
[ ] SDC1 NBD device available
[ ] SDC1 heartbeat active
```

**Evening:**
```
[ ] MGMT GUI deployed
[ ] MGMT accessible from Windows
[ ] All components show ACTIVE
[ ] Test volume created
[ ] Write/read test passed
[ ] Cross-VM replication verified
[ ] Failure test passed
[ ] Documentation complete
```

---

## 🎯 Success Milestones

### Milestone 1: VMs Ready ✅
- 5 Rocky Linux VMs running
- All on 192.168.100.0/24 network
- SSH access working
- Pre-deployment check passed

### Milestone 2: Control Plane Running ✅
- MDM API operational
- Protection Domain created
- Discovery registry working

### Milestone 3: Data Plane Running ✅
- SDS1 and SDS2 operational
- Storage pool created
- Heartbeats active

### Milestone 4: IO Plane Running ✅
- SDC operational
- NBD device available
- Token management working

### Milestone 5: Management Plane Running ✅
- MGMT GUI accessible
- All components monitored
- Alerts configured

### Milestone 6: System Validated ✅
- Volume operations working
- Cross-VM replication verified
- Failure recovery tested
- Documentation complete

---

## 📊 Progress Tracking

**Track your progress with this table:**

| Component | Status | IP | Deployed | Tested | Notes |
|-----------|--------|------------|----------|--------|-------|
| VM1 (MDM) | ⏸️ | 192.168.100.10 | ⬜ | ⬜ | |
| VM2 (SDS1) | ⏸️ | 192.168.100.11 | ⬜ | ⬜ | |
| VM3 (SDS2) | ⏸️ | 192.168.100.12 | ⬜ | ⬜ | |
| VM4 (SDC1) | ⏸️ | 192.168.100.13 | ⬜ | ⬜ | |
| VM5 (SDC2) | ⏸️ | 192.168.100.14 | ⬜ | ⬜ | |
| MGMT GUI | ⏸️ | 192.168.100.10:5000 | ⬜ | ⬜ | |

**Legend:** ⏸️ Pending, 🔄 In Progress, ✅ Complete, ❌ Failed

**Update as you go!**

---

## 🚨 Troubleshooting Quick References

**Problem: Can't SSH to VM**
→ Check firewalld: `sudo systemctl status firewalld`
→ Add SSH: `sudo firewall-cmd --permanent --add-service=ssh; sudo firewall-cmd --reload`

**Problem: Service won't start**
→ Check logs: `sudo journalctl -u powerflex-mdm -n 50`
→ Check permissions: `sudo chown -R rocky:rocky /opt/powerflex`

**Problem: No internet from VM**
→ Check DNS: `cat /etc/resolv.conf` (should have 8.8.8.8)
→ Restart network: `sudo nmcli con down "System eth0"; sudo nmcli con up "System eth0"`

**Problem: VMs can't see each other**
→ Ping test: `ping 192.168.100.10`
→ Check firewall: `sudo firewall-cmd --list-all`
→ Temporarily disable: `sudo systemctl stop firewalld`

---

## 📚 Document References

**Setup Guides:**
- [VMWARE_REDHAT_GUIDE.md](VMWARE_REDHAT_GUIDE.md) - VMware + Rocky Linux setup
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Quick command reference
- [cluster_config_vmware.yaml](cluster_config_vmware.yaml) - Your config file

**Deployment:**
- [PHASE14_DEPLOYMENT_GUIDE.md](PHASE14_DEPLOYMENT_GUIDE.md) - Step-by-step deployment
- [QUICKSTART.md](QUICKSTART.md) - Phase 14 overview

**Architecture:**
- [../docs/REFORM_PLAN.md](../docs/REFORM_PLAN.md) - System architecture
- [../docs/STRATEGY_ROADMAP.md](../docs/STRATEGY_ROADMAP.md) - Full roadmap

---

## ✅ Final Checklist

**Before you're done with Phase 14:**

- [ ] All 5 services running (systemctl status powerflex-*)
- [ ] All heartbeats active (curl http://192.168.100.10:8001/health/components)
- [ ] Volume creation works
- [ ] Write operation works
- [ ] Read operation works
- [ ] Data replicated across SDS1 and SDS2
- [ ] Failure test passed (SDS down → alert → recovered)
- [ ] MGMT GUI accessible
- [ ] All tests documented
- [ ] Snapshots taken ("Phase 14 Complete")
- [ ] Git committed and pushed

**Congratulations! You've built a distributed storage system! 🎉**

---

## 🎓 What You've Accomplished

After Phase 14, you can say:

✅ **"Deployed a 5-node distributed storage cluster"**  
✅ **"Configured multi-VM networking across separate physical nodes"**  
✅ **"Implemented cross-node data replication with automatic failover"**  
✅ **"Built monitoring dashboard for distributed system health"**  
✅ **"Tested network partition recovery and node failure scenarios"**  
✅ **"Used enterprise Linux (Rocky Linux 9) and systemd services"**  
✅ **"Automated deployment with Python scripts and systemd"**  

**This is portfolio-worthy! 🌟**

---

## 🚀 What's Next?

**After Phase 14:**
1. **Phase 15:** SQLAlchemy 2.0 migration (5-7 hours)
2. **Phase 16:** Performance optimization (8-10 hours, optional)
3. **Phase 17:** Advanced testing (6-8 hours, optional)
4. **Phase 18:** Production hardening (10-12 hours, optional)

**Or stop here!** Phase 14 completion is already impressive.

See [STRATEGY_ROADMAP.md](../docs/STRATEGY_ROADMAP.md) for details.

---

## 💡 Tips for Success

**Take breaks:** This is 8-10 hours of focused work. Split across 2 weekends is perfect.

**Take snapshots:** Before each major step (after OS install, after MDM deploy, etc.)

**Keep notes:** Document any issues you hit and how you solved them (great for interviews!)

**Ask for help:** If stuck, check troubleshooting sections or ask questions.

**Celebrate milestones:** Each checkpoint is an achievement! ✨

**Good luck with your deployment! You've got this! 🚀**
