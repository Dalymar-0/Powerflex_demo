import argparse
import base64
import json
import time
from typing import Any

import requests


class DemoValidationError(RuntimeError):
    pass


def req(base_url: str, method: str, path: str, **kwargs: Any) -> requests.Response:
    url = f"{base_url.rstrip('/')}{path}"
    response = requests.request(method, url, timeout=20, **kwargs)
    return response


def req_json(base_url: str, method: str, path: str, expected: tuple[int, ...] = (200,), **kwargs: Any) -> dict[str, Any]:
    response = req(base_url, method, path, **kwargs)
    try:
        payload = response.json()
    except Exception as exc:
        raise DemoValidationError(f"{method} {path} returned non-JSON body: {response.text[:300]}") from exc

    if response.status_code not in expected:
        raise DemoValidationError(
            f"{method} {path} failed with HTTP {response.status_code}: {json.dumps(payload, default=str)}"
        )

    if isinstance(payload, dict) and payload.get("error"):
        raise DemoValidationError(f"{method} {path} returned error payload: {payload}")

    return payload


def ensure_api_up(base_url: str) -> None:
    response = req(base_url, "GET", "/")
    if response.status_code != 200:
        raise DemoValidationError(f"API is not reachable at {base_url} (HTTP {response.status_code})")


def run_validation(base_url: str, address_base: str, control_base_port: int, data_base_port: int) -> dict[str, Any]:
    ts = str(int(time.time()))
    prefix = f"demo{ts}"

    report: dict[str, Any] = {
        "base_url": base_url,
        "prefix": prefix,
        "checks": [],
    }

    ensure_api_up(base_url)

    bootstrap = req_json(
        base_url,
        "POST",
        "/cluster/bootstrap/minimal",
        json={
            "prefix": prefix,
            "address_base": address_base,
            "control_base_port": control_base_port,
            "data_base_port": data_base_port,
        },
    )
    report["bootstrap"] = bootstrap

    pd = req_json(base_url, "POST", "/pd/create", json={"name": f"VAL_PD_{ts}"})
    pd_id = int(pd["id"])

    sds1 = req_json(
        base_url,
        "POST",
        "/sds/add",
        json={
            "name": f"VAL_SDS1_{ts}",
            "total_capacity_gb": 8,
            "devices": "blk0,blk1",
            "protection_domain_id": pd_id,
            "cluster_node_id": f"{prefix}-sds-1",
        },
    )
    sds2 = req_json(
        base_url,
        "POST",
        "/sds/add",
        json={
            "name": f"VAL_SDS2_{ts}",
            "total_capacity_gb": 8,
            "devices": "blk0,blk1",
            "protection_domain_id": pd_id,
            "cluster_node_id": f"{prefix}-sds-2",
        },
    )

    pool = req_json(
        base_url,
        "POST",
        "/pool/create",
        json={
            "name": f"VAL_POOL_{ts}",
            "pd_id": pd_id,
            "protection_policy": "two_copies",
            "total_capacity_gb": 8,
        },
    )
    pool_id = int(pool["id"])

    sdc = req_json(
        base_url,
        "POST",
        "/sdc/add",
        json={"name": f"VAL_SDC_{ts}", "cluster_node_id": f"{prefix}-sdc-1"},
    )
    sdc_id = int(sdc["id"])

    vol = req_json(
        base_url,
        "POST",
        "/vol/create",
        json={"name": f"VAL_VOL_{ts}", "size_gb": 1, "provisioning": "thin", "pool_id": pool_id},
    )
    vol_id = int(vol["id"])

    req_json(
        base_url,
        "POST",
        "/vol/map",
        params={"volume_id": vol_id, "sdc_id": sdc_id, "access_mode": "readWrite"},
    )

    payload = f"doD-roundtrip-{ts}".encode("utf-8")
    write_body = {
        "sdc_id": sdc_id,
        "offset_bytes": 4096,
        "data_b64": base64.b64encode(payload).decode("ascii"),
    }
    write_resp = req_json(base_url, "POST", f"/vol/{vol_id}/io/write", json=write_body)

    read_body = {"sdc_id": sdc_id, "offset_bytes": 4096, "length_bytes": len(payload)}
    read_resp = req_json(base_url, "POST", f"/vol/{vol_id}/io/read", json=read_body)
    read_back = base64.b64decode(str(read_resp.get("data_b64", "")).encode("ascii"))

    if read_back != payload:
        raise DemoValidationError("Initial IO roundtrip failed before failure simulation")

    report["checks"].append({"name": "dod1_roundtrip_before_failure", "ok": True, "io_path": read_resp.get("io_path")})

    sds1_id = int(sds1["id"])
    req_json(base_url, "POST", f"/sds/{sds1_id}/fail")

    post_fail_read = req_json(base_url, "POST", f"/vol/{vol_id}/io/read", json=read_body)
    read_after_fail = base64.b64decode(str(post_fail_read.get("data_b64", "")).encode("ascii"))
    if read_after_fail != payload:
        raise DemoValidationError("Read-after-failure does not match written payload")

    report["checks"].append({"name": "dod3_read_after_sds_fail", "ok": True, "io_path": post_fail_read.get("io_path")})

    rebuild_before = req_json(base_url, "GET", f"/rebuild/status/{pool_id}")
    rebuild_start = req_json(base_url, "POST", f"/rebuild/start/{pool_id}")
    rebuild_after = req_json(base_url, "GET", f"/rebuild/status/{pool_id}")

    report["checks"].append(
        {
            "name": "dod4_rebuild_invoked",
            "ok": True,
            "before": rebuild_before,
            "start": rebuild_start,
            "after": rebuild_after,
        }
    )

    req_json(base_url, "POST", f"/sds/{sds1_id}/recover")
    pool_health = req_json(base_url, "GET", f"/pool/{pool_id}/health")

    report["checks"].append({"name": "pool_health_observed", "ok": True, "pool_health": pool_health})

    report["artifacts"] = {
        "pd_id": pd_id,
        "pool_id": pool_id,
        "sds_ids": [int(sds1["id"]), int(sds2["id"])],
        "sdc_id": sdc_id,
        "volume_id": vol_id,
        "write_response": write_resp,
        "read_response": read_resp,
    }

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate demo-readiness flow (bootstrap, map, IO, fail, rebuild, recover)"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="FastAPI base URL")
    parser.add_argument("--address-base", default="127.0.0.", help="Address base used by cluster bootstrap")
    parser.add_argument("--control-base-port", type=int, default=9100, help="Control-plane base port")
    parser.add_argument("--data-base-port", type=int, default=9700, help="Data-plane base port")
    parser.add_argument("--output", default="", help="Optional JSON report output path")
    args = parser.parse_args()

    report = run_validation(
        base_url=args.base_url,
        address_base=args.address_base,
        control_base_port=args.control_base_port,
        data_base_port=args.data_base_port,
    )
    pretty = json.dumps(report, indent=2, default=str)
    print(pretty)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(pretty)
            handle.write("\n")


if __name__ == "__main__":
    main()
