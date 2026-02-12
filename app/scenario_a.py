import requests
import time

BASE_URL = "http://127.0.0.1:8001"

def scenario_a():
    suffix = str(int(time.time()))
    # Create PD
    pd = requests.post(f"{BASE_URL}/pd/create", json={"name": f"PD1_{suffix}"}).json()
    pd_id = pd["id"]
    # Add 3 SDS nodes
    for i in range(1, 4):
        requests.post(f"{BASE_URL}/sds/add", json={
            "name": f"SDS{i}_{suffix}",
            "total_capacity_gb": 1000,
            "devices": "SSD,HDD",
            "protection_domain_id": pd_id
        })
    # Create pool with 2-copy protection
    pool = requests.post(f"{BASE_URL}/pool/create", json={
        "name": f"Pool1_{suffix}",
        "pd_id": pd_id,
        "protection_policy": "two_copies",
        "total_capacity_gb": 2000
    }).json()
    pool_id = pool["id"]
    # Add 2 SDC clients
    for i in range(1, 3):
        requests.post(f"{BASE_URL}/sdc/add", json={"name": f"SDC{i}_{suffix}"})
    # Create volume 500GB thin
    vol = requests.post(f"{BASE_URL}/vol/create", json={
        "name": f"Vol1_{suffix}",
        "size_gb": 500,
        "provisioning": "thin",
        "pool_id": pool_id
    }).json()
    vol_id = vol["id"]
    # Map to SDC1
    requests.post(f"{BASE_URL}/vol/map", params={"volume_id": vol_id, "sdc_id": 1, "access_mode": "readWrite"})
    # Run IO workload (placeholder)
    print("Scenario A completed: Basic Deployment")

if __name__ == "__main__":
    scenario_a()
