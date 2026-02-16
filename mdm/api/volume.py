from fastapi import APIRouter, Depends, HTTPException
import os
import base64
import hashlib
import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from mdm.database import SessionLocal
from mdm.models import Volume, ProvisioningType, VolumeState, VolumeMapping, Replica, Chunk, SDSNode, ClusterNode, ClusterNodeStatus
from mdm.services.capability_guard import has_active_capability
from mdm.services.volume_manager import VolumeManager
from mdm.services.real_storage import RealStorageBackend
from shared.sdc_socket_client import SDCSocketClient
from mdm.logic import create_volume, map_volume, unmap_volume, extend_volume, delete_volume
from pydantic import BaseModel

router = APIRouter()

IO_MODE_NETWORK_PREFER_LOCAL = "network_prefer_local"
IO_MODE_NETWORK_ONLY = "network_only"
WRITE_ACK_POLICY_ALL = "all"
WRITE_ACK_POLICY_QUORUM = "quorum"


def _io_mode() -> str:
    configured = str(os.getenv("POWERFLEX_IO_MODE", IO_MODE_NETWORK_PREFER_LOCAL)).strip().lower()
    if configured in {IO_MODE_NETWORK_PREFER_LOCAL, IO_MODE_NETWORK_ONLY}:
        return configured
    return IO_MODE_NETWORK_PREFER_LOCAL


def _write_ack_policy() -> str:
    configured = str(os.getenv("POWERFLEX_WRITE_ACK_POLICY", WRITE_ACK_POLICY_ALL)).strip().lower()
    if configured in {WRITE_ACK_POLICY_ALL, WRITE_ACK_POLICY_QUORUM}:
        return configured
    return WRITE_ACK_POLICY_ALL


