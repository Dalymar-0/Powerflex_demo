from datetime import datetime
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select

from mdm.database import SessionLocal
from mdm.config import CONTROL_PLANE_BASE_PORT, DATA_PLANE_BASE_PORT
from mdm.models import ClusterNode, ClusterNodeStatus, NodeCapability

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ClusterNodeRegister(BaseModel):
    node_id: str = Field(min_length=2)
    name: str = Field(min_length=1)
    address: str = Field(min_length=3)
    port: int | None = Field(default=None, ge=1, le=65535)
    control_port: int | None = Field(default=None, ge=1, le=65535)
    data_port: int | None = Field(default=None, ge=1, le=65535)
    capabilities: list[str]
    metadata: dict[str, Any] | None = None


class ClusterNodeHeartbeat(BaseModel):
    status: ClusterNodeStatus | None = None
    capabilities: list[str] | None = None


class ClusterBootstrapRequest(BaseModel):
    prefix: str = Field(default="demo", min_length=2)
    address_base: str = Field(default="10.0.0.", min_length=4)
    start_octet: int = Field(default=10, ge=1, le=250)
    base_port: int | None = Field(default=None, ge=1, le=65000)
    control_base_port: int = Field(default=CONTROL_PLANE_BASE_PORT, ge=1, le=65000)
    data_base_port: int = Field(default=DATA_PLANE_BASE_PORT, ge=1, le=65000)


