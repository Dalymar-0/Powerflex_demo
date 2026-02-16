from __future__ import annotations

import json
import os
import base64
import shutil
from pathlib import Path
from typing import Iterable

from mdm.models import SDSNode, SDCClient, Volume


class RealStorageBackend:
    def __init__(self, root_path: str | None = None):
        configured = root_path or os.getenv("POWERFLEX_STORAGE_ROOT") or "./vm_storage"
        self.root = Path(configured)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _node_folder(node_id: str) -> str:
        return "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in node_id)

    @staticmethod
    def _volume_bytes(size_gb: float) -> int:
        return int(float(size_gb) * 1024 * 1024 * 1024)

    @staticmethod
    def _volume_id(volume: Volume) -> int:
        return int(getattr(volume, "id", 0) or 0)

    @staticmethod
    def _volume_size_gb(volume: Volume) -> float:
        return float(getattr(volume, "size_gb", 0.0) or 0.0)

    def _sds_volume_path(self, volume_id: int, sds: SDSNode) -> Path:
        cluster_node_id = getattr(sds, "cluster_node_id", None) or f"sds-{sds.id}"
        folder = self.root / "sds" / self._node_folder(str(cluster_node_id)) / "volumes"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"vol_{volume_id}.img"

    def _sdc_mapping_path(self, volume_id: int, sdc: SDCClient) -> Path:
        cluster_node_id = getattr(sdc, "cluster_node_id", None) or f"sdc-{sdc.id}"
        folder = self.root / "sdc" / self._node_folder(str(cluster_node_id)) / "mappings"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"vol_{volume_id}.json"

    def _sdc_device_path(self, volume_id: int, sdc: SDCClient) -> Path:
        cluster_node_id = getattr(sdc, "cluster_node_id", None) or f"sdc-{sdc.id}"
        folder = self.root / "sdc" / self._node_folder(str(cluster_node_id)) / "devices"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"naa.{volume_id}.img"

    def ensure_volume_replicas(self, volume: Volume, replica_sds_nodes: Iterable[SDSNode]) -> list[str]:
        paths: list[str] = []
        volume_id = self._volume_id(volume)
        target_size = self._volume_bytes(self._volume_size_gb(volume))

        for sds in replica_sds_nodes:
            file_path = self._sds_volume_path(volume_id, sds)
            with open(file_path, "ab"):
                pass
            with open(file_path, "r+b") as handle:
                handle.truncate(target_size)
            paths.append(str(file_path.resolve()))

        return paths

    def resize_volume_replicas(self, volume_id: int, new_size_gb: float, replica_sds_nodes: Iterable[SDSNode]) -> list[str]:
        paths: list[str] = []
        target_size = self._volume_bytes(new_size_gb)

        for sds in replica_sds_nodes:
            file_path = self._sds_volume_path(volume_id, sds)
            if not file_path.exists():
                with open(file_path, "ab"):
                    pass
            with open(file_path, "r+b") as handle:
                handle.truncate(target_size)
            paths.append(str(file_path.resolve()))

        return paths

    def write_mapping(self, volume: Volume, sdc: SDCClient, access_mode: str, replica_paths: list[str]) -> str:
        volume_id = self._volume_id(volume)
        mapping_path = self._sdc_mapping_path(volume_id, sdc)
        device_path = self._sdc_device_path(volume_id, sdc)
        mapping_payload = {
            "volume_id": volume_id,
            "volume_name": volume.name,
            "size_gb": self._volume_size_gb(volume),
            "access_mode": access_mode,
            "replicas": replica_paths,
            "device_path": str(device_path.resolve()),
        }
        mapping_path.write_text(json.dumps(mapping_payload, indent=2), encoding="utf-8")
        return str(mapping_path.resolve())

    def create_mapped_device(self, volume: Volume, sdc: SDCClient, replica_paths: list[str]) -> str:
        if not replica_paths:
            raise FileNotFoundError("No replica paths available for mapped device")

        volume_id = self._volume_id(volume)
        device_path = self._sdc_device_path(volume_id, sdc)
        source_path = Path(replica_paths[0])

        if device_path.exists() or device_path.is_symlink():
            device_path.unlink()

        try:
            os.link(source_path, device_path)
        except OSError:
            try:
                os.symlink(source_path, device_path)
            except OSError:
                shutil.copy2(source_path, device_path)

        return str(device_path.resolve())

    def remove_mapped_device(self, volume_id: int, sdc: SDCClient) -> None:
        device_path = self._sdc_device_path(volume_id, sdc)
        if device_path.exists() or device_path.is_symlink():
            device_path.unlink()

    def remove_mapping(self, volume_id: int, sdc: SDCClient) -> None:
        mapping_path = self._sdc_mapping_path(volume_id, sdc)
        if mapping_path.exists():
            mapping_path.unlink()

    def remove_volume_replicas(self, volume_id: int, replica_sds_nodes: Iterable[SDSNode]) -> None:
        for sds in replica_sds_nodes:
            file_path = self._sds_volume_path(volume_id, sds)
            if file_path.exists():
                file_path.unlink()

    def list_replica_paths(self, volume_id: int, replica_sds_nodes: Iterable[SDSNode]) -> list[str]:
        paths: list[str] = []
        for sds in replica_sds_nodes:
            file_path = self._sds_volume_path(volume_id, sds)
            if file_path.exists():
                paths.append(str(file_path.resolve()))
        return sorted(paths)

    def list_mapping_paths(self, volume_id: int, sdcs: Iterable[SDCClient]) -> list[str]:
        paths: list[str] = []
        for sdc in sdcs:
            mapping_path = self._sdc_mapping_path(volume_id, sdc)
            if mapping_path.exists():
                paths.append(str(mapping_path.resolve()))
        return sorted(paths)

    def list_mapped_device_paths(self, volume_id: int, sdcs: Iterable[SDCClient]) -> list[str]:
        paths: list[str] = []
        for sdc in sdcs:
            device_path = self._sdc_device_path(volume_id, sdc)
            if device_path.exists() or device_path.is_symlink():
                paths.append(str(device_path.resolve()))
        return sorted(paths)

    def write_to_replica_paths(self, replica_paths: Iterable[str], offset_bytes: int, data: bytes) -> int:
        if offset_bytes < 0:
            raise ValueError("offset_bytes must be >= 0")
        if not data:
            return 0

        written = 0
        for raw_path in replica_paths:
            path = Path(raw_path)
            if not path.exists():
                continue
            with open(path, "r+b") as handle:
                handle.seek(offset_bytes)
                handle.write(data)
            written += 1

        if written == 0:
            raise FileNotFoundError("No replica files found to write")
        return written

    def read_from_replica_paths(self, replica_paths: Iterable[str], offset_bytes: int, length_bytes: int) -> bytes:
        if offset_bytes < 0:
            raise ValueError("offset_bytes must be >= 0")
        if length_bytes <= 0:
            raise ValueError("length_bytes must be > 0")

        for raw_path in replica_paths:
            path = Path(raw_path)
            if not path.exists():
                continue
            with open(path, "rb") as handle:
                handle.seek(offset_bytes)
                return handle.read(length_bytes)

        raise FileNotFoundError("No replica files found to read")

    @staticmethod
    def encode_base64(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def decode_base64(text: str) -> bytes:
        return base64.b64decode(text.encode("ascii"), validate=True)