def _required_acks_for_segment(target_count: int, policy: str) -> int:
    if target_count <= 0:
        return 0
    if policy == WRITE_ACK_POLICY_QUORUM:
        return (target_count // 2) + 1
    return target_count


def _plan_generation_token(
    operation: str,
    volume_id: int,
    sdc_id: int,
    offset_bytes: int,
    length_bytes: int,
    io_mode: str,
    segments: list[dict],
    write_policy: str | None = None,
) -> str:
    normalized_segments = []
    for segment in segments:
        targets = sorted(
            [
                {
                    "sds_id": int(target.get("sds_id", 0) or 0),
                    "host": str(target.get("host", "") or ""),
                    "port": int(target.get("port", 0) or 0),
                }
                for target in (segment.get("targets", []) or [])
            ],
            key=lambda item: (item["sds_id"], item["host"], item["port"]),
        )
        normalized_segments.append(
            {
                "chunk_id": int(segment.get("chunk_id", 0) or 0),
                "chunk_generation": int(segment.get("chunk_generation", 0) or 0),
                "segment_offset_bytes": int(segment.get("segment_offset_bytes", 0) or 0),
                "segment_length_bytes": int(segment.get("segment_length_bytes", 0) or 0),
                "targets": targets,
            }
        )

    payload = {
        "operation": operation,
        "volume_id": int(volume_id),
        "sdc_id": int(sdc_id),
        "offset_bytes": int(offset_bytes),
        "length_bytes": int(length_bytes),
        "io_mode": io_mode,
        "write_policy": write_policy,
        "segments": normalized_segments,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class VolumeCreate(BaseModel):
    name: str
    size_gb: float
    provisioning: ProvisioningType
    pool_id: int


class VolumeWriteRequest(BaseModel):
    sdc_id: int
    offset_bytes: int
    data_b64: str


class VolumeReadRequest(BaseModel):
    sdc_id: int
    offset_bytes: int
    length_bytes: int


class VolumeIOPlanRequest(BaseModel):
    sdc_id: int
    offset_bytes: int = 0
    length_bytes: int = 0


def _validate_mapping_for_io(db: Session, volume_id: int, sdc_id: int, require_write: bool) -> None:
    mapping = db.scalars(select(VolumeMapping).where(
        VolumeMapping.volume_id == volume_id, VolumeMapping.sdc_id == sdc_id
    )).first()
    if not mapping:
        raise HTTPException(status_code=403, detail="Volume is not mapped to this SDC")

    if require_write:
        mode = getattr(mapping, "access_mode", "")
        mode_value = str(getattr(mode, "value", mode))
        if str(mode_value).lower() == "readonly":
            raise HTTPException(status_code=403, detail="Mapping is read-only")


def _active_sds_endpoints_for_volume(db: Session, volume_id: int) -> list[tuple[str, int]]:
    replicas = db.scalars(select(Replica).join(Chunk, Chunk.id == Replica.chunk_id).where(
        Chunk.volume_id == volume_id
    )).all()
    sds_ids = sorted({int(getattr(replica, "sds_id", 0) or 0) for replica in replicas})
    if not sds_ids:
        return []

    sds_nodes = db.scalars(select(SDSNode).where(SDSNode.id.in_(sds_ids))).all()
    endpoints: list[tuple[str, int]] = []
    for sds in sds_nodes:
        cluster_node_id = getattr(sds, "cluster_node_id", None)
        if not cluster_node_id:
            continue
        node = db.scalars(select(ClusterNode).where(ClusterNode.node_id == cluster_node_id)).first()
        if not node:
            continue
        node_status = getattr(node, "status", None)
        status_value = str(getattr(node_status, "value", node_status))
        if status_value != ClusterNodeStatus.ACTIVE.value:
            continue
        address = str(getattr(node, "address", "") or "")
        data_port = int(getattr(node, "data_port", 0) or 0)
        control_port = int(getattr(node, "control_port", 0) or 0)
        legacy_port = int(getattr(node, "port", 0) or 0)
        port = data_port or control_port or legacy_port
        if address and port > 0:
            endpoints.append((address, port))

    return endpoints


def _active_sds_endpoint_map_for_volume(db: Session, volume_id: int) -> dict[int, tuple[str, int]]:
    replicas = db.scalars(select(Replica).join(Chunk, Chunk.id == Replica.chunk_id).where(
        Chunk.volume_id == volume_id
    )).all()
    sds_ids = sorted({int(getattr(replica, "sds_id", 0) or 0) for replica in replicas})
    if not sds_ids:
        return {}

    sds_nodes = db.scalars(select(SDSNode).where(SDSNode.id.in_(sds_ids))).all()
    endpoint_map: dict[int, tuple[str, int]] = {}
    for sds in sds_nodes:
        cluster_node_id = getattr(sds, "cluster_node_id", None)
        if not cluster_node_id:
            continue
        node = db.scalars(select(ClusterNode).where(ClusterNode.node_id == cluster_node_id)).first()
        if not node:
            continue
        node_status = getattr(node, "status", None)
        status_value = str(getattr(node_status, "value", node_status))
        if status_value != ClusterNodeStatus.ACTIVE.value:
            continue
        address = str(getattr(node, "address", "") or "")
        data_port = int(getattr(node, "data_port", 0) or 0)
        control_port = int(getattr(node, "control_port", 0) or 0)
        legacy_port = int(getattr(node, "port", 0) or 0)
        port = data_port or control_port or legacy_port
        if address and port > 0:
            endpoint_map[int(sds.id)] = (address, port)
    return endpoint_map


def _volume_chunk_size_bytes(db: Session, volume: Volume) -> int:
    pool = getattr(volume, "pool", None)
    if pool is None:
        refreshed = db.scalars(select(Volume).where(Volume.id == volume.id)).first()
        pool = getattr(refreshed, "pool", None) if refreshed is not None else None
    chunk_size_mb = float(getattr(pool, "chunk_size_mb", 4) or 4)
    return max(1024 * 1024, int(chunk_size_mb * 1024 * 1024))


def _build_chunk_segments(
    db: Session,
    volume: Volume,
    offset_bytes: int,
    length_bytes: int,
) -> list[dict]:
    if length_bytes <= 0:
        return []

    chunk_size = _volume_chunk_size_bytes(db, volume)
    endpoint_map = _active_sds_endpoint_map_for_volume(db, int(volume.id))
    chunks = db.scalars(select(Chunk).where(Chunk.volume_id == int(volume.id)).order_by(
        Chunk.logical_offset_mb.asc()
    )).all()

    by_index: dict[int, Chunk] = {
        int((int(getattr(chunk, "logical_offset_mb", 0) or 0) * 1024 * 1024) // chunk_size): chunk
        for chunk in chunks
    }

    end_exclusive = offset_bytes + length_bytes
    current = offset_bytes
    segments: list[dict] = []

    while current < end_exclusive:
        chunk_index = current // chunk_size
        chunk_start = chunk_index * chunk_size
        chunk_end = chunk_start + chunk_size
        segment_end = min(chunk_end, end_exclusive)
        segment_len = segment_end - current

        chunk = by_index.get(int(chunk_index))
        if chunk is None:
            raise HTTPException(status_code=500, detail=f"No chunk metadata for chunk_index={chunk_index}")

        replicas = db.scalars(select(Replica).where(Replica.chunk_id == int(chunk.id)).order_by(
            Replica.sds_id.asc()
        )).all()
        targets: list[dict] = []
        for replica in replicas:
            sds_id = int(getattr(replica, "sds_id", 0) or 0)
            endpoint = endpoint_map.get(sds_id)
            if endpoint is None:
                continue
            host, port = endpoint
            targets.append(
                {
                    "sds_id": sds_id,
                    "host": host,
                    "port": port,
                    "plane": "data",
                    "target_offset_bytes": current,
                }
            )

        segments.append(
            {
                "chunk_id": int(chunk.id),
                "chunk_index": int(chunk_index),
                "chunk_generation": int(getattr(chunk, "generation", 0) or 0),
                "chunk_checksum": getattr(chunk, "checksum", None),
                "segment_offset_bytes": current,
                "segment_length_bytes": segment_len,
                "targets": targets,
            }
        )

        current = segment_end

    return segments


def _unique_targets(segments: list[dict]) -> list[dict]:
    seen: set[tuple[str, int]] = set()
    result: list[dict] = []
    for segment in segments:
        for target in segment.get("targets", []):
            host = str(target.get("host", "") or "")
            port = int(target.get("port", 0) or 0)
            if not host or port <= 0:
                continue
            key = (host, port)
            if key in seen:
                continue
            seen.add(key)
            result.append({"host": host, "port": port})
    return result

@router.post("/vol/create")
def create_vol(vol: VolumeCreate, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")
    try:
        volume = create_volume(vol.name, vol.size_gb, vol.provisioning, vol.pool_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": volume.id, "name": volume.name}

@router.post("/vol/map")
def map_vol(volume_id: int, sdc_id: int, access_mode: str, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")
    try:
        map_volume(volume_id, sdc_id, access_mode, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "mapped"}

@router.post("/vol/unmap")
def unmap_vol(volume_id: int, sdc_id: int, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")
    try:
        unmap_volume(volume_id, sdc_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "unmapped"}

@router.post("/vol/extend")
def extend_vol(volume_id: int, new_size_gb: float, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")
    try:
        extend_volume(volume_id, new_size_gb, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "extended"}

@router.delete("/vol/{volume_id}")
def delete_vol(volume_id: int, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")
    try:
        delete_volume(volume_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "deleted"}

@router.get("/vol/list")
def list_vols(db: Session = Depends(get_db)):
    vols = db.scalars(select(Volume)).all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "state": v.state,
            "size_gb": v.size_gb,
            "pool_id": v.pool_id,
            "provisioning": v.provisioning,
            "mapping_count": v.mapping_count,
        }
        for v in vols
    ]


@router.get("/vol/{volume_id}")
def get_vol(volume_id: int, db: Session = Depends(get_db)):
    vol = db.get(Volume, volume_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")

    manager = VolumeManager(db)
    details = manager.get_volume_details(volume_id) or {}
    mappings = db.scalars(select(VolumeMapping).where(VolumeMapping.volume_id == volume_id)).all()
    return {
        "id": vol.id,
        "name": vol.name,
        "size_gb": vol.size_gb,
        "provisioning": vol.provisioning,
        "pool_id": vol.pool_id,
        "used_capacity_gb": vol.used_capacity_gb,
        "state": vol.state,
        "mapping_count": vol.mapping_count,
        "mappings": [
            {"sdc_id": m.sdc_id, "access_mode": m.access_mode, "mapped_at": m.mapped_at}
            for m in mappings
        ],
        "io_mode": _io_mode(),
    }


@router.get("/vol/{volume_id}/debug/storage")
def get_vol_storage_debug(volume_id: int, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")

    vol = db.get(Volume, volume_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")

    manager = VolumeManager(db)
    details = manager.get_volume_details(volume_id) or {}
    chunks = db.scalars(select(Chunk).where(Chunk.volume_id == volume_id).order_by(
        Chunk.logical_offset_mb.asc()
    )).all()
    chunk_layout = []
    for chunk in chunks:
        replicas = db.scalars(select(Replica).where(Replica.chunk_id == chunk.id)).all()
        chunk_layout.append(
            {
                "chunk_id": int(chunk.id),
                "logical_offset_mb": int(getattr(chunk, "logical_offset_mb", 0) or 0),
                "generation": int(getattr(chunk, "generation", 0) or 0),
                "checksum": getattr(chunk, "checksum", None),
                "last_write_offset_bytes": getattr(chunk, "last_write_offset_bytes", None),
                "last_write_length_bytes": getattr(chunk, "last_write_length_bytes", None),
                "last_write_at": getattr(chunk, "last_write_at", None),
                "replicas": [
                    {
                        "replica_id": int(replica.id),
                        "sds_id": int(replica.sds_id),
                        "is_available": bool(getattr(replica, "is_available", False)),
                        "is_current": bool(getattr(replica, "is_current", False)),
                        "is_rebuilding": bool(getattr(replica, "is_rebuilding", False)),
                    }
                    for replica in replicas
                ],
            }
        )
    return {
        "volume_id": vol.id,
        "volume_name": vol.name,
        "replica_paths": details.get("replica_paths", []),
        "mapping_artifacts": details.get("mapping_artifacts", []),
        "mapped_device_paths": details.get("mapped_device_paths", []),
        "active_sds_endpoints": _active_sds_endpoints_for_volume(db, volume_id),
        "chunk_layout": chunk_layout,
    }


@router.post("/vol/{volume_id}/io/plan/write")
def plan_volume_write(volume_id: int, payload: VolumeIOPlanRequest, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")

    vol = db.get(Volume, volume_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")

    _validate_mapping_for_io(db, volume_id, payload.sdc_id, require_write=True)
    requested_len = int(payload.length_bytes or 0)
    if requested_len <= 0:
        requested_len = 1
    segments = _build_chunk_segments(db, vol, int(payload.offset_bytes or 0), requested_len)
    if not segments:
        raise HTTPException(status_code=400, detail="No write segments planned")

    if any(len(segment.get("targets", [])) == 0 for segment in segments):
        raise HTTPException(status_code=503, detail="At least one chunk segment has no ACTIVE SDS targets")

    write_policy = _write_ack_policy()
    plan_generation = _plan_generation_token(
        operation="write",
        volume_id=vol.id,
        sdc_id=payload.sdc_id,
        offset_bytes=payload.offset_bytes,
        length_bytes=requested_len,
        io_mode=_io_mode(),
        write_policy=write_policy,
        segments=segments,
    )
    sds_endpoints = _unique_targets(segments)

    return {
        "authorized": True,
        "operation": "write",
        "volume_id": vol.id,
        "volume_name": vol.name,
        "sdc_id": payload.sdc_id,
        "offset_bytes": payload.offset_bytes,
        "length_bytes": requested_len,
        "io_mode": _io_mode(),
        "plan_generation": plan_generation,
        "plan_cache_hint": "invalidate_on_target_io_error_or_mapping_change",
        "target_sds_endpoints": sds_endpoints,
        "segments": segments,
        "write_policy": write_policy,
        "required_acks_by_segment": [
            {
                "chunk_id": int(segment.get("chunk_id", 0) or 0),
                "required_acks": _required_acks_for_segment(len(segment.get("targets", []) or []), write_policy),
            }
            for segment in segments
        ],
    }


@router.post("/vol/{volume_id}/io/plan/read")
def plan_volume_read(volume_id: int, payload: VolumeIOPlanRequest, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")

    vol = db.get(Volume, volume_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")

    _validate_mapping_for_io(db, volume_id, payload.sdc_id, require_write=False)
    requested_len = int(payload.length_bytes or 0)
    if requested_len <= 0:
        requested_len = 1
    segments = _build_chunk_segments(db, vol, int(payload.offset_bytes or 0), requested_len)
    if not segments:
        raise HTTPException(status_code=400, detail="No read segments planned")

    if any(len(segment.get("targets", [])) == 0 for segment in segments):
        raise HTTPException(status_code=503, detail="At least one chunk segment has no ACTIVE SDS targets")

    plan_generation = _plan_generation_token(
        operation="read",
        volume_id=vol.id,
        sdc_id=payload.sdc_id,
        offset_bytes=payload.offset_bytes,
        length_bytes=requested_len,
        io_mode=_io_mode(),
        segments=segments,
    )
    sds_endpoints = _unique_targets(segments)

    return {
        "authorized": True,
        "operation": "read",
        "volume_id": vol.id,
        "volume_name": vol.name,
        "sdc_id": payload.sdc_id,
        "offset_bytes": payload.offset_bytes,
        "length_bytes": requested_len,
        "io_mode": _io_mode(),
        "plan_generation": plan_generation,
        "plan_cache_hint": "invalidate_on_target_io_error_or_mapping_change",
        "target_sds_endpoints": sds_endpoints,
        "segments": segments,
        "read_policy": "first_healthy",
    }


@router.post("/vol/{volume_id}/io/write")
def write_volume_bytes(volume_id: int, payload: VolumeWriteRequest, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")

    mapping = db.scalars(select(VolumeMapping).where(
        VolumeMapping.volume_id == volume_id, VolumeMapping.sdc_id == payload.sdc_id
    )).first()
    if not mapping:
        raise HTTPException(status_code=403, detail="Volume is not mapped to this SDC")

    mode = getattr(mapping, "access_mode", "")
    mode_value = str(getattr(mode, "value", mode))
    if str(mode_value).lower() == "readonly":
        raise HTTPException(status_code=403, detail="Mapping is read-only")

    manager = VolumeManager(db)
    details = manager.get_volume_details(volume_id)
    if not details:
        raise HTTPException(status_code=404, detail="Volume not found")

    replica_paths = details.get("replica_paths", [])
    if not replica_paths:
        raise HTTPException(status_code=404, detail="No replica files available for volume")

    backend = RealStorageBackend()
    volume_obj = db.scalars(select(Volume).where(Volume.id == volume_id)).first()
    if not volume_obj:
        raise HTTPException(status_code=404, detail="Volume not found")

    volume_size_bytes = int(float(getattr(volume_obj, "size_gb", 0.0) or 0.0) * 1024 * 1024 * 1024)
    io_mode = _io_mode()
    write_policy = _write_ack_policy()

    try:
        data = backend.decode_base64(payload.data_b64)
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="No data provided for write")

        segments = _build_chunk_segments(db, volume_obj, payload.offset_bytes, len(data))
        if not segments:
            raise HTTPException(status_code=400, detail="No segments generated for write")

        replicas_written = 0
        io_path = "network"
        cursor = 0

        for segment in segments:
            segment_len = int(segment.get("segment_length_bytes", 0) or 0)
            segment_offset = int(segment.get("segment_offset_bytes", payload.offset_bytes) or payload.offset_bytes)
            targets = segment.get("targets", []) or []
            if segment_len <= 0:
                continue

            if not targets:
                if io_mode == IO_MODE_NETWORK_ONLY:
                    raise HTTPException(status_code=503, detail=f"No ACTIVE SDS targets for chunk {segment.get('chunk_id')}")
                io_path = "local"
                break

            segment_data = data[cursor:cursor + segment_len]
            segment_b64 = base64.b64encode(segment_data).decode("ascii")
            successes = 0

            for target in targets:
                host = str(target.get("host", "") or "")
                port = int(target.get("port", 0) or 0)
                if not host or port <= 0:
                    continue
                try:
                    client = SDCSocketClient(host, port, timeout_seconds=1.0)
                    try:
                        client.init_volume(str(volume_id), volume_size_bytes)
                    except Exception:
                        pass
                    write_resp = client.write(str(volume_id), segment_offset, segment_b64)
                    if write_resp.get("ok"):
                        successes += 1
                except Exception:
                    continue

            required = _required_acks_for_segment(len(targets), write_policy)
            if successes < required:
                if io_mode == IO_MODE_NETWORK_ONLY:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Segment write failed for chunk {segment.get('chunk_id')}: {successes}/{required} acks ({write_policy})",
                    )
                io_path = "local"
                break

            chunk_id = int(segment.get("chunk_id", 0) or 0)
            chunk_obj = db.scalars(select(Chunk).where(Chunk.id == chunk_id)).first()
            if chunk_obj is not None:
                generation = int(getattr(chunk_obj, "generation", 0) or 0) + 1
                checksum = hashlib.sha256(segment_data).hexdigest()
                setattr(chunk_obj, "generation", generation)
                setattr(chunk_obj, "checksum", checksum)
                setattr(chunk_obj, "last_write_offset_bytes", segment_offset)
                setattr(chunk_obj, "last_write_length_bytes", segment_len)
                setattr(chunk_obj, "last_write_at", datetime.utcnow())

            replicas_written += successes
            cursor += segment_len

        if io_path == "local":
            replicas_written = backend.write_to_replica_paths(replica_paths, payload.offset_bytes, data)

    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()

    return {
        "status": "written",
        "volume_id": volume_id,
        "sdc_id": payload.sdc_id,
        "offset_bytes": payload.offset_bytes,
        "bytes_written": len(data),
        "replicas_written": replicas_written,
        "io_path": io_path,
        "io_mode": io_mode,
        "write_policy": write_policy,
    }


@router.post("/vol/{volume_id}/io/read")
def read_volume_bytes(volume_id: int, payload: VolumeReadRequest, db: Session = Depends(get_db)):
    if not has_active_capability(db, "MDM"):
        raise HTTPException(status_code=400, detail="No ACTIVE MDM-capable node available")

    mapping = db.scalars(select(VolumeMapping).where(
        VolumeMapping.volume_id == volume_id, VolumeMapping.sdc_id == payload.sdc_id
    )).first()
    if not mapping:
        raise HTTPException(status_code=403, detail="Volume is not mapped to this SDC")

    manager = VolumeManager(db)
    details = manager.get_volume_details(volume_id)
    if not details:
        raise HTTPException(status_code=404, detail="Volume not found")

    replica_paths = details.get("replica_paths", [])
    if not replica_paths:
        raise HTTPException(status_code=404, detail="No replica files available for volume")

    backend = RealStorageBackend()
    volume_obj = db.scalars(select(Volume).where(Volume.id == volume_id)).first()
    if not volume_obj:
        raise HTTPException(status_code=404, detail="Volume not found")

    volume_size_bytes = int(float(getattr(volume_obj, "size_gb", 0.0) or 0.0) * 1024 * 1024 * 1024)
    io_mode = _io_mode()

    try:
        if int(payload.length_bytes or 0) <= 0:
            raise HTTPException(status_code=400, detail="length_bytes must be > 0")

        segments = _build_chunk_segments(db, volume_obj, payload.offset_bytes, payload.length_bytes)
        if not segments:
            raise HTTPException(status_code=400, detail="No segments generated for read")

        parts: list[bytes] = []
        io_path = "network"

        for segment in segments:
            segment_len = int(segment.get("segment_length_bytes", 0) or 0)
            segment_offset = int(segment.get("segment_offset_bytes", payload.offset_bytes) or payload.offset_bytes)
            targets = segment.get("targets", []) or []
            if segment_len <= 0:
                continue

            if not targets:
                if io_mode == IO_MODE_NETWORK_ONLY:
                    raise HTTPException(status_code=503, detail=f"No ACTIVE SDS targets for chunk {segment.get('chunk_id')}")
                io_path = "local"
                break

            read_part = b""
            for target in targets:
                host = str(target.get("host", "") or "")
                port = int(target.get("port", 0) or 0)
                if not host or port <= 0:
                    continue
                try:
                    client = SDCSocketClient(host, port, timeout_seconds=1.0)
                    try:
                        client.init_volume(str(volume_id), volume_size_bytes)
                    except Exception:
                        pass
                    read_resp = client.read(str(volume_id), segment_offset, segment_len)
                    if read_resp.get("ok"):
                        read_part = backend.decode_base64(str(read_resp.get("data_b64", "")))
                        break
                except Exception:
                    continue

            if not read_part or len(read_part) != segment_len:
                if io_mode == IO_MODE_NETWORK_ONLY:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Segment read failed for chunk {segment.get('chunk_id')}",
                    )
                io_path = "local"
                break

            parts.append(read_part)

        if io_path == "local":
            data = backend.read_from_replica_paths(replica_paths, payload.offset_bytes, payload.length_bytes)
        else:
            data = b"".join(parts)

    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    utf8_text = None
    try:
        utf8_text = data.decode("utf-8")
    except Exception:
        utf8_text = None

    return {
        "status": "read",
        "volume_id": volume_id,
        "sdc_id": payload.sdc_id,
        "offset_bytes": payload.offset_bytes,
        "bytes_read": len(data),
        "data_b64": backend.encode_base64(data),
        "utf8_text": utf8_text,
        "io_path": io_path,
        "io_mode": io_mode,
    }
