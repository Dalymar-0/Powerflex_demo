from typing import Any, Set, Tuple, Optional

from sqlalchemy.orm import Session

from mdm.models import ClusterNode, ClusterNodeStatus


def _caps(node: ClusterNode) -> Set[str]:
    raw = getattr(node, "capabilities", "") or ""
    return {cap.strip().upper() for cap in raw.split(",") if cap.strip()}


def has_active_capability(db: Session, capability: str) -> bool:
    wanted = capability.upper()
    nodes = db.query(ClusterNode).all()
    for node in nodes:
        status = getattr(node, "status", None)
        if status is None:
            status_str = ClusterNodeStatus.UNKNOWN.value
        elif hasattr(status, "value"):
            status_str = str(status.value)
        else:
            status_str = str(status)
        if status_str == ClusterNodeStatus.ACTIVE.value and wanted in _caps(node):
            return True
    return False


def validate_node_capability(
    db: Session,
    node_id: str,
    capability: str,
    require_active: bool = True,
) -> Tuple[bool, str, Optional[ClusterNode]]:
    node = db.query(ClusterNode).filter(ClusterNode.node_id == node_id).first()
    if node is None:
        return False, f"Cluster node '{node_id}' not registered", None

    status = getattr(node, "status", None)
    if status is None:
        status_str = ClusterNodeStatus.UNKNOWN.value
    elif hasattr(status, "value"):
        status_str = str(status.value)
    else:
        status_str = str(status)
    if require_active and status_str != ClusterNodeStatus.ACTIVE.value:
        return False, f"Cluster node '{node_id}' is not ACTIVE", node

    wanted = capability.upper()
    if wanted not in _caps(node):
        return False, f"Cluster node '{node_id}' missing capability '{wanted}'", node

    return True, "ok", node


def sds_is_eligible(db: Session, sds_obj: Any) -> bool:
    cluster_node_id = getattr(sds_obj, "cluster_node_id", None)
    if not cluster_node_id:
        return False
    ok, _, _ = validate_node_capability(db, cluster_node_id, "SDS", require_active=True)
    return ok
