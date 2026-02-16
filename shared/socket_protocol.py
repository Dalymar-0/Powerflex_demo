from __future__ import annotations

import json
import socket
from typing import Any


def send_json_line(sock: socket.socket, payload: dict[str, Any]) -> None:
    body = (json.dumps(payload) + "\n").encode("utf-8")
    sock.sendall(body)


def read_json_line(sock: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break

    if not data:
        raise ConnectionError("No data received")

    line = data.split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))
