"""Test /health/components endpoint"""
import requests
import json
import traceback

try:
    r = requests.get('http://127.0.0.1:8001/health/components', timeout=5)
    print(f'Status: {r.status_code}')
    
    if r.status_code == 200:
        data = r.json()
        print(json.dumps(data, indent=2))
    else:
        print(f'Error response:')
        print(r.text[:1000])
        
except Exception as e:
    print(f'Exception: {e}')
    traceback.print_exc()
