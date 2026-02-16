import requests

endpoints = ['/health', '/health/api/summary', '/health/api/components', '/alerts']
base_url = "http://127.0.0.1:5000"

for ep in endpoints:
    try:
        r = requests.get(f"{base_url}{ep}", timeout=5)
        print(f"{ep}: {r.status_code}")
    except Exception as e:
        print(f"{ep}: ERROR - {e}")
