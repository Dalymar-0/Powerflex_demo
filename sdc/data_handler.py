from dataclasses import dataclass, field
from typing import Any
import base64
import os
import time

import requests

from shared.sdc_socket_client import SDCSocketClient


@dataclass
class SDCCapability:
    node_id: str
    mapped_volumes: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan_cache_ttl_seconds: float = 30.0

    def __post_init__(self) -> None:
        configured_ttl = str(os.getenv("POWERFLEX_PLAN_CACHE_TTL_SECONDS", "30")).strip()
        try:
            ttl = float(configured_ttl)
            if ttl >= 0:
                self.plan_cache_ttl_seconds = ttl
        except Exception:
            pass

    def map_volume(self, volume_id: str, metadata: dict[str, Any]) -> None:
        self.mapped_volumes[volume_id] = metadata

    def unmap_volume(self, volume_id: str) -> None:
        if volume_id in self.mapped_volumes:
            del self.mapped_volumes[volume_id]

    def list_mappings(self) -> list[str]:
        return sorted(self.mapped_volumes.keys())

    def _plan_cache_key(
        self,
        operation: str,
        volume_id: int,
        sdc_id: int,
        offset_bytes: int,
        length_bytes: int,
    ) -> str:
        return f"{operation}:{int(volume_id)}:{int(sdc_id)}:{int(offset_bytes)}:{int(length_bytes)}"

    def invalidate_plan_cache(self, volume_id: int | None = None, operation: str | None = None) -> None:
        if volume_id is None and operation is None:
            self.plan_cache.clear()
            return

        survivors: dict[str, dict[str, Any]] = {}
        for key, value in self.plan_cache.items():
            parts = key.split(":")
            if len(parts) != 5:
                continue
            key_operation = parts[0]
            key_volume_id = int(parts[1])
            if volume_id is not None and key_volume_id != int(volume_id):
                survivors[key] = value
                continue
            if operation is not None and key_operation != operation:
                survivors[key] = value
                continue
        self.plan_cache = survivors

    def _load_plan_from_cache(self, cache_key: str) -> dict[str, Any] | None:
        entry = self.plan_cache.get(cache_key)
        if not entry:
            return None
        expires_at = float(entry.get("expires_at", 0) or 0)
        if self.plan_cache_ttl_seconds > 0 and time.time() >= expires_at:
            self.plan_cache.pop(cache_key, None)
            return None
        return entry.get("plan")

    def _store_plan_in_cache(self, cache_key: str, plan: dict[str, Any]) -> None:
        expires_at = time.time() + max(0.0, float(self.plan_cache_ttl_seconds))
        self.plan_cache[cache_key] = {"plan": plan, "expires_at": expires_at}

    def _get_or_fetch_plan(
        self,
        control_plane_url: str,
        volume_id: int,
        sdc_id: int,
        offset_bytes: int,
        length_bytes: int,
        operation: str,
        force_refresh: bool = False,
    ) -> tuple[dict[str, Any], str]:
        cache_key = self._plan_cache_key(operation, volume_id, sdc_id, offset_bytes, length_bytes)
        if not force_refresh:
            cached = self._load_plan_from_cache(cache_key)
            if cached:
                return cached, "cache"

        payload = {
            "sdc_id": sdc_id,
            "offset_bytes": offset_bytes,
            "length_bytes": length_bytes,
        }
        plan_resp = requests.post(
            f"{control_plane_url}/vol/{volume_id}/io/plan/{operation}",
            json=payload,
            timeout=10,
        )
        plan_resp.raise_for_status()
        plan = plan_resp.json()
        self._store_plan_in_cache(cache_key, plan)
        return plan, "control_plane"

    def write_direct(
        self,
        control_plane_url: str,
        volume_id: int,
        sdc_id: int,
        offset_bytes: int,
        data: bytes,
        timeout_seconds: float = 1.0,
        force_refresh_plan: bool = False,
    ) -> dict[str, Any]:
        plan, plan_source = self._get_or_fetch_plan(
            control_plane_url=control_plane_url,
            volume_id=volume_id,
            sdc_id=sdc_id,
            offset_bytes=offset_bytes,
            length_bytes=len(data),
            operation="write",
            force_refresh=force_refresh_plan,
        )

        segments = plan.get("segments", [])
        if not isinstance(segments, list) or not segments:
            raise RuntimeError("No chunk segments returned by MDM for direct write")

        writes: list[dict[str, Any]] = []
        successes = 0
        cursor = 0
        target_io_error = False
        for segment in segments:
            segment_len = int(segment.get("segment_length_bytes", 0) or 0)
            segment_offset = int(segment.get("segment_offset_bytes", offset_bytes) or offset_bytes)
            targets = segment.get("targets", []) or []
            if segment_len <= 0:
                continue
            segment_data = data[cursor:cursor + segment_len]
            segment_b64 = base64.b64encode(segment_data).decode("ascii")
            for target in targets:
                host = str(target.get("host", "") or "")
                port = int(target.get("port", 0) or 0)
                if not host or port <= 0:
                    continue
                try:
                    client = SDCSocketClient(host, port, timeout_seconds=timeout_seconds)
                    result = client.write(str(volume_id), segment_offset, segment_b64)
                    ok = bool(result.get("ok"))
                    if not ok:
                        target_io_error = True
                    writes.append(
                        {
                            "chunk_id": segment.get("chunk_id"),
                            "host": host,
                            "port": port,
                            "ok": ok,
                            "result": result,
                        }
                    )
                    if ok:
                        successes += 1
                except Exception as exc:
                    target_io_error = True
                    writes.append(
                        {
                            "chunk_id": segment.get("chunk_id"),
                            "host": host,
                            "port": port,
                            "ok": False,
                            "error": str(exc),
                        }
                    )
            cursor += segment_len

        expected_writes = sum(len((segment.get("targets", []) or [])) for segment in segments)

        if target_io_error:
            self.invalidate_plan_cache(volume_id=volume_id)

        return {
            "operation": "write",
            "volume_id": volume_id,
            "sdc_id": sdc_id,
            "offset_bytes": offset_bytes,
            "bytes_written": len(data),
            "segment_count": len(segments),
            "target_count": expected_writes,
            "success_count": successes,
            "results": writes,
            "plan_generation": plan.get("plan_generation"),
            "plan_source": plan_source,
            "cache_invalidated": target_io_error,
        }

    def read_direct(
        self,
        control_plane_url: str,
        volume_id: int,
        sdc_id: int,
        offset_bytes: int,
        length_bytes: int,
        timeout_seconds: float = 1.0,
        force_refresh_plan: bool = False,
    ) -> dict[str, Any]:
        plan, plan_source = self._get_or_fetch_plan(
            control_plane_url=control_plane_url,
            volume_id=volume_id,
            sdc_id=sdc_id,
            offset_bytes=offset_bytes,
            length_bytes=length_bytes,
            operation="read",
            force_refresh=force_refresh_plan,
        )

        segments = plan.get("segments", [])
        if not isinstance(segments, list) or not segments:
            raise RuntimeError("No chunk segments returned by MDM for direct read")

        data_parts: list[bytes] = []
        attempts: list[dict[str, Any]] = []
        target_io_error = False
        for segment in segments:
            segment_len = int(segment.get("segment_length_bytes", 0) or 0)
            segment_offset = int(segment.get("segment_offset_bytes", offset_bytes) or offset_bytes)
            targets = segment.get("targets", []) or []
            if segment_len <= 0:
                continue
            segment_ok = False
            for target in targets:
                host = str(target.get("host", "") or "")
                port = int(target.get("port", 0) or 0)
                if not host or port <= 0:
                    continue
                try:
                    client = SDCSocketClient(host, port, timeout_seconds=timeout_seconds)
                    result = client.read(str(volume_id), segment_offset, segment_len)
                    ok = bool(result.get("ok"))
                    if not ok:
                        target_io_error = True
                    attempts.append({"chunk_id": segment.get("chunk_id"), "host": host, "port": port, "ok": ok})
                    if ok:
                        data_b64 = str(result.get("data_b64", "") or "")
                        segment_data = base64.b64decode(data_b64.encode("ascii")) if data_b64 else b""
                        if len(segment_data) == segment_len:
                            data_parts.append(segment_data)
                            segment_ok = True
                            break
                except Exception as exc:
                    target_io_error = True
                    attempts.append(
                        {
                            "chunk_id": segment.get("chunk_id"),
                            "host": host,
                            "port": port,
                            "ok": False,
                            "error": str(exc),
                        }
                    )
            if not segment_ok:
                self.invalidate_plan_cache(volume_id=volume_id)
                raise RuntimeError(f"Direct read failed for segment chunk_id={segment.get('chunk_id')}: {attempts}")

        data = b"".join(data_parts)
        if target_io_error:
            self.invalidate_plan_cache(volume_id=volume_id)
        return {
            "operation": "read",
            "volume_id": volume_id,
            "sdc_id": sdc_id,
            "offset_bytes": offset_bytes,
            "length_bytes": length_bytes,
            "bytes_read": len(data),
            "data": data,
            "segment_count": len(segments),
            "attempts": attempts,
            "plan_generation": plan.get("plan_generation"),
            "plan_source": plan_source,
            "cache_invalidated": target_io_error,
        }
