from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import socket

from shared.socket_protocol import read_json_line, send_json_line


@dataclass
class SDCSocketClient:
    sds_host: str
    sds_port: int
    timeout_seconds: float = 10.0

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout_seconds)
        try:
            sock.connect((self.sds_host, self.sds_port))
            send_json_line(sock, payload)
            return read_json_line(sock)
        finally:
            sock.close()

    def health(self) -> dict[str, Any]:
        return self.request({"action": "health"})

    def init_volume(self, volume_id: str, size_bytes: int) -> dict[str, Any]:
        return self.request({"action": "init_volume", "volume_id": volume_id, "size_bytes": size_bytes})

    def write(self, volume_id: str, offset_bytes: int, data_b64: str) -> dict[str, Any]:
        return self.request({
            "action": "write",
            "volume_id": volume_id,
            "offset_bytes": offset_bytes,
            "data_b64": data_b64,
        })

    def read(self, volume_id: str, offset_bytes: int, length_bytes: int) -> dict[str, Any]:
        return self.request({
            "action": "read",
            "volume_id": volume_id,
            "offset_bytes": offset_bytes,
            "length_bytes": length_bytes,
        })
