import argparse
import json
from urllib import request


def post_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("utf-8")
        return resp.status, json.loads(data)


def get_json(url: str) -> tuple[int, dict]:
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("utf-8")
        return resp.status, json.loads(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap minimal cluster topology (1 MDM, 2 SDS, 1 SDC)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="API base URL")
    parser.add_argument("--prefix", default="demo", help="Node ID prefix")
    parser.add_argument("--address-base", default="10.0.0.", help="Address base prefix")
    parser.add_argument("--start-octet", type=int, default=10, help="Starting address octet")
    parser.add_argument("--base-port", type=int, default=None, help="Legacy base control-plane port (deprecated)")
    parser.add_argument("--control-base-port", type=int, default=9100, help="Base control-plane port")
    parser.add_argument("--data-base-port", type=int, default=9700, help="Base data-plane port (SDS IO)")
    args = parser.parse_args()

    payload = {
        "prefix": args.prefix,
        "address_base": args.address_base,
        "start_octet": args.start_octet,
        "base_port": args.base_port,
        "control_base_port": args.control_base_port,
        "data_base_port": args.data_base_port,
    }

    code, body = post_json(f"{args.base_url}/cluster/bootstrap/minimal", payload)
    print(f"POST /cluster/bootstrap/minimal -> {code}")
    print(json.dumps(body, indent=2))

    code, summary = get_json(f"{args.base_url}/cluster/summary")
    print(f"GET /cluster/summary -> {code}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