def _normalize_capabilities(raw_caps: list[str]) -> list[str]:
    normalized = sorted({cap.upper() for cap in raw_caps})
    allowed = {cap.value for cap in NodeCapability}
    invalid = [cap for cap in normalized if cap not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid capabilities: {invalid}")
    if not normalized:
        raise HTTPException(status_code=400, detail="At least one capability is required")
    return normalized


def _serialize_node(node: ClusterNode) -> dict[str, Any]:
    capabilities_raw = getattr(node, "capabilities", "") or ""
    status_value = getattr(node, "status", None)
    registered_at = getattr(node, "registered_at", None)
    last_heartbeat = getattr(node, "last_heartbeat", None)
    metadata_json = getattr(node, "metadata_json", None)

    if isinstance(status_value, ClusterNodeStatus):
        status_output = status_value.value
    else:
        status_output = str(status_value) if status_value is not None else None

    legacy_port = getattr(node, "port", None)
    control_port = getattr(node, "control_port", None) or legacy_port
    data_port = getattr(node, "data_port", None)

    return {
        "node_id": getattr(node, "node_id", None),
        "name": getattr(node, "name", None),
        "address": getattr(node, "address", None),
        "port": legacy_port,
        "control_port": control_port,
        "data_port": data_port,
        "capabilities": [c for c in capabilities_raw.split(",") if c],
        "status": status_output,
        "registered_at": registered_at.isoformat() if registered_at is not None else None,
        "last_heartbeat": last_heartbeat.isoformat() if last_heartbeat is not None else None,
        "metadata": json.loads(metadata_json) if metadata_json else None,
    }


def _resolve_ports(payload: ClusterNodeRegister, capabilities: list[str]) -> tuple[int, int | None]:
    control_port = payload.control_port or payload.port
    if not control_port or int(control_port) <= 0:
        raise HTTPException(status_code=400, detail="control_port (or legacy port) is required")

    data_port = payload.data_port
    if NodeCapability.SDS.value in capabilities and (not data_port or int(data_port) <= 0):
        data_port = int(control_port)

    return int(control_port), int(data_port) if data_port else None


@router.post("/cluster/nodes/register")
def register_node(payload: ClusterNodeRegister, db: Session = Depends(get_db)):
    capabilities = _normalize_capabilities(payload.capabilities)
    control_port, data_port = _resolve_ports(payload, capabilities)

    node = db.scalars(select(ClusterNode).where(ClusterNode.node_id == payload.node_id)).first()
    if node is None:
        node = ClusterNode(
            node_id=payload.node_id,
            name=payload.name,
            address=payload.address,
            port=control_port,
            control_port=control_port,
            data_port=data_port,
            capabilities=",".join(capabilities),
            status=ClusterNodeStatus.ACTIVE,
            registered_at=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
            metadata_json=json.dumps(payload.metadata) if payload.metadata else None,
        )
        db.add(node)
    else:
        setattr(node, "name", payload.name)
        setattr(node, "address", payload.address)
        setattr(node, "port", control_port)
        setattr(node, "control_port", control_port)
        setattr(node, "data_port", data_port)
        setattr(node, "capabilities", ",".join(capabilities))
        setattr(node, "status", ClusterNodeStatus.ACTIVE)
        setattr(node, "last_heartbeat", datetime.utcnow())
        if payload.metadata:
            setattr(node, "metadata_json", json.dumps(payload.metadata))

    db.commit()
    db.refresh(node)
    return {"registered": True, "node": _serialize_node(node)}


@router.post("/cluster/nodes/{node_id}/heartbeat")
def heartbeat_node(node_id: str, payload: ClusterNodeHeartbeat, db: Session = Depends(get_db)):
    node = db.scalars(select(ClusterNode).where(ClusterNode.node_id == node_id)).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    setattr(node, "last_heartbeat", datetime.utcnow())
    if payload.status is not None:
        setattr(node, "status", payload.status)
    if payload.capabilities is not None:
        setattr(node, "capabilities", ",".join(_normalize_capabilities(payload.capabilities)))

    db.commit()
    db.refresh(node)
    return {"heartbeat": "ok", "node": _serialize_node(node)}


@router.get("/cluster/nodes")
def list_nodes(db: Session = Depends(get_db)):
    nodes = db.scalars(select(ClusterNode).order_by(ClusterNode.node_id.asc())).all()
    return {"count": len(nodes), "nodes": [_serialize_node(node) for node in nodes]}


@router.get("/cluster/nodes/{node_id}")
def get_node(node_id: str, db: Session = Depends(get_db)):
    node = db.scalars(select(ClusterNode).where(ClusterNode.node_id == node_id)).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return _serialize_node(node)


@router.get("/cluster/summary")
def cluster_summary(db: Session = Depends(get_db)):
    nodes = db.scalars(select(ClusterNode)).all()
    capability_totals = {cap.value: 0 for cap in NodeCapability}
    status_totals = {status.value: 0 for status in ClusterNodeStatus}

    for node in nodes:
        node_status = getattr(node, "status", None)
        if isinstance(node_status, ClusterNodeStatus):
            status_key = node_status.value
        else:
            status_key = str(node_status) if node_status is not None else ClusterNodeStatus.UNKNOWN.value
        status_totals[status_key] = status_totals.get(status_key, 0) + 1

        capabilities_raw = getattr(node, "capabilities", "") or ""
        for cap in [c for c in capabilities_raw.split(",") if c]:
            capability_totals[cap] = capability_totals.get(cap, 0) + 1

    return {
        "node_count": len(nodes),
        "capabilities": capability_totals,
        "statuses": status_totals,
    }


@router.post("/cluster/bootstrap/minimal")
def bootstrap_minimal_topology(payload: ClusterBootstrapRequest, db: Session = Depends(get_db)):
    control_base_port = int(payload.base_port) if payload.base_port else int(payload.control_base_port)
    data_base_port = int(payload.data_base_port)

    topology = [
        {
            "suffix": "mdm-1",
            "name": "mdm-1",
            "capabilities": [NodeCapability.MDM.value],
            "control_port_offset": 0,
            "data_port_offset": None,
            "ip_offset": 0,
        },
        {
            "suffix": "sds-1",
            "name": "sds-1",
            "capabilities": [NodeCapability.SDS.value],
            "control_port_offset": 10,
            "data_port_offset": 0,
            "ip_offset": 1,
        },
        {
            "suffix": "sds-2",
            "name": "sds-2",
            "capabilities": [NodeCapability.SDS.value],
            "control_port_offset": 11,
            "data_port_offset": 1,
            "ip_offset": 2,
        },
        {
            "suffix": "sdc-1",
            "name": "sdc-1",
            "capabilities": [NodeCapability.SDC.value],
            "control_port_offset": 20,
            "data_port_offset": None,
            "ip_offset": 10,
        },
    ]

    created = 0
    updated = 0
    result_nodes: list[dict[str, Any]] = []

    for item in topology:
        node_id = f"{payload.prefix}-{item['suffix']}"
        existing = db.scalars(select(ClusterNode).where(ClusterNode.node_id == node_id)).first()

        address = f"{payload.address_base}{payload.start_octet + item['ip_offset']}"
        control_port = control_base_port + int(item["control_port_offset"])
        data_port = None
        if item["data_port_offset"] is not None:
            data_port = data_base_port + int(item["data_port_offset"])
        capabilities = _normalize_capabilities(item["capabilities"])
        metadata = {
            "source": "bootstrap_minimal_topology",
            "topology": "minimal",
            "role": item["suffix"],
            "network_planes": {
                "control_port": control_port,
                "data_port": data_port,
            },
        }

        if existing is None:
            node = ClusterNode(
                node_id=node_id,
                name=f"{payload.prefix}-{item['name']}",
                address=address,
                port=control_port,
                control_port=control_port,
                data_port=data_port,
                capabilities=",".join(capabilities),
                status=ClusterNodeStatus.ACTIVE,
                registered_at=datetime.utcnow(),
                last_heartbeat=datetime.utcnow(),
                metadata_json=json.dumps(metadata),
            )
            db.add(node)
            created += 1
            result_nodes.append(_serialize_node(node))
        else:
            setattr(existing, "name", f"{payload.prefix}-{item['name']}")
            setattr(existing, "address", address)
            setattr(existing, "port", control_port)
            setattr(existing, "control_port", control_port)
            setattr(existing, "data_port", data_port)
            setattr(existing, "capabilities", ",".join(capabilities))
            setattr(existing, "status", ClusterNodeStatus.ACTIVE)
            setattr(existing, "last_heartbeat", datetime.utcnow())
            setattr(existing, "metadata_json", json.dumps(metadata))
            updated += 1
            result_nodes.append(_serialize_node(existing))

    db.commit()

    return {
        "bootstrap": "ok",
        "topology": "minimal",
        "prefix": payload.prefix,
        "created": created,
        "updated": updated,
        "count": len(result_nodes),
        "nodes": result_nodes,
    }
